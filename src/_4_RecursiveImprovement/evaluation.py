"""Local, persisted evaluation handoffs. Provider execution and activation stay external."""
import hashlib
import json
import re
import uuid
import zipfile
from pathlib import Path

import core
import monitoring


class ReviewStore:
    def __init__(self, root):
        self.root = Path(root)

    def _directory(self, review_id):
        if not isinstance(review_id, str) or not re.fullmatch('[a-f0-9]{32}', review_id):
            raise ValueError('Invalid review identifier')
        return self.root/review_id

    def get(self, review_id):
        folder = self._directory(review_id)
        value = json.loads((folder/'review.json').read_text())
        if (folder/'result.json').exists():
            value['result'] = json.loads((folder/'result.json').read_text())
        return value

    def list(self):
        return sorted((self.get(p.parent.name) for p in self.root.glob('*/review.json')),
                      key=lambda v:v['created_at'], reverse=True)

    def artifact(self, review_id, name):
        allowed = {'handoff.zip','evaluation_request.json','evaluation_inputs.jsonl','manifest.json',
                   'response.json','result.json'}
        if name not in allowed:
            raise ValueError('Unknown review artifact')
        folder = self._directory(review_id)
        self._verify(folder)
        path = folder/name
        if not path.is_file():
            raise FileNotFoundError(name)
        return path

    def _verify(self, folder):
        review = json.loads((folder/'review.json').read_text())
        for name, digest in review['artifacts'].items():
            if hashlib.sha256((folder/name).read_bytes()).hexdigest() != digest:
                raise ValueError('Review artifact integrity check failed; prepare a new review')

    def prepare(self, tenders_root, base_model):
        review_id, inputs, references = uuid.uuid4().hex, [], []
        for row in monitoring.monitor_tenders(tenders_root)['predictions']:
            with core._lock(Path(tenders_root)/row['tender_id']/'feedback'):
                snap = core._snapshot(Path(tenders_root)/row['tender_id']/'feedback')
                outcome = core._outcome(Path(tenders_root)/row['tender_id']/'feedback')
                if snap['hash'] != row['submission_hash'] or outcome['revision'] != row['outcome_revision']:
                    raise ValueError('Outcome changed during preparation; try again')
                item = {'tender_id':row['tender_id'], 'input':snap['prebid_input']}
                item['input_hash'] = core._hash(item)
                inputs.append(item)
                references.append(dict(row, input_hash=item['input_hash']))
        blockers = []
        if len(inputs) < 10:
            blockers.append('At least 10 verified outcomes with saved pre-result offers are required.')
        if {r['outcome'] for r in references} != {'won','lost'}:
            blockers.append('Both won and lost outcomes are required.')
        folder = self._directory(review_id)
        request = {'schema_version':1, 'review_id':review_id, 'operation':'evaluate_win_probability',
            'base_model':base_model, 'status':'not_submitted', 'inputs':'evaluation_inputs.jsonl',
            'input_count':len(inputs), 'transport':'pending_cloud_endpoint',
            'response_schema':{'review_id':review_id, 'candidate_model_id':'provider adapter/model identifier',
                'provenance':{'verified':True, 'source':'provider job or evidence reference',
                    'training_cutoff':'timezone-aware ISO timestamp before every submitted bid',
                    'trained_project_ids':['complete list of project ids used to train this candidate']},
                'predictions':[{'tender_id':'id from inputs', 'input_hash':'hash from inputs',
                    'probability':'number in [0,1]', 'generated_at':'timezone-aware ISO timestamp'}]},
            'requirements':['Return exactly one prediction per input, including its unchanged input_hash.',
                'Exclude all evaluation projects from candidate training.',
                'Use a candidate trained only on evidence available before the evaluated bids.',
                'Reference outcomes and baseline scores remain local. Results require human review.']}
        core._atomic(folder/'evaluation_inputs.jsonl', ''.join(core._canonical(r)+'\n' for r in inputs), raw=True)
        core._atomic(folder/'reference.json', references)
        core._atomic(folder/'evaluation_request.json', request)
        hashes = {name:hashlib.sha256((folder/name).read_bytes()).hexdigest()
                  for name in ('evaluation_inputs.jsonl','evaluation_request.json','reference.json')}
        review = {'schema_version':1, 'id':review_id, 'created_at':core._now(), 'base_model':base_model,
                  'kind':'prepared', 'status':'blocked' if blockers else 'ready', 'samples':len(inputs),
                  'blockers':blockers, 'endpoint_status':'pending', 'artifacts':hashes}
        core._atomic(folder/'manifest.json', {k:v for k,v in review.items() if k != 'artifacts'} |
            {'artifacts':{k:v for k,v in hashes.items() if k != 'reference.json'}})
        with zipfile.ZipFile(folder/'handoff.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for name in ('evaluation_inputs.jsonl','evaluation_request.json','manifest.json'):
                archive.write(folder/name, name)
        for name in ('manifest.json','handoff.zip'):
            hashes[name] = hashlib.sha256((folder/name).read_bytes()).hexdigest()
        core._atomic(folder/'review.json', review)
        return self.get(review_id)

    def evaluate(self, review_id, tenders_root, response):
        folder = self._directory(review_id)
        with core._lock(folder):
            self._verify(folder)
            if (folder/'response.json').exists():
                if json.loads((folder/'response.json').read_text()) != response:
                    raise ValueError('This review already has results; prepare a new review for another candidate')
                if 'result.json' in self.get(review_id)['artifacts']:
                    return self.get(review_id)
            if not isinstance(response, dict) or response.get('review_id') != review_id:
                raise ValueError('Results must identify this review')
            references = json.loads((folder/'reference.json').read_text())
            predictions, provenance = response.get('predictions'), response.get('provenance')
            if not isinstance(predictions, list) or not isinstance(provenance, dict):
                raise ValueError('Results require predictions and verified training provenance')
            model_id = response.get('candidate_model_id')
            if not isinstance(model_id, str) or not model_id.strip():
                raise ValueError('A candidate model identifier is required')
            expected = {r['tender_id']:r for r in references}
            seen, records = set(), []
            current = {r['tender_id']:r for r in monitoring.monitor_tenders(tenders_root)['predictions']}
            for item in predictions:
                if not isinstance(item, dict) or not isinstance(item.get('tender_id'), str):
                    raise ValueError('Each prediction must identify a tender')
                tid = item['tender_id']
                if tid not in expected or tid in seen:
                    raise ValueError('Results contain an unknown or duplicate tender')
                seen.add(tid)
                row = expected[tid]
                if item.get('input_hash') != row['input_hash']:
                    raise ValueError('Prediction input hash does not match this review')
                if any(current.get(tid, {}).get(k) != row[k] for k in ('submission_hash','outcome_revision','outcome_sha256')):
                    raise ValueError('Outcome evidence changed; prepare a new review')
                records.append(dict(row, outcome_verified=True, champion_probability=row['probability'],
                    candidate_probability=item.get('probability'), prediction_provenance=dict(provenance,
                        model_id=model_id, generated_at=item.get('generated_at'), evaluation_mode='historical_backtest')))
            if seen != set(expected):
                raise ValueError('Return predictions for every tender in the handoff')
            result = monitoring.evaluate_candidate(records)
            # Invalid submissions can be corrected; do not consume this handoff.
            if result['rejected']:
                raise ValueError(result['rejected'][0]['reason'])
            result['review_id'] = review_id
            core._atomic(folder/'response.json', response)
            core._atomic(folder/'result.json', result)
            review = self.get(review_id)
            review.pop('result', None)
            review.update(status=result['status'], candidate_model_id=model_id)
            for name in ('response.json','result.json'):
                review['artifacts'][name] = hashlib.sha256((folder/name).read_bytes()).hexdigest()
            core._atomic(folder/'review.json', review)
            return self.get(review_id)

    def evaluate_external(self, records):
        """Compatibility path for the existing CLI/API with independently supplied pairs."""
        result = monitoring.evaluate_candidate(records)
        review_id = uuid.uuid4().hex
        result['review_id'] = review_id
        folder = self._directory(review_id)
        core._atomic(folder/'result.json', result)
        core._atomic(folder/'review.json', {'id':review_id, 'created_at':core._now(), 'kind':'external',
            'status':result['status'], 'samples':result['samples'], 'blockers':result['blockers'],
            'artifacts':{'result.json':hashlib.sha256((folder/'result.json').read_bytes()).hexdigest()}})
        return result
