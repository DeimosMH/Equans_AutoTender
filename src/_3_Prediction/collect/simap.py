"""Bounded collection from simap's public API; public awards are NOT own-bid labels."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

BASE = 'https://www.simap.ch'
ATTRIBUTION = ('Dies ist keine amtliche Veröffentlichung. Die amtliche Veröffentlichung '
               'ist auf simap.ch verfügbar. Quelle: simap.ch.')
HVAC = re.compile(r'lüft|ventilation|climatis|\bhlk|heizung|gebäudetechnik|klima|chauffage', re.I)
DEFAULT_SEARCHES = [('Lüftung', 'de'), ('HLK', 'de'), ('ventilation', 'fr')]


def project_id(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in {'simap.ch', 'www.simap.ch'} or parsed.port not in {None,443} or parsed.username or parsed.password:
        raise ValueError('Only HTTPS simap.ch project-detail URLs are accepted')
    match = re.fullmatch(r'/(?:de|fr|it|en)/project-detail/([0-9a-fA-F-]{36})/?', parsed.path)
    if not match or parsed.query or parsed.fragment:
        raise ValueError('Expected https://www.simap.ch/de/project-detail/<UUID>')
    return str(uuid.UUID(match.group(1)))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Client:
    def __init__(self, root, interval=1.0):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.interval = max(1.0, interval)
        self.last_request = 0.0
        self.opener = build_opener(NoRedirect())

    def get(self, url):
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.netloc != 'www.simap.ch' or not parsed.path.startswith('/api/publications/'):
            raise ValueError('API URL is outside the simap allowlist')
        for attempt in range(3):
            time.sleep(max(0, self.last_request + self.interval - time.monotonic()))
            self.last_request = time.monotonic()
            try:
                with self.opener.open(Request(url, headers={'User-Agent':'EquansAutoTender/1.0 (public award research)', 'Accept':'application/json'}), timeout=30) as response:
                    raw = response.read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024:
                    raise ValueError('API response exceeds 8 MiB')
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError('Expected API object')
                stamp = datetime.now(timezone.utc).isoformat()
                digest = hashlib.sha256(raw).hexdigest()
                target = self.root / (digest + '.json')
                target.write_bytes(raw)
                return data, {'api_url':url, 'raw_path':str(target), 'sha256':digest,'retrieved_at':stamp}
            except HTTPError as exc:
                if exc.code not in {429,500,502,503,504} or attempt == 2:
                    raise
                retry = exc.headers.get('Retry-After', '')
                time.sleep(min(30, max(1, int(retry) if retry.isdigit() else 2 ** attempt)))


def text(value):
    if isinstance(value, dict):
        return next((value.get(lang) for lang in ['de','fr','it','en'] if value.get(lang)), '')
    return value if isinstance(value, str) else ''


def normalize(detail, provenance):
    base = detail.get('base') or {}
    info = detail.get('project-info') or {}
    procurement = detail.get('procurement') or {}
    decision = detail.get('decision') or {}
    buyer_address = info.get('procOfficeAddress') or {}
    pid = str(uuid.UUID(base['projectId']))
    pub_type = detail.get('type') or base.get('type')
    provenance = dict(provenance, source_url=f'{BASE}/de/project-detail/{pid}', source='simap', attribution=ATTRIBUTION)
    cpv = procurement.get('cpvCode') or {}
    cpvs = [cpv.get('code')] if cpv.get('code') else []
    cpvs += [x.get('code') if isinstance(x,dict) else x for x in procurement.get('additionalCpvCodes', [])]
    winners = []
    if pub_type == 'award':
        for vendor in decision.get('vendors') or []:
            price = vendor.get('price') or {}
            winners.append({'name': vendor.get('vendorName'), 'price':price.get('price'), 'currency':str(price.get('currency') or '').upper() or None,'vat_type':price.get('vatType'),'canton':(vendor.get('vendorAddress') or {}).get('cantonId')})
    return {'schema_version':1,'record_type':'market_award' if pub_type == 'award' else 'public_tender', 'tender_id':'simap:'+pid,'project_number':base.get('projectNumber'),'publication_id':base.get('id') or detail.get('id'),'publication_number':base.get('publicationNumber'),'publication_type':pub_type,'title':text(info.get('title') or base.get('title')),'description':text(procurement.get('orderDescription')),'buyer':text(buyer_address.get('name')),'canton':buyer_address.get('cantonId'),'publication_date':base.get('publicationDate'),'process_type':base.get('processType'),'cpv_codes':cpvs,'bkp_codes':procurement.get('bkpCodes') or [],'number_of_submissions':decision.get('numberOfSubmissions'),'award_decision_date':decision.get('awardDecisionDate'),'award_justification':text(decision.get('awardDecisionJustification')),'winners':winners,'provenance':provenance}


def _merge(path, records):
    stored = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            row = json.loads(line)
            stored[row['publication_id']] = row
    for row in records:
        stored[row['publication_id']] = row
    temp = path.with_suffix('.tmp')
    temp.write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in sorted(stored.values(),key=lambda r:r['publication_id'])),encoding='utf-8')
    temp.replace(path)


def collect_sources(urls, output_dir, *, searches=None, max_pages=2, max_awards=20):
    """Collect explicit projects plus optional (term, language) search tuples.

    Invalid source URLs fail before any network call. Search/detail failures are
    reported in errors; a failed run never reports invented or stale rows as new.
    """
    if len(urls) > 20 or not 1 <= max_pages <= 10 or not 1 <= max_awards <= 100:
        raise ValueError('Bounds: 20 URLs, 1..10 pages/search, 1..100 awards')
    ids = [project_id(url) for url in urls]
    searches = searches or []
    if len(searches) > 10 or any(lang not in {'de','fr','it','en'} or not 1 <= len(term) <= 120 for term,lang in searches):
        raise ValueError('Invalid search terms or language')
    root = Path(output_dir)
    client = Client(root/'raw'/'simap')
    records, errors, seen = [], [], set()

    def fetch(pid, publication):
        if publication in seen:
            return
        seen.add(publication)
        url = f'{BASE}/api/publications/v1/project/{str(uuid.UUID(pid))}/publication-details/{str(uuid.UUID(publication))}'
        detail, provenance = client.get(url)
        records.append(normalize(detail,provenance))

    for pid in ids:
        try:
            header, _ = client.get(f'{BASE}/api/publications/v2/project/{pid}/project-header')
            fetch(pid, header['latestPublication']['id'])
        except (OSError,ValueError,KeyError) as exc:
            errors.append({'project_id':pid,'error':str(exc)})
    award_count = sum(r['record_type']=='market_award' for r in records)
    for term,lang in searches:
        cursor = None
        for _ in range(max_pages):
            if award_count >= max_awards:
                break
            params = {'search':term,'lang':lang}
            if cursor:
                params['lastItem'] = cursor
            try:
                page,_ = client.get(BASE+'/api/publications/v2/project/project-search?'+urlencode(params))
                for project in page.get('projects',[]):
                    if award_count >= max_awards:
                        break
                    if project.get('pubType') != 'award' or not HVAC.search(text(project.get('title'))):
                        continue
                    try:
                        before = len(records)
                        fetch(project['id'],project['publicationId'])
                        award_count += len(records)-before
                    except (OSError,ValueError,KeyError) as exc:
                        errors.append({'project_id':project.get('id'),'error':str(exc)})
                next_cursor = (page.get('pagination') or {}).get('lastItem')
                if not next_cursor or next_cursor == cursor:
                    break
                cursor = next_cursor
            except (OSError,ValueError,KeyError) as exc:
                errors.append({'search':term,'error':str(exc)})
                break
    awards_path, tenders_path = root/'market_awards.jsonl', root/'public_tenders.jsonl'
    _merge(awards_path,[r for r in records if r['record_type']=='market_award'])
    _merge(tenders_path,[r for r in records if r['record_type']=='public_tender'])
    manifest = {'schema_version':1,'collected_at':datetime.now(timezone.utc).isoformat(),'market_awards_path':str(awards_path),'public_tenders_path':str(tenders_path),'counts':{'market_awards':award_count,'public_tenders':sum(r['record_type']=='public_tender' for r in records)},'errors':errors,'records':records,'attribution':ATTRIBUTION}
    (root/'collection_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',action='append',default=[])
    parser.add_argument('--output-dir',default=str(Path(__file__).resolve().parents[1]/'data'))
    parser.add_argument('--max-pages',type=int,default=2)
    parser.add_argument('--max-awards',type=int,default=20)
    parser.add_argument('--search-hvac',action='store_true')
    args = parser.parse_args()
    result = collect_sources(args.url,args.output_dir,searches=DEFAULT_SEARCHES if args.search_hvac else [],max_pages=args.max_pages,max_awards=args.max_awards)
    print(json.dumps({k:v for k,v in result.items() if k!='records'},ensure_ascii=False,indent=2))
