"""Exercise the LoRA UI preview without creating or activating remote models.
Run with Playwright + Chromium: python tests/browser_lora_settings.py
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import expect, sync_playwright

BASE = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as temp:
    settings = Path(temp) / 'ui_settings.json'
    settings.write_text(json.dumps({'base_model': 'glm-5.3-flash', 'tasks': {
        'input_processing': {'versions': [{'version': 'Tender reader v2', 'base': 'glm-5.3-flash'}]},
        'productivity_factors': {'versions': [{'version': 'Site measurements v1', 'base': 'GLM-4.6'}]},
        'win_ratio': {'versions': [{'version': 'Bid results v3', 'base': 'glm-5.3-flash'}]},
    }}))
    original = settings.read_bytes()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    process = subprocess.Popen([sys.executable, str(BASE/'server.py'), str(port)],
        env={**os.environ, 'AUTOTENDER_UI_DATA_DIR': temp},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(url, timeout=1).close()
                break
            except OSError:
                time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors, mutations = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: mutations.append(request.url) if request.method != 'GET' else None)
            page.goto(url+'/#training')
            expect(page.locator('[data-lm-select]')).to_have_count(3)
            expect(page).to_have_url(url+'/#lora-settings/loras/select')
            expect(page.locator('[data-lm-path], [data-lm-parameter], #tr-model')).to_have_count(0)
            page.locator('#lm-input_processing').select_option(label='Tender reader v2 · GLM 5.3 Flash')
            page.locator('#lm-productivity_factors').select_option(label='Site measurements v1 · GLM-4.6')
            expect(page.locator('#lm-base-productivity_factors')).to_have_text('Base model: GLM-4.6')
            page.get_by_role('button', name='Save choices', exact=True).click()
            page.reload()
            expect(page.locator('#lm-productivity_factors option:checked')).to_contain_text('Site measurements v1')
            page.get_by_role('button', name='Base models', exact=True).click()
            expect(page.get_by_role('button', name='Base models', exact=True)).to_be_focused()
            expect(page.locator('#lm-input_processing')).to_have_value('glm-5.3-flash')
            expect(page.locator('#lm-productivity_factors')).to_have_value('GLM-4.6')
            page.locator('#lm-productivity_factors').select_option('glm-5.3-flash')
            expect(page.locator('#lm-base-productivity_factors')).to_contain_text('Expert values (manual)')
            page.get_by_role('button', name='Select LoRAs', exact=True).click()
            expect(page.locator('#lm-productivity_factors')).to_have_value('')
            expect(page.locator('#lm-input_processing option:checked')).to_contain_text('Tender reader v2')
            page.get_by_role('button', name='Save choices', exact=True).click()
            page.get_by_role('button', name='Advanced', exact=True).click()
            expect(page.get_by_role('button', name='Cloud', exact=True)).to_have_attribute('aria-pressed', 'true')
            expect(page.locator('#lm-cloud-endpoint')).to_have_value('')
            expect(page.locator('[data-lm-path]')).to_have_count(0)
            page.get_by_role('button', name='Save configuration', exact=True).click()
            expect(page.locator('#lm-message')).to_contain_text('Configuration saved')
            page.get_by_role('button', name='Local', exact=True).click()
            expect(page.get_by_role('button', name='Local', exact=True)).to_be_focused()
            expect(page).to_have_url(url+'/#lora-settings/advanced/configuration/input-processing/local')
            page.go_back()
            expect(page.get_by_role('button', name='Cloud', exact=True)).to_have_attribute('aria-pressed', 'true')
            expect(page).to_have_url(url+'/#lora-settings/advanced/configuration/input-processing/cloud')
            page.go_forward()
            expect(page.get_by_role('button', name='Local', exact=True)).to_have_attribute('aria-pressed', 'true')
            page.reload()
            expect(page.get_by_role('button', name='Local', exact=True)).to_have_attribute('aria-pressed', 'true')
            # The link restores the form selection without saving over the stored configuration.
            assert page.evaluate('JSON.parse(localStorage.getItem("tendif_lora_preferences_v1")).advanced.execution_mode') == 'cloud'
            expect(page.locator('#lm-cloud-endpoint')).to_have_count(0)
            page.locator('[data-lm-path="data_dir"]').fill('/data/reviewed-tenders')
            page.locator('[data-lm-parameter="rank"]').fill('32')
            page.get_by_role('button', name='Save configuration', exact=True).click()
            expect(page.locator('#lm-message')).to_contain_text('Configuration saved')
            page.get_by_role('button', name='LoRAs', exact=True).click()
            page.get_by_role('button', name='Update LoRAs', exact=True).click()
            page.locator('#lm-internal').uncheck()
            page.get_by_role('button', name='Update LoRA', exact=True).click()
            expect(page.locator('#lm-message')).to_contain_text('Choose internal training data, upload files or add a link')
            with page.expect_file_chooser() as picker:
                page.get_by_role('button', name='Upload data', exact=True).click()
            picker.value.set_files([
                {'name': 'positions.csv', 'mimeType': 'text/csv', 'buffer': b'quantity\n10\n'},
                {'name': 'tender-notes.txt', 'mimeType': 'text/plain', 'buffer': b'Reviewed input'},
            ])
            expect(page.locator('#lm-file-count')).to_have_text('2 files selected')
            page.get_by_role('button', name='Remove tender-notes.txt', exact=True).click()
            expect(page.locator('#lm-file-count')).to_have_text('1 file selected')
            page.get_by_role('button', name='Productivity factors', exact=True).click()
            expect(page.locator('#lm-file-count')).to_have_text('No files selected')
            expect(page).to_have_url(url+'/#lora-settings/loras/update/productivity-factors')
            page.go_back()
            expect(page).to_have_url(url+'/#lora-settings/loras/update/input-processing')
            expect(page.get_by_role('button', name='Input processing', exact=True)).to_have_attribute('aria-pressed', 'true')
            expect(page.locator('#lm-file-list')).to_contain_text('positions.csv')
            page.go_forward()
            expect(page.get_by_role('button', name='Productivity factors', exact=True)).to_have_attribute('aria-pressed', 'true')
            page.get_by_role('button', name='Input processing', exact=True).click()
            # Clicking an already selected tab must not add duplicate history entries.
            history_length = page.evaluate('history.length')
            page.get_by_role('button', name='Input processing', exact=True).click()
            assert page.evaluate('history.length') == history_length
            # Files alone are a valid source, with no internal data or links.
            page.get_by_role('button', name='Update LoRA', exact=True).click()
            saved = page.evaluate('JSON.parse(localStorage.getItem("tendif_lora_preferences_v1"))')
            upload_request = saved['requests']['input_processing']
            assert not upload_request['include_internal'] and not upload_request['links']
            assert upload_request['files'][0]['name'] == 'positions.csv'
            assert upload_request['files'][0]['size'] == len(b'quantity\n10\n')
            page.locator('#lm-links').fill('javascript:alert(1)')
            page.get_by_role('button', name='Update LoRA', exact=True).click()
            assert not page.locator('#lm-links').evaluate('e=>e.validity.valid')
            page.locator('#lm-internal').check()
            page.locator('#lm-links').fill('https://www.simap.ch/de/project-detail/example\nhttps://example.org/reviewed-data')
            page.get_by_role('button', name='Update LoRA', exact=True).click()
            expect(page.locator('#lm-message')).to_have_text('Update request saved. Waiting for the training service.')
            saved = page.evaluate('JSON.parse(localStorage.getItem("tendif_lora_preferences_v1"))')
            request = saved['requests']['input_processing']
            assert request['adapter']['version'] == 'Tender reader v2'
            assert request['base_model'] == request['adapter']['base'] == 'glm-5.3-flash'
            assert request['execution']['mode'] == 'local'
            assert request['execution']['paths']['data_dir'] == '/data/reviewed-tenders'
            assert 'endpoint' not in request['execution']
            assert request['parameters']['rank'] == 32
            assert request['include_internal'] and len(request['links']) == 2
            page.get_by_role('button', name='Productivity factors', exact=True).click()
            expect(page.get_by_role('button', name='Create LoRA', exact=True)).to_be_visible()
            page.get_by_role('button', name='Create LoRA', exact=True).click()
            saved = page.evaluate('JSON.parse(localStorage.getItem("tendif_lora_preferences_v1"))')
            assert saved['requests']['productivity_factors']['adapter'] is None
            assert saved['requests']['productivity_factors']['parameters']['rank'] == 16
            page.reload()
            expect(page.get_by_role('button', name='Update LoRAs', exact=True)).to_have_attribute('aria-pressed', 'true')
            expect(page.get_by_role('button', name='Productivity factors', exact=True)).to_have_attribute('aria-pressed', 'true')
            page.get_by_role('button', name='Input processing', exact=True).click()
            expect(page.locator('#lm-links')).to_have_value('https://www.simap.ch/de/project-detail/example\nhttps://example.org/reviewed-data')
            expect(page.locator('#lm-request')).to_contain_text('Update request saved')
            expect(page.locator('#lm-file-list')).to_be_empty()
            expect(page.locator('#lm-file-reminder')).to_be_visible()
            # Execution choices persist; switching to cloud preserves local paths.
            page.get_by_role('button', name='Advanced', exact=True).click()
            expect(page.get_by_role('button', name='Local', exact=True)).to_have_attribute('aria-pressed', 'true')
            expect(page.locator('[data-lm-path="data_dir"]')).to_have_value('/data/reviewed-tenders')
            page.get_by_role('button', name='Cloud', exact=True).click()
            expect(page.locator('[data-lm-path]')).to_have_count(0)
            expect(page.locator('[data-lm-parameter="rank"]')).to_have_value('32')
            page.locator('#lm-cloud-endpoint').fill('ftp://training.example')
            page.get_by_role('button', name='Save configuration', exact=True).click()
            expect(page.locator('#lm-message')).to_contain_text('Use an http:// or https:// cloud endpoint')
            # An invalid endpoint must not overwrite the last saved update request.
            previous = page.evaluate('JSON.parse(localStorage.getItem("tendif_lora_preferences_v1")).requests.input_processing')
            page.get_by_role('button', name='LoRAs', exact=True).click()
            page.get_by_role('button', name='Update LoRA', exact=True).click()
            expect(page.locator('#lm-message')).to_contain_text('Use an http:// or https:// cloud endpoint')
            assert page.evaluate('JSON.parse(localStorage.getItem("tendif_lora_preferences_v1")).requests.input_processing') == previous
            page.get_by_role('button', name='Advanced', exact=True).click()
            page.locator('#lm-cloud-endpoint').fill('')
            page.get_by_role('button', name='Save configuration', exact=True).click()
            page.get_by_role('button', name='LoRAs', exact=True).click()
            expect(page.locator('.lm-footer')).to_contain_text('Cloud · endpoint pending')
            page.get_by_role('button', name='Update LoRA', exact=True).click()
            saved = page.evaluate('JSON.parse(localStorage.getItem("tendif_lora_preferences_v1"))')
            assert saved['requests']['input_processing']['execution'] == {'mode': 'cloud', 'endpoint': None}
            assert 'data_dir' not in saved['requests']['input_processing']
            page.get_by_role('button', name='Advanced', exact=True).click()
            page.locator('#lm-cloud-endpoint').fill('https://training.example/v1')
            page.get_by_role('button', name='Save configuration', exact=True).click()
            page.get_by_role('button', name='LoRAs', exact=True).click()
            page.get_by_role('button', name='Update LoRA', exact=True).click()
            saved = page.evaluate('JSON.parse(localStorage.getItem("tendif_lora_preferences_v1"))')
            assert saved['requests']['input_processing']['execution'] == {'mode': 'cloud', 'endpoint': 'https://training.example/v1'}
            page.reload()
            page.get_by_role('button', name='Advanced', exact=True).click()
            expect(page.get_by_role('button', name='Cloud', exact=True)).to_have_attribute('aria-pressed', 'true')
            expect(page.locator('#lm-cloud-endpoint')).to_have_value('https://training.example/v1')
            page.get_by_role('button', name='Local', exact=True).click()
            expect(page.locator('[data-lm-path="data_dir"]')).to_have_value('/data/reviewed-tenders')
            page.get_by_role('button', name='Cloud', exact=True).click()
            expect(page.locator('#lm-cloud-endpoint')).to_have_value('https://training.example/v1')
            page.get_by_role('button', name='LoRAs', exact=True).click()
            page.get_by_role('button', name='Select LoRAs', exact=True).click()
            page.get_by_role('link', name='Edit expert productivity values', exact=False).click()
            expect(page.locator('#pfRows')).to_be_visible()
            expect(page).to_have_url(url+'/#settings')
            page.go_back()
            expect(page.get_by_role('button', name='Select LoRAs', exact=True)).to_have_attribute('aria-pressed', 'true')
            page.go_forward()
            expect(page.locator('#pfRows')).to_be_visible()
            # Shared links restore every menu, including its task, in a fresh browser context.
            shared = browser.new_page()
            shared.on('pageerror', lambda error: errors.append(str(error)))
            shared.on('request', lambda request: mutations.append(request.url) if request.method != 'GET' else None)
            routes = [
                ('loras/select', ['LoRAs', 'Select LoRAs']),
                ('loras/base-models', ['LoRAs', 'Base models']),
                ('advanced/sources', ['Advanced', 'Sources']),
                ('advanced/history', ['Advanced', 'History']),
                ('advanced/evaluation', ['Advanced', 'Evaluation']),
            ]
            for task, label in [('input-processing', 'Input processing'), ('productivity-factors', 'Productivity factors'), ('win-ratio', 'Success probability')]:
                routes.append((f'loras/update/{task}', ['LoRAs', 'Update LoRAs', label]))
                for runtime in ['local', 'cloud']:
                    routes.append((f'advanced/configuration/{task}/{runtime}', ['Advanced', 'Configuration', label, runtime.title()]))
            for task, label in [('market-extraction', 'Public notices'), ('input-processing', 'Tender matching'), ('win-ratio', 'Bid outcomes'), ('productivity-factors', 'Productivity')]:
                routes.append((f'advanced/data-preparation/{task}', ['Advanced', 'Data preparation', label]))
            for path, buttons in routes:
                shared.goto(url+'/#lora-settings/'+path)
                for button in buttons:
                    expect(shared.get_by_role('button', name=button, exact=True)).to_have_attribute('aria-pressed', 'true')
                shared.reload()
                for button in buttons:
                    expect(shared.get_by_role('button', name=button, exact=True)).to_have_attribute('aria-pressed', 'true')
                expect(shared).to_have_url(url+'/#lora-settings/'+path)
            # An explicit Cloud link overrides a saved Local selection, keeping form values private.
            saved_config = {'advanced': {'execution_mode': 'local', 'cloud_endpoint': 'https://training.example/v1', 'data_dir': '/data/reviewed'}}
            shared.evaluate('(value)=>localStorage.setItem("tendif_lora_preferences_v1",JSON.stringify(value))', saved_config)
            shared.goto(url+'/#lora-settings/advanced/configuration/win-ratio/cloud')
            shared.reload()
            expect(shared.get_by_role('button', name='Cloud', exact=True)).to_have_attribute('aria-pressed', 'true')
            expect(shared.locator('#lm-cloud-endpoint')).to_have_value('https://training.example/v1')
            assert shared.evaluate('JSON.parse(localStorage.getItem("tendif_lora_preferences_v1"))') == saved_config
            # Legacy links without a mode use the browser's saved selection.
            shared.goto('about:blank')
            shared.goto(url+'/#lora-settings/advanced/configuration/win-ratio')
            expect(shared.get_by_role('button', name='Local', exact=True)).to_have_attribute('aria-pressed', 'true')
            expect(shared).to_have_url(url+'/#lora-settings/advanced/configuration/win-ratio/local')
            expect(shared.locator('[data-lm-path="data_dir"]')).to_have_value('/data/reviewed')
            shared.evaluate('localStorage.removeItem("tendif_lora_preferences_v1")')
            shared.goto(url+'/#lora-settings/advanced/configuration/input-processing/cloud')
            shared.reload()
            # Partial and invalid paths fall back to a valid, canonical view.
            for path, canonical in [
                ('training', 'loras/select'),
                ('lora-settings/advanced/configuration', 'advanced/configuration/input-processing/cloud'),
                ('lora-settings/advanced/unknown/invalid', 'advanced/configuration/input-processing/cloud'),
                ('lora-settings/advanced/configuration/input-processing/invalid', 'advanced/configuration/input-processing/cloud'),
                ('lora-settings/advanced/data-preparation/invalid', 'advanced/data-preparation/market-extraction'),
                ('lora-settings/loras/update/invalid', 'loras/update/input-processing'),
                ('lora-settings/unknown/%3Cscript%3E', 'loras/select'),
            ]:
                shared.evaluate('(hash)=>{location.hash=hash}', path)
                expect(shared).to_have_url(url+'/#lora-settings/'+canonical)
            # Navigating before the initial tender list arrives must still open the chosen route.
            delayed = []
            shared.route('**/api/tenders', lambda route: delayed.append(route))
            shared.goto(url+'/')
            shared.locator('#trainingBtn').click()
            shared.get_by_role('button', name='Advanced', exact=True).click()
            shared.get_by_role('button', name='Productivity factors', exact=True).click()
            delayed[0].continue_()
            shared.wait_for_load_state('networkidle')
            expect(shared).to_have_url(url+'/#lora-settings/advanced/configuration/productivity-factors/cloud')
            expect(shared.get_by_role('button', name='Productivity factors', exact=True)).to_have_attribute('aria-pressed', 'true')
            shared.close()
            assert not errors, errors
            assert not mutations, mutations
            assert settings.read_bytes() == original
            browser.close()
            print('PASS: task selections, base compatibility, expert fallback, local persistence, update requests, Local/Cloud configuration, shared tab links, reload, Back/Forward and invalid routes; no backend mutations')
    finally:
        process.terminate()
        process.wait(timeout=10)
