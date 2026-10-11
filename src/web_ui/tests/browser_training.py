"""Optional real-browser smoke test. Requires Playwright and its Chromium browser.
Run: python tests/browser_training.py (uses temporary storage, never user tenders).
"""
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright, expect

BASE = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    address = f'http://127.0.0.1:{port}'
    process = subprocess.Popen([sys.executable,str(BASE/'server.py'),str(port)],
        env={**os.environ,'AUTOTENDER_UI_DATA_DIR':temp},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(address,timeout=1).close();break
            except OSError:time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width':1440,'height':1000})
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(address+'/#training')
            expect(page.locator('#tr-model, #tr-file, .tr-splits')).to_have_count(0)
            expect(page.get_by_role('button',name='Sources',exact=True)).to_have_count(0)
            page.get_by_role('button',name='Advanced',exact=True).click()
            expect(page.get_by_role('button',name='Advanced',exact=True)).to_be_focused()
            page.get_by_role('button',name='Data preparation',exact=True).click()
            page.get_by_role('button',name='Productivity',exact=True).click()
            expect(page).to_have_url(address+'/#lora-settings/advanced/data-preparation/productivity-factors')
            expect(page.get_by_role('button',name='Productivity',exact=True)).to_be_focused()
            expect(page.locator('#tr-evidence')).to_contain_text('No measurements yet')
            expect(page.locator('#tr-prepare')).to_be_hidden()
            page.get_by_role('button',name='Add measurements',exact=True).click()
            expect(page.locator('#tr-tender-picker')).to_contain_text('Upload and calculate a tender first')
            page.get_by_role('button',name='Public notices',exact=True).click()
            page.get_by_role('button',name='Prepare training data',exact=False).click()
            expect(page.locator('#tr-result')).to_contain_text('Data ready',timeout=15000)
            expect(page.locator('#tr-model')).to_have_value('glm-5.3-flash')
            page.get_by_role('button',name='Review examples').click()
            expect(page.locator('.tr-example')).to_have_count(3)
            page.locator('#tr-preview-split').select_option('test')
            expect(page.locator('#tr-preview-split')).to_have_value('test')
            with page.expect_download() as download:
                page.get_by_role('link',name='Download training data',exact=False).click()
            with zipfile.ZipFile(download.value.path()) as bundle:
                assert json.loads(bundle.read('training_request.json'))['base_model']=='glm-5.3-flash'
                assert 'examples.json' in bundle.namelist()
            page.locator('#tr-model').fill('cloud/glm-5.3-flash')
            page.get_by_role('button',name='Save as default',exact=True).click()
            expect(page.locator('#tr-message')).to_have_text('Default model saved.')
            page.locator('#tr-existing').uncheck()
            page.get_by_role('button',name='LoRAs',exact=True).click()
            expect(page.locator('#tr-model, #tr-existing')).to_have_count(0)
            page.get_by_role('button',name='Advanced',exact=True).click()
            page.locator('#tr-existing').check()
            expect(page.locator('#tr-evidence')).to_contain_text('examples from')
            page.get_by_role('button',name='Tender matching',exact=True).click()
            page.get_by_role('button',name='Prepare training data',exact=False).click()
            expect(page.locator('#tr-result')).to_contain_text('More examples needed',timeout=10000)
            expect(page.locator('#tr-result')).to_contain_text('22 examples accepted')
            page.get_by_text('Preparation details & files',exact=True).click()
            expect(page.locator('.tr-artifacts')).to_contain_text('cloud/glm-5.3-flash')
            page.locator('#tr-existing').check()
            page.get_by_role('button',name='Bid outcomes',exact=True).click()
            page.locator('#tr-file').set_input_files({'name':'invalid.jsonl','mimeType':'application/json','buffer':b'{"project_id":"bad"}\n'})
            expect(page.locator('#tr-upload-status')).to_contain_text('line 1')
            page.get_by_role('button',name='Productivity',exact=True).click()
            measurement={'project_id':'site-1','measurement_reference':'approved-timesheet',
                'input':{'site_type':'school'},'target':{'site_efficiency':.9}}
            page.locator('#tr-file').set_input_files({'name':'measured.jsonl','mimeType':'application/json','buffer':(json.dumps(measurement)+'\n').encode()})
            expect(page.locator('#tr-upload-status')).to_contain_text('1 example added')
            expect(page.locator('#tr-upload-count')).to_have_text('1')
            page.get_by_role('button',name='Prepare training data',exact=False).click()
            expect(page.locator('#tr-result')).to_contain_text('1 example accepted',timeout=10000)
            page.get_by_role('button',name='Sources',exact=True).click()
            page.locator('#tr-source-filter').fill('nonexistent-source-xyz')
            expect(page.locator('#tr-source-list')).to_contain_text('No publications match')
            page.locator('#tr-urls').fill('http://localhost/private')
            page.get_by_role('button',name='Import notices',exact=False).click()
            expect(page.locator('#tr-message')).to_contain_text('HTTPS simap.ch')
            page.get_by_role('button',name='History',exact=True).click()
            expect(page.locator('.tr-table tbody tr')).to_have_count(3)
            page.locator('[data-run]').last.click()
            expect(page.locator('#tr-result')).to_contain_text('Data ready')
            expect(page).to_have_url(address+'/#lora-settings/advanced/data-preparation/market-extraction')
            # Existing calculator workflow and unsaved drafts survive visiting training.
            page.locator('#addBtn').click();page.locator('#tenderName').fill('Browser review')
            page.locator('#createBtn').click()
            expect(page.locator('#tenderTitle')).to_have_text('Browser review')
            expect(page.locator('#emptywrap')).to_be_visible()
            positions=(BASE.parent/'_2_Calculator/input/example_lv_positions.csv').read_text()
            positions=positions.replace('LV0001,','LV0001<img src=x onerror=alert(1)>,',1)
            page.locator('#bigFile').set_input_files({'name':'positions.csv','mimeType':'text/csv','buffer':positions.encode()})
            expect(page.locator('#posTable tbody tr')).to_have_count(22,timeout=15000)
            expect(page.locator('#posTable img')).to_have_count(0)
            expect(page.locator('#posTable tbody tr').first).to_contain_text('LV0001<img src=x onerror=alert(1)>')
            quantity=page.locator('#posTable input[data-f="quantity"]').first
            quantity.fill('7')
            page.locator('#trainingBtn').click()
            training_url=page.url
            page.go_back()
            expect(page.locator('#posTable input[data-f="quantity"]').first).to_have_value('7')
            expect(page).to_have_url(address+'/')
            page.go_forward()
            expect(page.locator('#tr-model')).to_be_visible()
            expect(page).to_have_url(training_url)
            page.locator('#tenderList .tname').click()
            expect(page).to_have_url(address+'/')
            expect(page.locator('#posTable input[data-f="quantity"]').first).to_have_value('7')
            expect(page.locator('#saveBtn')).to_be_enabled()
            page.locator('#overhead').fill('12')
            page.locator('#saveBtn').click()
            expect(page.locator('#saveBtn')).to_be_disabled()
            expect(page.locator('#posTable input[data-f="quantity"]').first).to_have_value('7')
            expect(page.locator('#overhead')).to_have_value('12')
            expect(page.locator('#predictionNote, #scenarioResults, #feedbackPanel')).to_have_count(0)
            expect(page.get_by_text('Compare bid scenarios',exact=True)).to_have_count(0)
            page.locator('#posTable input[data-f="quantity"]').first.fill('9')
            page.locator('#overhead').fill('12')
            page.locator('#pdfBtn').click()
            with page.expect_download() as offer_download:
                page.locator('#dlMenu a[data-fmt="html"]').click()
            assert b'Tendif' in Path(offer_download.value.path()).read_bytes()
            expect(page.locator('#saveBtn')).to_be_disabled()
            expect(page.locator('#tenderActionMsg')).to_have_text('Offer saved and downloaded.')
            assert page.locator('#cPrice').inner_text().encode() in Path(offer_download.value.path()).read_bytes()
            page.locator('#finaliseBtn').click()
            expect(page.locator('#feedbackPanel')).to_be_visible()
            expect(page.locator('#outcomeFiles')).to_be_hidden()
            expect(page.get_by_role('button',name='Upload documents',exact=True)).to_be_visible()
            expect(page.locator('#posTable input[data-f="quantity"]').first).to_have_value('9')
            expect(page.locator('#posTable input[data-f="quantity"]').first).to_be_disabled()
            expect(page.locator('#overhead')).to_have_value('12')
            assert page.locator('#feedbackPanel').evaluate('e=>e===document.querySelector("#content").firstElementChild')
            # A newer tender must not replace the selected one on reload.
            page.request.post(address+'/api/tenders',data={'name':'Another tender'})
            page.reload()
            expect(page.locator('#tenderTitle')).to_have_text('Browser review')
            expect(page.locator('#feedbackPanel')).to_be_visible()
            expect(page.locator('#overhead')).to_have_value('12')
            page.locator('#outcomeFiles').set_input_files({'name':'award-letter.pdf','mimeType':'application/pdf','buffer':b'%PDF-1.4\nsynthetic award'})
            expect(page.locator('#outcomeDocuments')).to_contain_text('award-letter.pdf')
            with page.expect_download() as evidence_download:
                page.locator('#outcomeDocuments a').click()
            assert Path(evidence_download.value.path()).read_bytes()==b'%PDF-1.4\nsynthetic award'
            page.locator('#feedbackOutcome').select_option('won')
            expect(page.locator('#submittedOfferField')).to_be_visible()
            page.locator('#submittedOffer').select_option(index=1)
            assert page.locator('#feedbackBid').evaluate('e=>e.readOnly')
            submitted=datetime.now()+timedelta(seconds=2)
            date_value=lambda value:value.isoformat(timespec='minutes' if value.second==0 else 'seconds')
            page.locator('#feedbackSubmitted').fill(date_value(submitted))
            page.locator('#feedbackObserved').fill(date_value(submitted+timedelta(seconds=1)))
            page.locator('#feedbackNarrative').fill('Award confirmed by the client.')
            page.get_by_text('Decision details',exact=True).click()
            page.locator('#feedbackVerified').check()
            page.locator('#recordOutcome').click()
            expect(page.locator('#feedbackMessage')).to_have_text('Outcome saved.')
            page.reload()
            expect(page.locator('#feedbackOutcome')).to_have_value('won')
            expect(page.locator('#feedbackNarrative')).to_have_value('Award confirmed by the client.')
            expect(page.locator('#outcomeDocuments')).to_contain_text('award-letter.pdf')
            page.locator('#feedbackOutcome').select_option('lost')
            page.locator('#recordOutcome').click()
            expect(page.locator('#feedbackMessage')).to_have_text('Outcome saved.')
            page.locator('#trainingBtn').click()
            page.get_by_role('button',name='Advanced',exact=True).click()
            page.get_by_role('button',name='Data preparation',exact=True).click()
            page.get_by_role('button',name='Productivity',exact=True).click()
            page.get_by_role('button',name='Add measurements',exact=True).click()
            page.locator('#tr-open-tender').click()
            expect(page.locator('#tenderTitle')).to_have_text('Browser review')
            expect(page.locator('#measurementForm')).to_be_visible()
            page.locator('[data-measure="site_efficiency"]').fill('0.93')
            page.locator('#measurementReference').fill('Approved installation timesheet')
            page.locator('#measurementVerified').check()
            page.locator('#recordMeasurement').click()
            expect(page.locator('#measurementMessage')).to_have_text('Measurement saved.')
            page.locator('#trainingBtn').click()
            expect(page.locator('#tr-evidence')).to_contain_text('2 examples from 2 tenders')
            page.get_by_role('button',name='Add measurements',exact=True).click()
            page.locator('#tr-open-tender').click()
            page.reload()
            page.get_by_text('Actual productivity',exact=True).click()
            expect(page.locator('[data-measure="site_efficiency"]')).to_have_value('0.93')
            expect(page.locator('#measurementReference')).to_have_value('Approved installation timesheet')
            page.locator('#revokeMeasurement').click()
            expect(page.locator('#measurementMessage')).to_have_text('Measurement excluded from learning.')
            page.locator('#reopenBtn').click()
            expect(page.locator('#feedbackPanel')).to_have_count(0)
            expect(page.locator('#finaliseBtn')).to_be_visible()
            expect(page.locator('#posTable input[data-f="quantity"]').first).to_be_enabled()
            page.locator('#settingsBtn').click();page.locator('.switch').click()
            page.locator('#trainingBtn').click()
            page.get_by_role('button',name='Advanced',exact=True).click()
            page.get_by_role('button',name='Evaluation',exact=True).click()
            page.get_by_role('button',name='Prepare review',exact=True).click()
            expect(page.locator('[data-message]')).to_contain_text('Bundle saved.')
            expect(page.locator('.learning-review')).to_have_count(1)
            with page.expect_download() as review_download:
                page.get_by_role('link',name='Download bundle',exact=False).click()
            with zipfile.ZipFile(review_download.value.path()) as bundle:
                assert 'reference.json' not in bundle.namelist()
                assert len(bundle.read('evaluation_inputs.jsonl').splitlines())==1
            page.reload()
            page.get_by_role('button',name='Advanced',exact=True).click()
            page.get_by_role('button',name='Evaluation',exact=True).click()
            expect(page.locator('.learning-review')).to_have_count(1)
            page.locator('#trainingBtn').click()
            expect(page.locator('body')).to_have_class('dark')
            page.get_by_role('button',name='Advanced',exact=True).click()
            page.get_by_role('button',name='Data preparation',exact=True).click()
            for width in (1440,900,390):
                page.set_viewport_size({'width':width,'height':900})
                if width==390:
                    page.locator('#navToggle').click()
                    page.wait_for_function('document.querySelector("nav").getBoundingClientRect().width <= 1')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                for label in ('Sources','History','Data preparation'):
                    page.get_by_role('button',name=label,exact=True).click()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width,label)
                    assert page.evaluate('document.querySelector(".views").scrollWidth <= document.querySelector(".views").clientWidth'), (width,label,'inner overflow')
            assert not errors,errors
            browser.close()
            print('PASS: datasets, downloads, tender editing, finalisation/reopen, document upload/download, persisted outcome corrections, dark mode and responsive layouts')
    finally:
        process.terminate();process.wait(timeout=10)
