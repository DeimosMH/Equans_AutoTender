"""Regression coverage for the review workspace, using isolated data and HTTP."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import zipfile
import shutil
from datetime import datetime, timezone, timedelta
from http.server import ThreadingHTTPServer

BASE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('workspace_app', BASE/'server.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)
from jobs import JobStore
from collect.simap import _merge


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        app.UI_SETTINGS = self.root/'settings.json'
        app.UPLOADS = self.root/'uploads'
        app.TENDERS = self.root/'tenders'
        app.FEEDBACK_REVIEWS = app.ReviewStore(self.root/'reviews')
        self.corpus = self.root/'corpus'
        self.corpus.mkdir()
        rows = []
        for i in range(5):
            raw = json.dumps({'title':f'Ventilation {i}'}).encode()
            path = self.corpus/f'{i}.json'; path.write_bytes(raw)
            rows.append({'publication_id':str(i), 'tender_id':f'project-{i}',
                'record_type':'market_award','title':f'Ventilation {i}',
                'provenance':{'raw_path':str(path), 'sha256':hashlib.sha256(raw).hexdigest(),
                              'source_url':'https://www.simap.ch/de/project-detail/example'}})
        _merge(self.corpus/'market_awards.jsonl', rows)
        app.PREPARATION_JOBS = JobStore(self.root/'jobs', self.corpus)
        self.http = ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever,daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.http.server_port}'

    def tearDown(self):
        self.http.shutdown(); self.http.server_close()
        self.temp.cleanup()

    def request(self, path, data=None):
        req = urllib.request.Request(self.url+path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req) as res:
            raw = res.read()
            return json.loads(raw) if 'application/json' in res.headers['Content-Type'] else raw

    def wait(self, job):
        for _ in range(300):
            job = self.request('/api/settings/jobs/'+job['id'])
            if job['status'] not in ('queued','collecting','preparing'):
                return job
            time.sleep(.01)
        self.fail('job did not complete')

    def test_download_freezes_unsaved_values_prices_and_chosen_submission(self):
        meta=self.request('/api/tenders',{'name':'Frozen offer regression'})
        tid=meta['id'];route='/api/tenders/'+tid;folder=app.TENDERS/tid
        shutil.copy(BASE.parent/'_2_Calculator/input/example_lv_positions.csv',folder/'positions.csv')
        self.request(route+'/recalc',{})
        request={'edits':{'LV0001':{'quantity':7}},'margin':10,'overhead':12,'waste':6}
        original=(folder/'calc.json').read_bytes()
        for invalid in (-1, None, 'NaN', True):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request(route+'/offers',dict(request,edits={'LV0001':{'quantity':invalid}}))
            self.assertEqual(error.exception.code,400)
            self.assertEqual((folder/'calc.json').read_bytes(),original)
        offer=self.request(route+'/offers',request)
        frozen=app.feedback_core.read_offer(folder,offer['id'])
        self.assertEqual(frozen['calc']['position_results'][0]['quantity'],7)
        self.assertEqual(frozen['params']['commercial']['overhead_pct'],12)
        self.assertEqual(frozen['params']['commercial']['target_margin_pct'],app.calc_common.load_params()['commercial']['target_margin_pct'])
        self.assertLess(frozen['predicted_win_probability'],.55)
        self.assertEqual(self.request(route+'/offers',request)['id'],offer['id'])
        page=self.request(route+f"/pdf?offer={offer['id']}&format=html&hide=0&hide_notes=0")
        self.assertIn(f"{offer['bid_amount_chf']:,.2f}".encode(),page)
        self.assertIn(b'10%',page)
        self.request(route+'/values',{'edits':{'LV0001':{'quantity':99}}})
        self.assertEqual(page,self.request(route+f"/pdf?offer={offer['id']}&format=html&margin=1&hide=0&hide_notes=0"))
        for fmt in ('pdf','docx'):
            self.assertTrue(self.request(route+f"/pdf?offer={offer['id']}&format={fmt}"))
        submitted=datetime.now(timezone.utc).isoformat()
        self.request(route+'/finalise',{'margin':3})
        saved=self.request(route+'/submission',{'offer_id':offer['id'],'submitted_at':submitted,'bid_amount_chf':offer['bid_amount_chf']})['result']
        self.assertTrue(saved['training_eligible']);self.assertEqual(saved['offer_hash'],frozen['hash'])
        self.request(route+'/outcome',{'outcome':'won','verified':True,'evidence_reference':'Synthetic award',
            'observed_at':datetime.now(timezone.utc).isoformat()})
        self.assertTrue((app.UPLOADS/'lora_data'/f'win_ratio_feedback_{tid}.jsonl').exists())
        review=self.request('/api/feedback/reviews',{})
        self.assertEqual(review['samples'],1);self.assertEqual(review['status'],'blocked')
        self.assertEqual(self.request('/api/feedback/reviews')['reviews'][0]['id'],review['id'])
        bundle=self.request(f"/api/feedback/reviews/{review['id']}/artifacts/handoff.zip")
        with zipfile.ZipFile(io.BytesIO(bundle)) as z:self.assertNotIn('reference.json',z.namelist())
        with urllib.request.urlopen(urllib.request.Request(self.url+route,method='DELETE')) as res:self.assertEqual(res.status,200)
        self.assertFalse((app.UPLOADS/'lora_data'/f'win_ratio_feedback_{tid}.jsonl').exists())

    def test_model_roundtrip_bundle_preview_and_no_activation(self):
        model = 'cloud/glm-5.3-flash'
        saved = self.request('/api/settings',{'base_model':model})['settings']
        self.assertEqual(saved['base_model'],model)
        self.assertTrue(all(t['selected'] is None for t in saved['tasks'].values()))
        job = self.wait(self.request('/api/training/prepare',{
            'task':'market_extraction','base_model':model,'include_existing':True})['job'])
        self.assertEqual(job['status'],'ready_for_training')
        self.assertEqual(job['manifest']['accepted_count'],5)
        preview = self.request('/api/training/'+job['id']+'/preview?split=validation')
        self.assertEqual(len(preview['examples']),1)
        self.assertIn('sha256', preview['evidence'][0]['evidence']['provenance'])
        raw = self.request('/api/settings/jobs/'+job['id']+'/artifacts/dataset_bundle.zip')
        with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
            manifest = json.loads(bundle.read('manifest.json'))
            for name,digest in manifest['hashes'].items():
                self.assertEqual(hashlib.sha256(bundle.read(name)).hexdigest(),digest)
            request = json.loads(bundle.read('training_request.json'))
            self.assertEqual(request['base_model'],model)
            self.assertEqual(request['submission_status'],'not_submitted')
            self.assertFalse(request['evaluation']['upload_test_for_training'])
        with self.assertRaises(urllib.error.HTTPError) as invalid:
            self.request('/api/training/'+job['id']+'/preview?split=other')
        self.assertEqual(invalid.exception.code,400)

    def test_bad_model_or_source_rejected_before_start(self):
        for path, payload in [('/api/training/collect',{'urls':['http://localhost/secret']}),
                ('/api/training/prepare',{'task':'market_extraction','base_model':'bad model'})]:
            with self.assertRaises(urllib.error.HTTPError) as invalid:
                self.request(path,payload)
            self.assertEqual(invalid.exception.code,400)
        self.assertEqual(app.PREPARATION_JOBS.list(),[])

    def test_uploaded_data_validated_and_visible_in_inventory(self):
        row = {'project_id':'site-1','measurement_reference':'approved-timesheet',
               'input':{'site_type':'school'},'target':{'site_efficiency':.9}}
        req = urllib.request.Request(self.url+'/api/settings/upload-data?task=productivity_factors&name=measured.jsonl',
            data=(json.dumps(row)+'\n').encode(), method='POST')
        with urllib.request.urlopen(req) as res:
            self.assertEqual(json.load(res)['records'],1)
        overview = self.request('/api/training')
        self.assertEqual(overview['uploads'][0]['records'],1)
        job = self.wait(self.request('/api/training/prepare',{
            'task':'productivity_factors','base_model':'glm-5.3-flash','include_existing':True})['job'])
        self.assertEqual(job['status'],'blocked')
        self.assertEqual(job['public_record_count'],0)
        self.assertEqual(job['manifest']['counts']['train'],1)

    def test_collection_reusable_without_implicit_search(self):
        url = 'https://www.simap.ch/de/project-detail/d849c22b-3fc4-48d8-94c9-c45457544ab1'
        def collect(urls, directory, **options):
            self.assertEqual(options['searches'],[])
            directory.mkdir(parents=True)
            raw = b'{"title":"New source"}'
            source = directory/'raw.json'; source.write_bytes(raw)
            row = {'publication_id':'new','tender_id':'new-project','record_type':'public_tender',
                'title':'New source','provenance':{'raw_path':str(source),'sha256':hashlib.sha256(raw).hexdigest()}}
            _merge(directory/'public_tenders.jsonl',[row])
            return {'records':[row],'errors':[]}
        with patch('collect.simap.collect_sources',side_effect=collect):
            job = self.wait(self.request('/api/training/collect',{'urls':[url]})['job'])
            self.assertEqual(job['status'],'collected')
        self.assertEqual(len(self.request('/api/training')['sources']),6)
        prepared = self.wait(self.request('/api/training/prepare',{
            'task':'market_extraction','base_model':'glm-5.3-flash','include_existing':True})['job'])
        self.assertEqual(prepared['manifest']['accepted_count'],6)

    def test_provider_status_does_not_expose_credentials(self):
        with patch.dict('os.environ',{'AUTOTENDER_TRAINING_API_KEY':'secret-test-value'}):
            overview = self.request('/api/training')
        self.assertTrue(overview['provider']['credential_configured'])
        self.assertEqual(overview['provider']['status'],'awaiting_contract')
        self.assertNotIn('secret-test-value',json.dumps(overview))

    def calculated_tender(self):
        meta = self.request('/api/tenders', {'name':'Completion workflow'})
        folder = app.TENDERS/meta['id']
        shutil.copy(BASE.parent/'_2_Calculator/input/example_lv_positions.csv',folder/'positions.csv')
        self.request(f"/api/tenders/{meta['id']}/recalc",{})
        return meta['id']

    def test_finalisation_saves_edits_and_commercial_values_and_can_reopen(self):
        tid = self.calculated_tender()
        route = '/api/tenders/'+tid
        payload = {'edits':{'LV0001':{'quantity':9}},'margin':7.5,'overhead':12,'waste':6}
        for invalid_margin in (None, True, 'invalid', float('inf'), -1, 100):
            with self.subTest(margin=invalid_margin), self.assertRaises(urllib.error.HTTPError) as invalid:
                self.request(route+'/finalise',dict(payload,margin=invalid_margin))
            self.assertEqual(invalid.exception.code,400)
        self.assertEqual(self.request(route)['calc']['position_results'][0]['quantity'],5)
        result = self.request(route+'/finalise',payload)['meta']
        self.assertEqual(result['lifecycle'],'finalised')
        self.assertEqual(result['final_commercial'],{'margin':7.5,'overhead':12,'waste':6})
        self.assertEqual(self.request(route)['calc']['position_results'][0]['quantity'],9)
        self.assertEqual(self.request(route+'/finalise',payload)['meta'],result)
        with self.assertRaises(urllib.error.HTTPError) as invalid:
            self.request(route+'/values',{'edits':{'LV0001':{'quantity':10}}})
        self.assertEqual(invalid.exception.code,400)
        self.assertEqual(self.request(route+'/reopen',{})['meta']['lifecycle'],'active')
        self.request(route+'/values',{'edits':{'LV0001':{'quantity':10}}})
        self.assertEqual(self.request(route)['calc']['position_results'][0]['quantity'],10)

    def test_completion_documents_are_persistent_downloads(self):
        tid = self.calculated_tender()
        route = '/api/tenders/'+tid
        content = b'%PDF-1.4\nsynthetic test evidence'
        def upload(name='letter.pdf'):
            with urllib.request.urlopen(urllib.request.Request(self.url+route+'/completion-documents?name='+name,
                    data=content,method='POST')) as response:
                return json.load(response)
        with self.assertRaises(urllib.error.HTTPError):
            upload()
        self.request(route+'/finalise',{})
        first,second = upload()['document'],upload()['document']
        self.assertNotEqual(first['id'],second['id'])
        self.assertEqual(first['sha256'],hashlib.sha256(content).hexdigest())
        self.assertEqual(len(self.request(route+'/completion-documents')['documents']),2)
        self.assertEqual(self.request(route+'/completion-documents/'+first['id']),content)
        with self.assertRaises(urllib.error.HTTPError):
            upload('script.html')
        self.request(route+'/reopen',{})
        self.assertEqual(len(self.request(route+'/completion-documents')['documents']),2)

    def test_completion_capture_is_retrospective_and_preserves_prior_forecasts(self):
        now = datetime.now(timezone.utc)
        for prospective in (False,True):
            with self.subTest(prospective=prospective):
                tid = self.calculated_tender()
                route = '/api/tenders/'+tid
                if prospective:
                    original = self.request(route+'/submission',{'submitted_at':(now-timedelta(seconds=2)).isoformat()})['result']
                self.request(route+'/finalise',{'margin':7.5,'overhead':12,'waste':6})
                snap = self.request(route+'/submission',{'submitted_at':(now-timedelta(seconds=2)).isoformat(),
                    'retrospective':False,'bid_amount_chf':650000})['result']
                self.assertEqual(snap['training_eligible'],prospective)
                if prospective:
                    self.assertEqual(snap,original)
                else:
                    self.assertEqual(snap['params']['commercial']['overhead_pct'],12)
                    self.assertEqual(snap['params']['allowances']['material_waste_pct'],6)
                outcome = self.request(route+'/outcome',{'outcome':'won','observed_at':datetime.now(timezone.utc).isoformat(),
                    'verified':True,'evidence_reference':'Uploaded award letter'})['feedback']
                self.assertEqual(outcome['analysis']['training_eligible'],prospective)
                self.assertEqual(self.request(route)['meta']['lifecycle'],'finalised')


if __name__ == '__main__':
    unittest.main()
