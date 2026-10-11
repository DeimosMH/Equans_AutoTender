import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core
from evaluation import ReviewStore


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.tenders=self.root/'tenders';self.store=ReviewStore(self.root/'reviews')
        for i in range(10):
            folder=self.tenders/f't{i}'
            calc={'project_cost':{'cost_baseline_chf':100},'recommended_bid_range':{'model':{'kind':'heuristic'}}}
            params={'commercial':{'target_margin_pct':5},'stretch_bid_optimization':{'enabled':True}}
            with patch.object(core,'_now',return_value='2024-01-01T00:00:00Z'):
                offer=core.capture_offer(folder,calc,params,{'margin':5,'waste':4,'overhead':8.5},{})
            core.confirm_offer_submission(folder,{'offer_id':offer['id'],'submitted_at':'2024-01-02T00:00:00Z'})
            core.record_outcome(folder,{'outcome':'won' if i%2 else 'lost','verified':True,
                'evidence_reference':'Synthetic award','observed_at':'2024-02-01T00:00:00Z'})

    def response(self, review):
        inputs=[json.loads(line) for line in self.store.artifact(review['id'],'evaluation_inputs.jsonl').read_text().splitlines()]
        return {'review_id':review['id'],'candidate_model_id':'synthetic-model',
            'provenance':{'source':'synthetic-test-job','verified':True,'training_cutoff':'2023-12-01T00:00:00Z','trained_project_ids':[]},
            'predictions':[{'tender_id':r['tender_id'],'input_hash':r['input_hash'],'probability':.5,
                'generated_at':'2025-01-01T00:00:00Z'} for r in inputs]}

    def test_handoff_hides_labels_and_review_survives_restart(self):
        review=self.store.prepare(self.tenders,'cloud/glm-5.3-flash')
        self.assertEqual(review['status'],'ready')
        with zipfile.ZipFile(self.store.artifact(review['id'],'handoff.zip')) as bundle:
            self.assertNotIn('reference.json',bundle.namelist())
            rows=[json.loads(line) for line in bundle.read('evaluation_inputs.jsonl').splitlines()]
            self.assertEqual(len(rows),10)
            self.assertTrue(all(set(r)=={'tender_id','input','input_hash'} for r in rows))
            self.assertEqual(json.loads(bundle.read('evaluation_request.json'))['status'],'not_submitted')
        response=self.response(review)
        result=self.store.evaluate(review['id'],self.tenders,response)
        self.assertEqual(result['status'],'evaluated');self.assertFalse(result['result']['promotion_performed'])
        self.assertTrue(result['result']['noninferior'])
        restarted=ReviewStore(self.root/'reviews')
        self.assertEqual(restarted.list()[0],result)
        self.assertEqual(restarted.evaluate(review['id'],self.tenders,response),result)
        self.assertTrue(restarted.artifact(review['id'],'result.json').exists())
        response['candidate_model_id']='different-model'
        with self.assertRaisesRegex(ValueError,'already has results'):restarted.evaluate(review['id'],self.tenders,response)

    def test_rejects_mismatched_missing_future_and_training_overlap(self):
        review=self.store.prepare(self.tenders,'model');response=self.response(review)
        invalid=[]
        body=copy.deepcopy(response);body['predictions'][0]['input_hash']='wrong';invalid.append(body)
        body=copy.deepcopy(response);body['predictions'].pop();invalid.append(body)
        body=copy.deepcopy(response);body['predictions'].append(body['predictions'][0]);invalid.append(body)
        body=copy.deepcopy(response);body['predictions'][0]['generated_at']='2999-01-01T00:00:00Z';invalid.append(body)
        body=copy.deepcopy(response);body['provenance']['trained_project_ids']=['t9'];invalid.append(body)
        body=copy.deepcopy(response);body['provenance']['training_cutoff']='2024-01-03T00:00:00Z';invalid.append(body)
        body=copy.deepcopy(response);body['predictions'][0]['probability']=1.01;invalid.append(body)
        for body in invalid:
            with self.subTest(body=body),self.assertRaises(ValueError):self.store.evaluate(review['id'],self.tenders,body)
        self.assertNotIn('result',self.store.get(review['id']))

    def test_changed_outcome_blocks_old_handoff(self):
        review=self.store.prepare(self.tenders,'model');response=self.response(review)
        core.record_outcome(self.tenders/'t0',{'outcome':'won','verified':True,'evidence_reference':'Corrected award',
            'observed_at':'2024-02-01T00:00:00Z','expected_revision':1})
        with self.assertRaisesRegex(ValueError,'evidence changed'):self.store.evaluate(review['id'],self.tenders,response)

    def test_import_can_resume_after_interrupted_result_write(self):
        review=self.store.prepare(self.tenders,'model');response=self.response(review)
        core._atomic(self.store.root/review['id']/'response.json',response)
        result=ReviewStore(self.store.root).evaluate(review['id'],self.tenders,response)
        self.assertEqual(result['status'],'evaluated')
        self.assertTrue(self.store.artifact(review['id'],'result.json').exists())

    def test_empty_bundle_and_tampering(self):
        review=self.store.prepare(self.root/'empty','model')
        self.assertEqual(review['status'],'blocked')
        self.assertTrue(self.store.artifact(review['id'],'handoff.zip').exists())
        with self.assertRaises(ValueError):self.store.artifact(review['id'],'reference.json')
        with self.assertRaises(ValueError):self.store.get('../escape')
        (self.store.root/review['id']/'evaluation_inputs.jsonl').write_text('tampered')
        with self.assertRaisesRegex(ValueError,'integrity'):self.store.artifact(review['id'],'handoff.zip')


if __name__=='__main__':unittest.main()
