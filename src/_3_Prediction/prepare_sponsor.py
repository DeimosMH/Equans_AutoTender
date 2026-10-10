#!/usr/bin/env python3
"""Seed reviewed catalogue-matching examples from sponsor materials.
The source CSV is supervised matching evidence, not verified raw-PDF extraction.
One project cannot support independent train/validation/test evaluation.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from dataset import prepare_dataset
from training import write_training_request

ROOT = Path(__file__).resolve().parents[2]

def prepare(materials, output, base_model):
    pdf = materials/'BKP_244_LV_Lueftung_260804.pdf'
    with (materials/'example_lv_positions.csv').open(newline='') as file:
        rows = list(csv.DictReader(file))
    with (materials/'catalog.csv').open(newline='') as file:
        catalog = list(csv.DictReader(file))
    examples = []
    for row in rows:
        examples.append({'project_id':'sponsor:oberglatt-erlenstrasse', 'reviewed':True,
            'input': {'description':row['description'], 'quantity':float(row['quantity']),
                      'unit':row['unit'], 'manufacturer_hint':row['manufacturer_hint'],
                      'model_hint':row['model_hint'], 'catalog':catalog},
            'target': {'suggested_product_id':row['suggested_product_id'],
                       'install_code':row['expected_install_code'],
                       'status':row['ground_truth_status']}})
    output.mkdir(parents=True, exist_ok=True)
    (output/'sponsor_matching.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in examples))
    manifest = prepare_dataset(examples,'input_processing',output,base_model)
    manifest.update(purpose='reviewed_catalog_matching', pdf_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(),
                    pdf=str(pdf), supervision='Sponsor verified CSV descriptions and catalogue matches; not raw PDF extraction.',
                    source_page_note='CSV source_page values retained in original CSV; physical PDF alignment needs review before extraction supervision.')
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    write_training_request(output,manifest)
    return manifest

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--materials',type=Path,default=ROOT/'materials')
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parent/'output'/'sponsor_matching')
    parser.add_argument('--base-model',required=True)
    args=parser.parse_args()
    print(json.dumps(prepare(args.materials,args.output,args.base_model)))
