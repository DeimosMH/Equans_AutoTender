import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location('measured_productivity_test',Path(__file__).resolve().parents[1]/'productivity.py')
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


class ProductivityTests(unittest.TestCase):
    def test_correction_revision_conflict_revocation_and_restore(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'t_fixture';uploads=Path(temp)/'uploads'
            params={'productivity_factors':{'site_efficiency':.88}}
            payload={'verified':True,'expected_revision':0,'measurement_reference':'Timesheet',
                'input':{'work_type':'duct'},'target':{'site_efficiency':.9}}
            saved=module.record_measurement(folder,uploads,params,payload)
            self.assertEqual(saved['revision'],1)
            payload['target']={'site_efficiency':.95}
            with self.assertRaisesRegex(ValueError,'revision changed'):module.record_measurement(folder,uploads,params,payload)
            payload['expected_revision']=1
            module.record_measurement(folder,uploads,params,payload)
            revoked=module.revoke_measurement(folder,uploads,{'expected_revision':2})
            self.assertEqual(revoked['revision'],3);self.assertFalse(revoked['verified'])
            self.assertFalse(list(uploads.glob('*.jsonl')))
            self.assertEqual(len(list((folder/'feedback/productivity_revisions').glob('*.json'))),3)
            payload['expected_revision']=3
            module.record_measurement(folder,uploads,params,payload)
            self.assertEqual(len(list(uploads.glob('*.jsonl'))),1)
            record=module.core.overview(folder)['productivity'];self.assertEqual(record['revision'],4)
            next(uploads.glob('*.jsonl')).unlink()
            payload['expected_revision']=4
            self.assertEqual(module.record_measurement(folder,uploads,params,payload)['revision'],4)
            self.assertEqual(len(list(uploads.glob('*.jsonl'))),1)
            record['target']['site_efficiency']=.3
            (folder/'feedback/productivity.json').write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError,'integrity'):module.core.overview(folder)

    def test_verified_measurements_replace_stable_export_without_changing_parameters(self):
        params={'productivity_factors':{'site_efficiency':.88}}
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'t_fixture'; uploads=Path(temp)/'uploads'
            payload={'verified':True,'measurement_reference':'Synthetic measured time','input':{'work_type':'duct'},'target':{'site_efficiency':.9}}
            module.record_measurement(folder,uploads,params,payload)
            payload['target']={'site_efficiency':.95}
            module.record_measurement(folder,uploads,params,payload)
            files=list(uploads.glob('productivity_factors_feedback_*.jsonl'))
            self.assertEqual(len(files),1)
            self.assertEqual(json.loads(files[0].read_text())['target']['site_efficiency'],.95)
            self.assertEqual(params['productivity_factors']['site_efficiency'],.88)
            for updates in ({'verified':False},{'measurement_reference':''},{'target':{'unknown':1}}, {'target':{'site_efficiency':float('inf')}}):
                invalid=dict(payload,**updates)
                with self.assertRaises(ValueError): module.record_measurement(folder,uploads,params,invalid)
            self.assertEqual(json.loads(files[0].read_text())['target']['site_efficiency'],.95)

if __name__=='__main__': unittest.main()
