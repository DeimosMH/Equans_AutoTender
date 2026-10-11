import importlib.util
import json
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from http.server import ThreadingHTTPServer

SRC = Path(__file__).resolve().parents[2]


class FeedbackAPITests(unittest.TestCase):
    def test_submission_outcome_report_and_training_feedback(self):
        spec=importlib.util.spec_from_file_location('feedback_api_test',SRC/'web_ui/server.py')
        app=importlib.util.module_from_spec(spec); spec.loader.exec_module(app)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            app.TENDERS=root/'tenders'; app.UPLOADS=root/'uploads'; app.UI_SETTINGS=root/'settings.json'
            app.PREPARATION_JOBS=app.JobStore(root/'jobs')
            app.FEEDBACK_REVIEWS=app.ReviewStore(root/'reviews')
            http=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
            threading.Thread(target=http.serve_forever,daemon=True).start()
            base=f'http://127.0.0.1:{http.server_port}'
            def request(route, payload=None, raw=False):
                req=urllib.request.Request(base+route,data=None if payload is None else json.dumps(payload).encode(),
                                           headers={'Content-Type':'application/json'})
                try:
                    with urllib.request.urlopen(req) as response:
                        content=response.read()
                        return response.status, content if raw else json.loads(content)
                except urllib.error.HTTPError as error:
                    return error.code,json.loads(error.read())
            try:
                _,meta=request('/api/tenders',{'name':'Synthetic workflow regression'})
                tid=meta['id']; folder=app.TENDERS/tid
                shutil.copy(SRC/'_2_Calculator/input/example_lv_positions.csv',folder/'positions.csv')
                self.assertEqual(request(f'/api/tenders/{tid}/recalc',{})[0],200)
                status, result=request(f'/api/tenders/{tid}/submission',{
                    'submitted_at':(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),'margin_pct':5.5})
                self.assertEqual(status,200,result)
                frozen=json.loads((folder/'feedback/submission.json').read_text())
                saved=json.loads((folder/'calc.json').read_text()); saved['project_cost']['cost_baseline_chf']=1
                (folder/'calc.json').write_text(json.dumps(saved))
                self.assertEqual(request(f'/api/tenders/{tid}/outcome',{
                    'outcome':'lost','verified':True,'observed_at':datetime.now(timezone.utc).isoformat(),
                    'evidence_reference':'Synthetic test award letter','reason_codes':['price'],
                    'reasons_confirmed':True,'award_price_chf':500000,'award_price_comparable':True})[0],200)
                _,overview=request(f'/api/tenders/{tid}/feedback')
                self.assertEqual(overview['submission']['hash'],frozen['hash'])
                self.assertTrue(overview['analysis']['training_eligible'])
                uploads=list((app.UPLOADS/'lora_data').glob('win_ratio_feedback_*.jsonl'))
                self.assertEqual(len(uploads),1)
                record=json.loads(uploads[0].read_text())
                self.assertEqual(record['input']['cost_amount_chf'],frozen['cost_baseline_chf'])
                self.assertNotIn('award_price_chf',record['input'])
                for fmt in ('md','html','pdf'):
                    status,report=request(f'/api/tenders/{tid}/postmortem?format={fmt}',raw=True)
                    self.assertEqual(status,200)
                    self.assertTrue(report)
                    if fmt=='pdf': self.assertTrue(report.startswith(b'%PDF'))
                self.assertEqual(request('/api/feedback/monitoring')[0],200)
                status,review=request('/api/feedback/evaluate',{'records':[]})
                self.assertEqual(status,200)
                self.assertEqual(review['status'],'blocked')
                self.assertFalse(review['promotion_performed'])
                self.assertTrue((app.FEEDBACK_REVIEWS.root/review['review_id']/'result.json').exists())
                # Revoking verification removes prior training supervision immediately.
                self.assertEqual(request(f'/api/tenders/{tid}/outcome',{
                    'outcome':'lost','verified':False,'observed_at':datetime.now(timezone.utc).isoformat()})[0],200)
                self.assertFalse(uploads[0].exists())
                self.assertEqual(request(f'/api/tenders/{tid}/productivity-feedback',{
                    'verified':True,'measurement_reference':'Synthetic time record','input':{'work_type':'duct'},
                    'target':{'site_efficiency':.9}})[0],200)
                self.assertEqual(len(list((app.UPLOADS/'lora_data').glob('productivity_factors_feedback_*.jsonl'))),1)
                self.assertEqual(request(f'/api/tenders/{tid}/outcome',{'outcome':'invalid'})[0],400)
                self.assertEqual(request('/api/tenders/bad/submission',{})[0],400)
            finally:
                http.shutdown(); http.server_close()
