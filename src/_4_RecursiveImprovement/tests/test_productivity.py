import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location('measured_productivity_test',Path(__file__).resolve().parents[1]/'productivity.py')
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


class ProductivityTests(unittest.TestCase):
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
