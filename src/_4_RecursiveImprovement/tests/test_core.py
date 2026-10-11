import concurrent.futures
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('recursive_core', Path(__file__).resolve().parents[1] / 'core.py')
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / 't_example'
        self.uploads = Path(self.tmp.name) / 'uploads'
        self.calc = {'project_cost': {'cost_baseline_chf': 100000},
                     'position_results': [{'status':'supplier_quote_required'}, {'status':'calculated'}],
                     'recommended_bid_range': {'model': {'kind':'heuristic'}, 'curve': []}}
        self.params = {'commercial': {'target_margin_pct': 5}}

    def capture(self, **payload):
        return core.capture_submission(self.folder, self.calc, self.params, payload)

    def outcome(self, **payload):
        defaults = {'outcome':'lost', 'observed_at':(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat(),
                    'verified':True, 'evidence_reference':'Confirmed award letter 10/10'}
        defaults.update(payload)
        return core.record_outcome(self.folder, defaults)

    def test_immutable_snapshot_and_integrity(self):
        initial = self.capture(bid_amount_chf=120000)
        self.calc['project_cost']['cost_baseline_chf'] = 200000
        self.assertEqual(self.capture(bid_amount_chf=300000), initial)
        self.assertEqual(core.overview(self.folder)['submission']['cost_baseline_chf'], 100000)
        initial['cost_baseline_chf'] = 1
        (self.folder/'feedback/submission.json').write_text(json.dumps(initial))
        with self.assertRaisesRegex(ValueError, 'integrity'):
            core.analyze(self.folder)

    def test_capture_after_outcome_blocked(self):
        self.capture()
        self.outcome()
        with self.assertRaisesRegex(ValueError, 'after an outcome'):
            self.capture()

    def test_downloads_deduplicate_and_confirmation_keeps_original_evidence(self):
        commercial={'margin':5,'overhead':8.5,'waste':4}
        with patch.object(core,'_now',return_value='2024-01-01T00:00:00Z'):
            offer=core.capture_offer(self.folder,self.calc,self.params,commercial,{'LV1':'Original'})
        repeated=core.capture_offer(self.folder,self.calc,self.params,commercial,{'LV1':'Original'})
        self.assertEqual(repeated,offer)
        self.assertIsNone(core.overview(self.folder)['submission'])
        self.calc['project_cost']['cost_baseline_chf']=200000
        later=core.capture_offer(self.folder,self.calc,self.params,commercial,{},completed=True)
        self.assertNotEqual(offer['id'],later['id'])
        for payload in ({'submitted_at':'2023-12-31T00:00:00Z'},
                        {'submitted_at':'2024-01-02T00:00:00Z','bid_amount_chf':1}):
            with self.assertRaises(ValueError):core.confirm_offer_submission(self.folder,dict(payload,offer_id=offer['id']))
        snap=core.confirm_offer_submission(self.folder,{'offer_id':offer['id'],'submitted_at':'2024-01-02T00:00:00Z'})
        self.assertEqual(snap['cost_baseline_chf'],100000)
        self.assertEqual(snap['captured_at'],offer['captured_at'])
        self.assertTrue(snap['training_eligible'])
        self.outcome()
        self.assertEqual(core.export_feedback(self.folder,self.uploads)['status'],'exported')

    def test_download_after_completion_cannot_become_training_evidence(self):
        with patch.object(core,'_now',return_value='2024-01-01T00:00:00Z'):
            offer=core.capture_offer(self.folder,self.calc,self.params,{'margin':5}, {},completed=True)
        snap=core.confirm_offer_submission(self.folder,{'offer_id':offer['id'],'submitted_at':'2024-01-02T00:00:00Z'})
        self.assertFalse(snap['training_eligible'])
        self.outcome()
        self.assertEqual(core.export_feedback(self.folder,self.uploads)['status'],'withheld')
        path=self.folder/'feedback/offers'/f"{offer['id']}.json"
        offer['bid_amount_chf']=1;path.write_text(json.dumps(offer))
        with self.assertRaisesRegex(ValueError,'integrity'):core.read_offer(self.folder,offer['id'])

    def test_chronology_and_verified_evidence(self):
        snap = self.capture()
        for payload in [{'observed_at':snap['submitted_at']}, {'evidence_reference':''}, {'observed_at':'2026-10-10T12:00:00'}, {'verified':'true'}]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.outcome(**payload)

    def test_retrospective_excluded(self):
        snap = self.capture(submitted_at=(datetime.now(timezone.utc)-timedelta(days=30)).isoformat())
        self.assertFalse(snap['training_eligible'])
        self.outcome()
        self.assertEqual(core.export_feedback(self.folder,self.uploads)['status'], 'withheld')
        self.assertFalse(list(self.uploads.glob('*.jsonl')))

    def test_export_uses_only_frozen_prebid_and_replaces_revisions(self):
        self.capture(prebid_context={'sector':'HVAC'})
        first = self.outcome(reason_codes=['price'], reasons_confirmed=True,
                             narrative='Our price higher.', award_price_chf=90000)
        exported = core.export_feedback(self.folder,self.uploads)
        path = Path(exported['path'])
        record = json.loads(path.read_text())
        core.dataset.validate_record(record, 'win_ratio')
        self.assertEqual(record['input']['cost_amount_chf'],100000)
        self.assertNotIn('award_price_chf',record['input'])
        self.calc['project_cost']['cost_baseline_chf'] = 1
        second = self.outcome(outcome='won', expected_revision=first['revision'])
        self.assertFalse(path.exists())
        core.export_feedback(self.folder,self.uploads)
        self.assertEqual(len(path.read_text().splitlines()), 1)
        record = json.loads(path.read_text())
        self.assertEqual(record['target'], {'outcome':'won'})
        self.assertEqual(record['outcome_revision'],second['revision'])
        self.assertEqual(record['input']['cost_amount_chf'],100000)
        self.outcome(verified=False)
        self.assertFalse(path.exists())
        self.assertEqual(core.export_feedback(self.folder,self.uploads)['status'],'withheld')

    def test_no_causal_price_inference_and_report_escaping(self):
        self.capture(bid_amount_chf=120000)
        self.outcome(narrative='<script>alert(1)</script>', reason_codes=['price'],
                     award_price_chf=90000, competitors=[{'name':'<b>Other</b>', 'price_chf':100000, 'comparable':True},
                     {'name':'EUR offer', 'price_chf':50000, 'currency':'EUR', 'comparable':True}])
        result=core.analyze(self.folder)
        self.assertEqual(len(result['comparisons']),1)
        self.assertEqual(result['comparisons'][0]['our_price_difference_pct'],20)
        self.assertEqual(result['confirmed_reason_codes'],[])
        self.assertEqual(result['missing_quote_share'],.5)
        report=(self.folder/'feedback/reports/postmortem.html').read_text()
        self.assertNotIn('<script>',report)
        self.assertIn('&lt;script&gt;',report)
        self.assertIn('No causal', report)

    def test_revision_conflicts_and_idempotency(self):
        self.capture()
        initial=self.outcome()
        repeated=core.record_outcome(self.folder,initial)
        self.assertEqual(initial, repeated)
        self.assertEqual(len(list((self.folder/'feedback/audit').glob('*.json'))),2)
        with self.assertRaisesRegex(ValueError,'revision changed'):
            self.outcome(outcome='won',expected_revision=0)

    def test_parallel_capture_creates_one_snapshot(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            results=list(executor.map(lambda _:self.capture(),range(8)))
        self.assertTrue(all(r['hash']==results[0]['hash'] for r in results))
        self.assertEqual(len(list((self.folder/'feedback/audit').glob('*.json'))),1)

    def test_public_awards_never_create_own_outcome(self):
        manifest={'counts':{'market_awards':1},'errors':[], 'records':[{'winner':'Our Company'}]}
        url='https://www.simap.ch/de/project-detail/d849c22b-3fc4-48d8-94c9-c45457544ab1'
        with patch.object(core.simap,'collect_sources',return_value=manifest):
            result=core.gather_evidence(self.folder,[url])
        self.assertFalse(result['participation_inferred'])
        self.assertIsNone(core.overview(self.folder)['outcome'])
        with patch.object(core.simap,'collect_sources') as collect:
            with self.assertRaises(ValueError):
                core.gather_evidence(self.folder,['http://127.0.0.1:8080/secret'])
            collect.assert_not_called()

    def test_custom_bid_freezes_actual_margin_and_probability(self):
        self.params['stretch_bid_optimization'] = {'enabled':True, 'reference_win_probability':.55,
            'price_sensitivity_probability_points_per_1pct_price':.05,
            'minimum_probability':.05,'maximum_probability':.95}
        snap=self.capture(bid_amount_chf=110000,margin_pct=5)
        self.assertAlmostEqual(snap['margin_pct'],100*(1-100000/110000))
        self.assertEqual(snap['selected_margin_pct'],5)
        self.assertAlmostEqual(snap['predicted_win_probability'],.325)

    def test_outcome_tampering_blocked(self):
        self.capture()
        self.outcome()
        path=self.folder/'feedback/outcome.json'
        value=json.loads(path.read_text())
        value['outcome']='won'
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'Outcome integrity'):
            core.export_feedback(self.folder,self.uploads)

    def test_postaward_context_blocked(self):
        with self.assertRaisesRegex(ValueError,'post-award'):
            self.capture(prebid_context={'award_price_chf':123})


if __name__=='__main__':
    unittest.main()
