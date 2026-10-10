#!/usr/bin/env python3
"""Prepare an auxiliary LoRA dataset from archived structured simap source records.
This teaches notice metadata normalization, not LV extraction or bid-win probabilities.
"""
import argparse
import hashlib
import json
from pathlib import Path
from dataset import prepare_dataset
from training import write_training_request


def prepare(corpus_dir, output, base_model):
    records = []
    for name in ('market_awards.jsonl', 'public_tenders.jsonl'):
        path = Path(corpus_dir) / name
        if path.exists():
            records.extend(json.loads(line) for line in path.read_text().splitlines() if line.strip())
    examples = []
    for record in records:
        provenance = record['provenance']
        path = Path(provenance['raw_path'])
        if not path.exists():
            path = Path(corpus_dir) / 'raw' / 'simap' / (provenance['sha256'] + '.json')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != provenance['sha256']:
            raise ValueError('Raw snapshot hash mismatch: ' + str(path))
        target = {key:record[key] for key in ('record_type','title','description','buyer','canton',
                  'publication_date','cpv_codes','bkp_codes') if record.get(key) is not None}
        examples.append({'project_id':record['tender_id'], 'source_kind':'public_structured_api',
                         'input':{'source_document':json.loads(raw)}, 'target':target})
    manifest = prepare_dataset(examples, 'market_extraction', output, base_model)
    manifest['supervision'] = 'deterministic API metadata normalization; not full LV extraction or win prediction'
    manifest['source_records'] = [{'publication_id':r['publication_id'],
                                  'provenance':r['provenance']} for r in records]
    (Path(output) / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    write_training_request(output, manifest)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus-dir', type=Path, default=Path(__file__).resolve().parent/'data')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent/'output'/'market_extraction')
    parser.add_argument('--base-model', required=True, help='Provider/Hugging Face model identifier; confirm before training')
    args = parser.parse_args()
    result = prepare(args.corpus_dir, args.output, args.base_model)
    print(json.dumps({k:v for k,v in result.items() if k not in ('source_records','projects')}))
