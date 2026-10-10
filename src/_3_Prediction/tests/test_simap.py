import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1]/'collect'/'simap.py'
spec = importlib.util.spec_from_file_location('simap', MODULE)
simap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(simap)
PID = 'd849c22b-3fc4-48d8-94c9-c45457544ab1'
PUB = 'b22afaa7-5791-4192-ad6c-42e493158a25'
URL = 'https://www.simap.ch/de/project-detail/'+PID


def fixture(kind):
    return {'base':{'projectId':PID,'id':PUB,'publicationDate':'2026-08-06'},'type':kind,'project-info':{'title':{'de':'244 Lüftungsanlagen'},'procOfficeAddress':{'name':{'de':'Gemeinde'},'cantonId':'ZH'}},'procurement':{'bkpCodes':[244],'cpvCode':{'code':'45331000'}},'decision':{'numberOfSubmissions':4,'vendors':[{'vendorName':'Real company','price':{'price':123.45,'currency':'chf','vatType':'full'}}],'awardDecisionJustification':{'de':'Highest score'}}}


class SimapTest(unittest.TestCase):
    def test_url_boundary(self):
        self.assertEqual(simap.project_id(URL),PID)
        for url in ['http://www.simap.ch/de/project-detail/'+PID,'https://www.simap.ch.evil.example/de/project-detail/'+PID,'https://user@www.simap.ch/de/project-detail/'+PID,URL+'?redirect=https://localhost', 'https://127.0.0.1/de/project-detail/'+PID]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                simap.project_id(url)

    def test_tender_cannot_become_win_label(self):
        row = simap.normalize(fixture('tender'),{})
        self.assertEqual(row['record_type'],'public_tender')
        self.assertEqual(row['winners'],[])
        self.assertNotIn('outcome',row)
        self.assertNotIn('win_probability',row)

    def test_award_preserves_price_and_provenance(self):
        row = simap.normalize(fixture('award'),{'sha256':'hash'})
        self.assertEqual(row['winners'][0]['price'],123.45)
        self.assertEqual(row['winners'][0]['currency'],'CHF')
        self.assertEqual(row['number_of_submissions'],4)
        self.assertEqual(row['provenance']['sha256'],'hash')
        self.assertNotIn('outcome',row)

    def test_collection_split_and_idempotency(self):
        def get(client,url):
            if url.endswith('project-header'):
                return {'latestPublication':{'id':PUB}}, {}
            return fixture('tender'), {'sha256':'hash'}
        with tempfile.TemporaryDirectory() as temp, patch.object(simap.Client,'get',get):
            first = simap.collect_sources([URL],temp)
            simap.collect_sources([URL],temp)
            self.assertEqual(first['counts'],{'market_awards':0,'public_tenders':1})
            rows = Path(first['public_tenders_path']).read_text().splitlines()
            self.assertEqual(len(rows),1)
            self.assertEqual(json.loads(rows[0])['publication_id'],PUB)
            self.assertEqual(Path(first['market_awards_path']).read_text(),'')

    def test_validation_precedes_network(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(simap.Client,'get') as get:
            with self.assertRaises(ValueError):
                simap.collect_sources(['https://localhost/'],temp)
            get.assert_not_called()

    def test_failed_fetch_reports_no_fake_record(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(simap.Client,'get',side_effect=OSError('offline')):
            result = simap.collect_sources([URL],temp)
            self.assertEqual(result['records'],[])
            self.assertEqual(len(result['errors']),1)


if __name__ == '__main__':
    unittest.main()
