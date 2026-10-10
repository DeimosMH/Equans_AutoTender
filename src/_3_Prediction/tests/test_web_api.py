import importlib.util,json,tempfile,threading,time,urllib.request,urllib.error,sys
from pathlib import Path
path=Path(__file__).resolve().parents[2]/'web_ui'/'server.py'
spec=importlib.util.spec_from_file_location('autotender_ui',path); app=importlib.util.module_from_spec(spec); spec.loader.exec_module(app)
from http.server import ThreadingHTTPServer
from jobs import JobStore
def smoke_test():
  with tempfile.TemporaryDirectory() as temp:
      root=Path(temp); app.UI_SETTINGS=root/'settings.json'; app.UPLOADS=root/'uploads'; app.TENDERS=root/'tenders'; app.PREPARATION_JOBS=JobStore(root/'jobs')
      http=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
      thread=threading.Thread(target=http.serve_forever,daemon=True); thread.start()
      base='http://127.0.0.1:'+str(http.server_port)
      def request(route, data=None):
          req=urllib.request.Request(base+route,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'})
          with urllib.request.urlopen(req) as res: return res.status,json.load(res)
      try:
          status,settings=request('/api/settings'); assert all(t['selected'] is None for t in settings['tasks'].values())
          status,res=request('/api/settings/update',{'task':'win_ratio','links':''}); assert status==202
          jid=res['job']['id']
          for _ in range(100):
              status,job=request('/api/settings/jobs/'+jid)
              if job['status'] not in ('queued','collecting','preparing'): break
              time.sleep(.01)
          assert job['status']=='blocked',job
          status,manifest=request('/api/settings/jobs/'+jid+'/artifacts/manifest.json'); assert manifest['status']=='blocked'
          status,meta=request('/api/tenders',{'name':'smoke'})
          tid=meta['id']; directory=app.TENDERS/tid
          import shutil
          shutil.copy(app.BASE.parent/'_2_Calculator/input/example_lv_positions.csv',directory/'positions.csv')
          status,recalc=request('/api/tenders/'+tid+'/recalc',{})
          status,result=request('/api/tenders/'+tid); assert result['calc']['recommended_bid_range']['model']['trained'] is False
          status,curve=request('/api/tenders/'+tid+'/wincurve?baseline=600000'); assert curve['cost_baseline_chf']==600000 and len(curve['curve'])==31
          print('PASS: localhost settings/jobs/artifacts/create/recalculate/prediction APIs with isolated storage')
      finally:
          http.shutdown(); http.server_close()

import unittest

class WebAPITests(unittest.TestCase):
    def test_preparation_and_calculator_routes(self):
        smoke_test()

if __name__ == "__main__":
    unittest.main()
