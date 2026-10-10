import importlib.util
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

PRED = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PRED))
from dataset import prepare_dataset, read_upload, validate_record
from jobs import JobStore


def bid(project='p1', outcome='won'):
    return {'project_id':project,'source_kind':'own_bid','bid_submitted_at':'2024-01-01',
            'outcome_observed_at':'2024-02-01','input':{'bid_amount_chf':1234,'margin_pct':8},
            'target':{'outcome':outcome}}

class DatasetTests(unittest.TestCase):
    def test_rejects_public_awards_and_post_outcome_inputs(self):
        r = bid(); r['source_kind'] = 'public_award'
        with self.assertRaisesRegex(ValueError,'own_bid'): validate_record(r,'win_ratio')
        r = bid(); r['input']['award_justification'] = 'Lowest price'
        with self.assertRaisesRegex(ValueError,'post-award'): validate_record(r,'win_ratio')
        r = bid(); r['target'] = {'probability':0.7}
        with self.assertRaisesRegex(ValueError,'probabilities'): validate_record(r,'win_ratio')

    def test_project_splits_deterministic_and_rejections_auditable(self):
        records = [bid('p'+str(i), 'won' if i%2 else 'lost') for i in range(30)]
        records.append(bid('p1','lost'))
        records.append({'project_id':'bad'})
        with tempfile.TemporaryDirectory() as temp:
            first = prepare_dataset(records,'win_ratio',Path(temp)/'a','base')
            second = prepare_dataset(list(reversed(records)),'win_ratio',Path(temp)/'b','base')
            self.assertEqual(first['projects'],second['projects'])
            self.assertEqual(first['hashes'],second['hashes'])
            self.assertEqual(first['rejected_count'],1)
            self.assertEqual(first['status'],'ready_for_training')
            self.assertEqual(set(first['projects'].values()),{'train','validation','test'})
            for line in (Path(temp)/'a'/'train.jsonl').read_text().splitlines():
                self.assertEqual([m['role'] for m in json.loads(line)['messages']],['system','user','assistant'])

    def test_upload_is_atomic_validation(self):
        payload = (json.dumps(bid())+'\n{"project_id":"invalid"}\n').encode()
        with self.assertRaisesRegex(ValueError,'line 2'): read_upload(payload,'win_ratio')

    def test_jobs_persist_blocked_and_never_promote_adapter(self):
        with tempfile.TemporaryDirectory() as temp:
            store=JobStore(Path(temp)/'jobs')
            uploads=Path(temp)/'uploads'; uploads.mkdir()
            (uploads/'win_ratio_example.jsonl').write_text(json.dumps(bid())+'\n')
            job=store.start('win_ratio','base','',uploads)
            for _ in range(100):
                result=store.get(job['id'])
                if result['status'] not in ('queued','collecting','preparing'): break
                time.sleep(.01)
            self.assertEqual(result['status'],'blocked')
            self.assertNotIn('adapter_id',result)
            bundle=json.loads(store.artifact(job['id'],'training_request.json').read_text())
            self.assertEqual(bundle['submission_status'],'not_submitted')
            self.assertEqual(JobStore(Path(temp)/'jobs').get(job['id']),result)
            with self.assertRaises(ValueError): store.artifact(job['id'],'../../secret')

    def test_server_restart_marks_interrupted_job_failed(self):
        with tempfile.TemporaryDirectory() as temp:
            store=JobStore(temp)
            job={'id':'j'+'0'*32,'status':'collecting','created_at':'now'}
            store._save(job)
            self.assertEqual(JobStore(temp).get(job['id'])['status'],'failed')


class ExistingSourcesTests(unittest.TestCase):
    def test_cached_market_data_is_first_class_ready_dataset(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); corpus=root/'corpus'; corpus.mkdir()
            rows=[]
            for i in range(5):
                raw=json.dumps({'title':f'Ventilation {i}'}).encode()
                path=corpus/f'{i}.json'; path.write_bytes(raw)
                rows.append({'publication_id':str(i),'tender_id':f'p{i}','record_type':'market_award',
                    'title':f'Ventilation {i}', 'provenance':{'raw_path':str(path),'sha256':hashlib.sha256(raw).hexdigest()}})
            (corpus/'market_awards.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            store=JobStore(root/'jobs',corpus_dir=corpus)
            job=store.start('market_extraction','base','',root/'uploads',include_existing=True)
            for _ in range(100):
                result=store.get(job['id'])
                if result['status'] not in ('queued','collecting','preparing'): break
                time.sleep(.01)
            self.assertEqual(result['status'],'ready_for_training')
            self.assertEqual(result['public_record_count'],5)
            self.assertEqual(sum(result['manifest']['counts'].values()),5)
            win=store.start('win_ratio','base','',root/'uploads',include_existing=True)
            for _ in range(100):
                result=store.get(win['id'])
                if result['status'] not in ('queued','collecting','preparing'): break
                time.sleep(.01)
            self.assertEqual(result['status'],'blocked')
            self.assertEqual(sum(result['manifest']['counts'].values()),0)

    def test_sponsor_seed_is_one_project_matching_supervision(self):
        from prepare_sponsor import sponsor_examples
        examples=sponsor_examples(PRED.parents[1]/'materials')
        self.assertEqual(len(examples),22)
        self.assertEqual(len({r['project_id'] for r in examples}),1)
        self.assertTrue(all('outcome' not in r['target'] for r in examples))
        with tempfile.TemporaryDirectory() as temp:
            manifest=prepare_dataset(examples,'input_processing',temp,'base')
            self.assertEqual(manifest['status'],'blocked')

if __name__ == '__main__': unittest.main()
