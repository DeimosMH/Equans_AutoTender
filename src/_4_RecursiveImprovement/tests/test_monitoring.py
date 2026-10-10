import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from monitoring import PageHinkley, evaluate_candidate, monitor_tenders


def candidate(index, champion=.5, challenger=.5):
    return {'tender_id':'t'+str(index),'submitted_at':'2024-01-01T12:00:00Z',
            'observed_at':'2024-02-01T12:00:00Z','outcome':'won' if index%2 else 'lost',
            'outcome_verified':True,'evidence_reference':'award:'+str(index),
            'champion_probability':champion,'candidate_probability':challenger,
            'prediction_provenance':{'source':'external_endpoint','verified':True,'model_id':'candidate-v1',
                'generated_at':'2024-01-01T11:00:00Z','evaluation_mode':'prospective'}}

class MonitoringTests(unittest.TestCase):
    def test_reference_recurrence_and_drift(self):
        detector=PageHinkley()
        count, mean, cumulative=0,0.,0.
        for value in [0.]*40+[1.]*40:
            count+=1; mean+=(value-mean)/count
            cumulative=max(0,.9999*cumulative+value-mean-.005)
            detector.update(value)
            self.assertAlmostEqual(detector.cumulative,cumulative)
            self.assertEqual(detector.alert,count>=10 and cumulative>8)
        self.assertTrue(detector.alert)
        constant=PageHinkley()
        for _ in range(100): self.assertFalse(constant.update(.2))

    def test_signed_errors_and_immutable_forecast_interpolation(self):
        with tempfile.TemporaryDirectory() as temp:
            for number,outcome in enumerate(('lost','won')):
                folder=Path(temp)/('t'+str(number))/'feedback'; folder.mkdir(parents=True)
                submission={'captured_at':'2024-01-01','training_eligible':True,'submitted_at':'2024-01-01','bid_amount_chf':120,'margin_pct':5,
                    'prediction':{'model':{'kind':'heuristic'},'curve':[
                        {'margin_pct':0,'p_win':{'mid':.8}},{'margin_pct':10,'p_win':{'mid':.4}}]}}
                record={'observed_at':'2024-02-0'+str(2-number),'outcome':outcome,
                    'verified':True,'evidence_reference':'award','competitors':[
                        {'name':'Example AG','price_chf':100,'currency':'CHF','comparable':True}]}
                submission['hash']=hashlib.sha256(json.dumps(submission,sort_keys=True,ensure_ascii=False,separators=(',', ':'),allow_nan=False).encode()).hexdigest()
                record['submission_hash']=submission['hash']
                (folder/'submission.json').write_text(json.dumps(submission))
                (folder/'outcome.json').write_text(json.dumps(record))
            result=monitor_tenders(temp)
            self.assertEqual(result['prediction_count'],2)
            self.assertEqual(result['predictions'][0]['outcome'],'won')
            self.assertAlmostEqual(result['predictions'][0]['error'],-.4)
            self.assertAlmostEqual(result['predictions'][1]['error'],.6)
            self.assertAlmostEqual(result['brier_score'],.26)
            self.assertAlmostEqual(result['calibration_bias'],.1)
            self.assertAlmostEqual(result['competitors']['Example AG']['median_delta_pct'],20)
            self.assertFalse(result['automatic_model_changes'])

    def test_monitor_rejects_mutated_or_unverified_snapshots(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'t1'/'feedback';folder.mkdir(parents=True)
            submission={'captured_at':'2024-01-01','submitted_at':'2024-01-01','training_eligible':True,
                        'predicted_win_probability':.7}
            submission['hash']=hashlib.sha256(json.dumps(submission,sort_keys=True,ensure_ascii=False,separators=(',', ':'),allow_nan=False).encode()).hexdigest()
            outcome={'observed_at':'2024-02-01','outcome':'lost','verified':True,
                     'evidence_reference':'award','submission_hash':submission['hash']}
            (folder/'outcome.json').write_text(json.dumps(outcome))
            submission['predicted_win_probability']=.4
            (folder/'submission.json').write_text(json.dumps(submission))
            result=monitor_tenders(temp)
            self.assertEqual(result['completed_count'],0)
            self.assertIn('integrity',result['rejected'][0]['reason'])

    def test_candidate_gate_no_promotion_and_regression(self):
        records=[candidate(i) for i in range(10)]
        approved=evaluate_candidate(records)
        self.assertEqual(approved['status'],'evaluated'); self.assertTrue(approved['noninferior'])
        self.assertFalse(approved['promotion_performed'])
        for record in records: record['candidate_probability']=0 if record['outcome']=='won' else 1
        failed=evaluate_candidate(records)
        self.assertFalse(failed['noninferior']); self.assertAlmostEqual(failed['brier_difference'],.75)

    def test_candidate_rejects_leakage_metadata_and_invalid_probability(self):
        for field,value in [('candidate_probability',float('nan')),('prediction_provenance',{}),('trained_project_ids',['t0'])]:
            records=[candidate(i) for i in range(10)]; records[0][field]=value
            result=evaluate_candidate(records)
            self.assertEqual(result['status'],'blocked'); self.assertEqual(len(result['rejected']),1)
        records=[candidate(i) for i in range(10)]
        records[0]['prediction_provenance']['generated_at']='2024-02-02'
        self.assertEqual(evaluate_candidate(records)['status'],'blocked')

    def test_historical_backtest_requires_cutoff_and_heldout_ids(self):
        records=[candidate(i) for i in range(10)]
        for row in records:
            row['prediction_provenance'].update(evaluation_mode='historical_backtest',generated_at='2025-01-01',
                training_cutoff='2023-12-01',trained_project_ids=[])
        self.assertEqual(evaluate_candidate(records)['status'],'evaluated')
        records[0]['prediction_provenance']['training_cutoff']='2024-02-01'
        self.assertEqual(evaluate_candidate(records)['status'],'blocked')

if __name__=='__main__': unittest.main()
