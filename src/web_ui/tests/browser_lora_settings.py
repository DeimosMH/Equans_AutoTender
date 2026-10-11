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
            page.locator('[data-lm-path="data_dir"]').fill('/data/reviewed-tenders')
            page.locator('[data-lm-parameter="rank"]').fill('32')
            page.get_by_role('button', name='Save configuration', exact=True).click()
            expect(page.locator('#lm-message')).to_contain_text('Configuration saved')
            page.get_by_role('button', name='LoRAs', exact=True).click()
            page.get_by_role('button', name='Update LoRAs', exact=True).click()
            page.locator('#lm-internal').uncheck()
            page.get_by_role('button', name='Update LoRA', exact=True).click()
            expect(page.locator('#lm-message')).to_contain_text('Choose internal training data or add a link')
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
            assert request['data_dir'] == '/data/reviewed-tenders'
            assert request['parameters']['rank'] == 32
            assert request['include_internal'] and len(request['links']) == 2
            page.get_by_role('button', name='Productivity factors', exact=True).click()
            expect(page.get_by_role('button', name='Create LoRA', exact=True)).to_be_visible()
            page.get_by_role('button', name='Create LoRA', exact=True).click()
            saved = page.evaluate('JSON.parse(localStorage.getItem("tendif_lora_preferences_v1"))')
            assert saved['requests']['productivity_factors']['adapter'] is None
            assert saved['requests']['productivity_factors']['parameters']['rank'] == 16
            page.reload()
            page.get_by_role('button', name='Update LoRAs', exact=True).click()
            expect(page.locator('#lm-links')).to_have_value('https://www.simap.ch/de/project-detail/example\nhttps://example.org/reviewed-data')
            expect(page.locator('#lm-request')).to_contain_text('Update request saved')
            page.get_by_role('button', name='Select LoRAs', exact=True).click()
            page.get_by_role('link', name='Edit expert productivity values', exact=False).click()
            expect(page.locator('#pfRows')).to_be_visible()
            assert not errors, errors
            assert not mutations, mutations
            assert settings.read_bytes() == original
            browser.close()
            print('PASS: task selections, base compatibility, expert fallback, local persistence, update requests, advanced parameters; no backend mutations')
    finally:
        process.terminate()
        process.wait(timeout=10)
