"""Persisted preparation jobs. Preparing data never registers a trained adapter."""
import json
import hashlib
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from dataset import TASKS, prepare_dataset, read_upload
from training import write_training_request

ACTIVE = ('queued', 'collecting', 'preparing')

class JobStore:
    def __init__(self, root, corpus_dir=None, materials_dir=None):
        self.corpus_dir = Path(corpus_dir) if corpus_dir else None
        self.materials_dir = Path(materials_dir) if materials_dir else None
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        # Interrupted threads cannot resume after server restart; keep their evidence.
        for path in self.root.glob('*/job.json'):
            data = json.loads(path.read_text())
            if data.get('status') in ('queued','collecting','preparing'):
                data.update(status='failed', error='Server restarted during preparation; start a new job.')
                self._save(data)

    def _save(self, job):
        with self.lock:
            directory = self.root/job['id']
            directory.mkdir(parents=True, exist_ok=True)
            temp = directory/'job.tmp'
            temp.write_text(json.dumps(job, indent=2)+'\n')
            temp.replace(directory/'job.json')

    def get(self, job_id):
        if not isinstance(job_id,str) or not job_id.startswith('j') or len(job_id) != 33 or not all(c in '0123456789abcdef' for c in job_id[1:]):
            raise ValueError('invalid job id')
        return json.loads((self.root/job_id/'job.json').read_text())

    def list(self):
        return sorted([json.loads(p.read_text()) for p in self.root.glob('*/job.json')], key=lambda j:j['created_at'], reverse=True)

    def artifact(self, job_id, name):
        self.get(job_id)
        if name not in ('manifest.json','training_request.json','train.jsonl','validation.jsonl','test.jsonl','rejected.json','examples.json','dataset_bundle.zip','public_market_records.jsonl','market_extraction_bundle.zip'):
            raise ValueError('unknown artifact')
        return self.root/job_id/'dataset'/name

    def public_records(self):
        """Reuse archived corpus and successful collections, newest publication snapshot wins."""
        roots = [self.corpus_dir] if self.corpus_dir else []
        roots += [self.root/j['id']/'collection' for j in reversed(self.list())
                  if j['status'] not in ACTIVE and j['status'] != 'failed']
        records = {}
        for root in roots:
            for name in ('market_awards.jsonl', 'public_tenders.jsonl'):
                path = root/name
                if path.is_file():
                    for line in path.read_text().splitlines():
                        if line.strip():
                            record = json.loads(line)
                            records[record['publication_id']] = record
        return list(records.values())

    def start_collection(self, urls, search_hvac=False):
        from collect.simap import project_id
        if not isinstance(urls, list) or len(urls) > 20 or (not urls and not search_hvac):
            raise ValueError('Provide 1–20 simap project URLs or enable historical HVAC search.')
        for url in urls:
            project_id(url)
        job = {'id':'j'+uuid.uuid4().hex, 'kind':'collection', 'task':'market_extraction',
               'created_at':datetime.now(timezone.utc).isoformat(), 'status':'queued',
               'links':'\n'.join(urls), 'search_hvac':bool(search_hvac), 'artifacts':[], 'error':None}
        self._save(job)
        threading.Thread(target=self._collect, args=(job, urls), daemon=True).start()
        return dict(job)

    def _collect(self, job, urls):
        try:
            from collect.simap import collect_sources, DEFAULT_SEARCHES
            job['status'] = 'collecting'; self._save(job)
            result = collect_sources(urls, self.root/job['id']/'collection',
                searches=DEFAULT_SEARCHES if job['search_hvac'] else [], max_pages=2, max_awards=20)
            job.update(status='collected' if result['records'] else 'failed',
                public_record_count=len(result['records']), collection_errors=result['errors'],
                error=None if result['records'] else 'No publications collected. Check the source URLs and collection errors.')
        except Exception as exc:
            job.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        self._save(job)

    def start(self, task, base_model, links, upload_dir, include_existing=False):
        if task not in TASKS:
            raise ValueError('unknown task')
        from collect.simap import project_id
        if len(links.split()) > 20:
            raise ValueError('At most 20 simap project URLs are accepted.')
        for url in links.split():
            project_id(url)
        job = {'id':'j'+uuid.uuid4().hex,'kind':'preparation','task':task,'base_model':base_model,
               'created_at':datetime.now(timezone.utc).isoformat(),'status':'queued','links':links,
               'artifacts':[], 'error':None, 'include_existing':bool(include_existing)}
        self._save(job)
        threading.Thread(target=self._run,args=(job, Path(upload_dir)),daemon=True).start()
        return dict(job)

    def _run(self, job, uploads):
        try:
            directory = self.root/job['id']
            records, public_records, collection_errors, upload_sources = [], [], [], []
            if job.get('include_existing') and job['task'] == 'market_extraction':
                public_records.extend(self.public_records())
            if job.get('include_existing') and job['task'] == 'input_processing' and self.materials_dir:
                from prepare_sponsor import sponsor_examples
                records.extend(sponsor_examples(self.materials_dir))
                for name in ('example_lv_positions.csv', 'catalog.csv', 'BKP_244_LV_Lueftung_260804.pdf'):
                    source = self.materials_dir/name
                    upload_sources.append({'file':name,'sha256':hashlib.sha256(source.read_bytes()).hexdigest(), 'source':'sponsor'})
            if job['links'].strip():
                job['status'] = 'collecting'; self._save(job)
                from collect.simap import collect_sources
                result = collect_sources(job['links'].split(), directory/'collection',
                    searches=[], max_pages=2, max_awards=20)
                public_records.extend(result.get('records', []))
                collection_errors = result.get('errors', [])
            public_records = list({r['publication_id']:r for r in public_records}.values())
            job['status'] = 'preparing'; self._save(job)
            for path in sorted(uploads.glob(job['task']+'_*')):
                raw_upload = path.read_bytes()
                records.extend(read_upload(raw_upload,job['task']))
                upload_sources.append({'file':path.name,'sha256':hashlib.sha256(raw_upload).hexdigest()})
            dataset_dir = directory/'dataset'
            dataset_dir.mkdir(parents=True, exist_ok=True)
            # Public outcomes remain auditable source material, separate from own bid supervision.
            (dataset_dir/'public_market_records.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in public_records))
            market_manifest = None
            if public_records:
                market_examples = []
                for record in public_records:
                    provenance = record.get('provenance', {})
                    raw_path = Path(provenance.get('raw_path', ''))
                    if not raw_path.is_file():
                        candidate = directory/'collection'/raw_path
                        raw_path = candidate if candidate.is_file() else raw_path
                    if not raw_path.is_file() and self.corpus_dir:
                        raw_path = self.corpus_dir/'raw'/'simap'/(str(provenance.get('sha256', ''))+'.json')
                    if not raw_path.is_file():
                        raise ValueError('Public source snapshot is missing for publication ' + str(record.get('publication_id')))
                    raw = raw_path.read_bytes()
                    if hashlib.sha256(raw).hexdigest() != provenance.get('sha256'):
                        raise ValueError('Public source snapshot hash mismatch')
                    source = json.loads(raw)
                    target = {key:record[key] for key in ('record_type','title','description','buyer','canton',
                        'publication_date','cpv_codes','bkp_codes') if record.get(key) is not None}
                    market_examples.append({'project_id':record.get('tender_id') or record.get('project_id'),
                        'source_kind':'public_structured_api', 'provenance':provenance,
                        'input':{'source_document':source},'target':target})
                market_dir = directory/'market_extraction'
                market_manifest = prepare_dataset(market_examples,'market_extraction',market_dir,job['base_model'])
                market_manifest['supervision'] = 'deterministic structured API normalization; evaluate extraction quality before deployment'
                (market_dir/'manifest.json').write_text(json.dumps(market_manifest,indent=2)+'\n')
                write_training_request(market_dir,market_manifest)
                with zipfile.ZipFile(dataset_dir/'market_extraction_bundle.zip','w',zipfile.ZIP_DEFLATED) as bundle:
                    for artifact in market_dir.iterdir():
                        bundle.write(artifact, artifact.name)
            if job['task'] == 'market_extraction' and public_records:
                records.extend(market_examples)
            manifest = prepare_dataset(records,job['task'],dataset_dir,job['base_model'])
            manifest['upload_sources'] = upload_sources
            manifest['public_record_count'] = len(public_records)
            (dataset_dir/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
            write_training_request(dataset_dir,manifest)
            with zipfile.ZipFile(dataset_dir/'dataset_bundle.zip','w',zipfile.ZIP_DEFLATED) as bundle:
                for name in ('train.jsonl','validation.jsonl','test.jsonl','manifest.json',
                             'training_request.json','rejected.json','examples.json'):
                    bundle.write(dataset_dir/name, name)
            job.update(status=manifest['status'], manifest=manifest, collection_errors=collection_errors,
                       public_record_count=len(public_records), market_extraction_manifest=market_manifest, awaiting='Explicit LoRA training provider endpoint and capability contract',
                       artifacts=[p.name for p in dataset_dir.iterdir() if p.is_file()])
            self._save(job)
        except Exception as exc:
            job.update(status='failed',error=f'{type(exc).__name__}: {exc}')
            self._save(job)
