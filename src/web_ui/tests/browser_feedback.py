"""Candidate review in a real browser, with isolated synthetic outcome evidence."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE.parent/'_4_RecursiveImprovement'))
import core

with tempfile.TemporaryDirectory() as temp:
    root=Path(temp)
    for i in range(10):
        folder=root/'tenders'/f't{i}'
        calc={'project_cost':{'cost_baseline_chf':100},'recommended_bid_range':{'model':{'kind':'heuristic'}}}
        params={'commercial':{'target_margin_pct':5},'stretch_bid_optimization':{'enabled':True}}
        with patch.object(core,'_now',return_value='2024-01-01T00:00:00Z'):
            offer=core.capture_offer(folder,calc,params,{'margin':5},{})
        core.confirm_offer_submission(folder,{'offer_id':offer['id'],'submitted_at':'2024-01-02T00:00:00Z'})
        core.record_outcome(folder,{'outcome':'won' if i%2 else 'lost','verified':True,
            'evidence_reference':'Synthetic browser fixture','observed_at':'2024-02-01T00:00:00Z'})
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    address=f'http://127.0.0.1:{port}'
    process=subprocess.Popen([sys.executable,str(BASE/'server.py'),str(port)],
        env={**os.environ,'AUTOTENDER_UI_DATA_DIR':temp},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:urllib.request.urlopen(address,timeout=1).close();break
            except OSError:time.sleep(.1)
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(viewport={'width':1280,'height':1000})
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(address+'/#settings')
            expect(page.locator('#saveSettingsBtn')).to_be_visible()
            expect(page.locator('#learningDetails, [data-prepare]')).to_have_count(0)
            page.locator('#trainingBtn').click()
            expect(page.get_by_role('button',name='Select LoRAs',exact=True)).to_be_visible()
            expect(page.locator('[data-prepare]')).to_have_count(0)
            page.get_by_role('button',name='Advanced',exact=True).click()
            page.get_by_role('button',name='Evaluation',exact=True).click()
            expect(page.locator('[data-metrics]')).to_contain_text('10')
            page.get_by_role('button',name='Prepare review',exact=True).click()
            expect(page.locator('[data-message]')).to_contain_text('Bundle ready.')
            with page.expect_download() as download:
                page.get_by_role('link',name='Download bundle',exact=False).click()
            review=page.request.get(address+'/api/feedback/reviews').json()['reviews'][0]
            inputs=[json.loads(line) for line in (root/'feedback_reviews'/review['id']/'evaluation_inputs.jsonl').read_text().splitlines()]
            response={'review_id':review['id'],'candidate_model_id':'synthetic-candidate<script>alert(1)</script>',
                'provenance':{'source':'synthetic-job','verified':True,'training_cutoff':'2023-01-01T00:00:00Z','trained_project_ids':[]},
                'predictions':[{'tender_id':r['tender_id'],'input_hash':r['input_hash'],
                    'probability':.5,'generated_at':'2025-01-01T00:00:00Z'} for r in inputs]}
            upload=page.locator('[data-import]')
            upload.set_input_files({'name':'invalid.json','mimeType':'application/json','buffer':b'{}'})
            expect(page.locator('[data-message]')).to_contain_text('Results must identify this review')
            upload.set_input_files({'name':'results.json','mimeType':'application/json','buffer':json.dumps(response).encode()})
            expect(page.locator('[data-message]')).to_have_text('Review saved.')
            expect(page.locator('.learning-review')).to_contain_text('Ready for human review')
            expect(page.locator('.learning-review script')).to_have_count(0)
            expect(page.locator('.learning-review')).to_contain_text('0.250')
            with page.expect_download() as result_download:
                page.get_by_role('link',name='Download review',exact=False).click()
            assert json.loads(Path(result_download.value.path()).read_text())['promotion_performed'] is False
            page.reload()
            page.get_by_role('button',name='Advanced',exact=True).click()
            page.get_by_role('button',name='Evaluation',exact=True).click()
            expect(page.locator('.learning-review')).to_contain_text('Ready for human review')
            page.locator('.learning-review summary').click()
            for dark,width in ((False,1280),(True,1280),(True,768),(True,390)):
                page.evaluate('(dark)=>setDarkMode(dark)',dark)
                page.set_viewport_size({'width':width,'height':1000})
                if width==390:
                    page.evaluate('document.body.classList.add("navoff")')
                    page.wait_for_function('document.querySelector("nav").getBoundingClientRect().width <= 1')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert page.evaluate('document.querySelector(".views").scrollWidth <= document.querySelector(".views").clientWidth')
                axe=Path('/tmp/autotender-axe.min.js')
                if axe.exists():
                    page.add_script_tag(path=str(axe))
                    audit=page.evaluate('async()=>await axe.run(document,{runOnly:{type:"tag",values:["wcag2a","wcag2aa","wcag21aa"]}})')
                    assert not audit['violations'],audit['violations']
                page.screenshot(path=f'/tmp/tendif-learning-{width}-{"dark" if dark else "light"}.png',full_page=True)
            assert not errors,errors
            browser.close()
            print('PASS: candidate handoff, invalid/valid import, saved review, downloads, light/dark/mobile layouts and optional axe audit')
    finally:
        process.terminate();process.wait(timeout=10)
