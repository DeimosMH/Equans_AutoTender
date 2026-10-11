"""Validated, project-grouped supervised datasets; public awards never imply bid wins."""
import hashlib
import json
import math
from pathlib import Path

TASKS = ('input_processing', 'productivity_factors', 'win_ratio', 'market_extraction')
# Only information available when bidding can be provided to win prediction.
BID_FIELDS = {'sector', 'canton', 'procedure', 'cpv_codes', 'estimated_value_chf',
              'bid_amount_chf', 'cost_amount_chf', 'margin_pct', 'evaluation_criteria',
              'competition_count_known_at_bid', 'deadline', 'scope', 'publication_date'}

def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)

def validate_record(record, task):
    if not isinstance(record, dict):
        raise ValueError('record must be an object')
    project = str(record.get('project_id', '')).strip()
    if not project:
        raise ValueError('project_id is required for leakage-safe splitting')
    inputs, target = record.get('input'), record.get('target')
    if not isinstance(inputs, dict) or not inputs:
        raise ValueError('input must be a nonempty object')
    if task == 'win_ratio':
        if record.get('source_kind') != 'own_bid':
            raise ValueError('win_ratio requires own_bid records, not public award announcements')
        if set(inputs) - BID_FIELDS:
            raise ValueError('unsupported or post-award input fields: ' + ', '.join(sorted(set(inputs) - BID_FIELDS)))
        if not record.get('bid_submitted_at') or not record.get('outcome_observed_at'):
            raise ValueError('bid_submitted_at and outcome_observed_at are required')
        from datetime import datetime
        try:
            bid = datetime.fromisoformat(str(record['bid_submitted_at']).replace('Z', '+00:00'))
            observed = datetime.fromisoformat(str(record['outcome_observed_at']).replace('Z', '+00:00'))
            if observed <= bid:
                raise ValueError('outcome must be observed after submission')
        except (TypeError, ValueError) as exc:
            raise ValueError('invalid bid/outcome chronology: ' + str(exc)) from exc
        if not isinstance(target, dict) or target.get('outcome') not in ('won', 'lost'):
            raise ValueError('target.outcome must be won or lost; probabilities are not labels')
        if set(target) != {'outcome'}:
            raise ValueError('win_ratio target must contain only outcome')
    elif task == 'productivity_factors':
        if not isinstance(target, dict) or not target:
            raise ValueError('target must contain measured productivity factors')
        if not record.get('measurement_reference'):
            raise ValueError('measurement_reference required; guessed factors are not training labels')
        for val in target.values():
            if isinstance(val, bool) or not isinstance(val, (float, int)) or not math.isfinite(val) or val <= 0:
                raise ValueError('productivity targets must be positive finite numbers')
    elif task == 'market_extraction':
        if record.get('source_kind') != 'public_structured_api' or not isinstance(target, dict) or not target:
            raise ValueError('market extraction requires trusted public structured API provenance')
    elif task == 'input_processing':
        if not isinstance(target, dict) or not target:
            raise ValueError('target must contain reviewed structured extraction')
        if not record.get('reviewed'):
            raise ValueError('reviewed=true required for extraction supervision')
    else:
        raise ValueError('unknown task')
    canonical(record)
    return {'project_id': project, 'input': inputs, 'target': target}

def read_upload(raw, task):
    records = []
    for number, line in enumerate(raw.decode('utf-8-sig').splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            validate_record(record, task)
        except (ValueError, TypeError) as exc:
            raise ValueError(f'line {number}: {exc}') from exc
        records.append(record)
    if not records:
        raise ValueError('upload contains no records; use JSONL task schema')
    return records

def prepare_dataset(records, task, output_dir, base_model):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    valid, rejected, seen, evidence = [], [], set(), {}
    for index, record in enumerate(records):
        try:
            normalized = validate_record(record, task)
            fingerprint = hashlib.sha256(canonical(normalized).encode()).hexdigest()
            if fingerprint in seen:
                raise ValueError('duplicate example')
            seen.add(fingerprint)
            valid.append(normalized)
            evidence[fingerprint] = {key:record[key] for key in (
                'source_kind', 'provenance', 'reviewed', 'measurement_reference',
                'bid_submitted_at', 'outcome_observed_at', 'submission_hash', 'outcome_revision',
                'evidence_reference', 'revision', 'recorded_at', 'verified') if key in record}
        except (ValueError, TypeError) as exc:
            rejected.append({'record_index': index, 'reason': str(exc)})
    groups = sorted({r['project_id'] for r in valid}, key=lambda p: hashlib.sha256(p.encode()).hexdigest())
    # Require held-out projects. Small uploads are valid storage but cannot support evaluation.
    assignments = {}
    if len(groups) >= 3:
        ntest = max(1, len(groups) // 10)
        nval = max(1, len(groups) // 10)
        for i, project in enumerate(groups):
            assignments[project] = 'test' if i < ntest else 'validation' if i < ntest+nval else 'train'
    else:
        assignments = {p: 'train' for p in groups}
    hashes, counts, examples = {}, {}, []
    for split in ('train', 'validation', 'test'):
        rows = []
        for record in sorted(valid, key=canonical):
            if assignments[record['project_id']] == split:
                fingerprint = hashlib.sha256(canonical(record).encode()).hexdigest()
                examples.append({'split':split, 'line':len(rows)+1, 'project_id':record['project_id'],
                    'fingerprint':fingerprint, 'evidence':evidence[fingerprint]})
                rows.append({'messages': [{'role':'system', 'content':f'Perform AutoTender {task}; return JSON.'},
                    {'role':'user', 'content':canonical(record['input'])},
                    {'role':'assistant', 'content':canonical(record['target'])}]})
        content = ''.join(canonical(row)+'\n' for row in rows).encode()
        (output / (split+'.jsonl')).write_bytes(content)
        hashes[split+'.jsonl'] = hashlib.sha256(content).hexdigest()
        counts[split] = len(rows)
    (output/'rejected.json').write_text(json.dumps(rejected, indent=2)+'\n')
    evidence_bytes = (json.dumps(examples, ensure_ascii=False, indent=2)+'\n').encode()
    (output/'examples.json').write_bytes(evidence_bytes)
    hashes['examples.json'] = hashlib.sha256(evidence_bytes).hexdigest()
    blockers = []
    if len(groups) < 3:
        blockers.append('At least three distinct projects are required for train/validation/test separation.')
    if task == 'win_ratio' and {r['target']['outcome'] for r in valid} != {'won','lost'}:
        blockers.append('Both own won and lost bids are required.')
    if task == 'win_ratio' and {r['target']['outcome'] for r in valid if assignments[r['project_id']] == 'train'} != {'won','lost'}:
        blockers.append('Training split must contain both outcome classes.')
    manifest = {'schema_version':1, 'task':task, 'base_model':base_model,
                'status':'blocked' if blockers else 'ready_for_training', 'blockers':blockers,
                'counts':counts, 'projects':assignments, 'hashes':hashes, 'rejected_count':len(rejected),
                'project_count':len(groups), 'accepted_count':len(valid),
                'split_strategy':'deterministic_project_groups',
                'purpose':task,
                'evaluation_required':True}
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return manifest
