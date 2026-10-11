"""Auditable outcome feedback; public awards never label our participation.

Capture submission before outcome. Numeric comparisons are descriptive, not causal.
Only verified outcomes with prospectively frozen prebid inputs enter win training.
"""
import copy
import fcntl
import hashlib
import html
import importlib.util
import json
import math
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dataset = _module('feedback_dataset', ROOT.parent / '_3_Prediction/dataset.py')
simap = _module('feedback_simap', ROOT.parent / '_3_Prediction/collect/simap.py')
REASON_CODES = {'price', 'technical_score', 'references', 'capacity', 'compliance',
                'delivery', 'relationship', 'other', 'quality', 'withdrawal'}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _date(value, name):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError('timezone required')
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError) as exc:
        raise ValueError(f'{name} must be a timezone-aware ISO timestamp') from exc


def _number(value, name, positive=True):
    if isinstance(value, bool):
        raise ValueError(f'{name} must be numeric')
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f'{name} must be numeric') from exc
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(f'{name} must be positive and finite')
    return result


def _root(folder):
    return Path(folder) / 'feedback'


@contextmanager
def _lock(root):
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _atomic(path, value, raw=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = value if raw else json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.feedback-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read(root, name):
    path = root / name
    return json.loads(path.read_text()) if path.exists() else None


def _snapshot(root):
    snap = _read(root, 'submission.json')
    if snap is not None and _hash({k:v for k,v in snap.items() if k != 'hash'}) != snap.get('hash'):
        raise ValueError('Submission integrity check failed')
    return snap


def _outcome(root):
    result = _read(root, 'outcome.json')
    if result is not None:
        archive = _read(root, f"outcome_revisions/{result.get('revision', 0):06d}.json")
        snap = _snapshot(root)
        if archive != result or not snap or result.get('submission_hash') != snap['hash']:
            raise ValueError('Outcome integrity check failed')
    return result


def _audit(root, action, value):
    # One immutable event per operation: atomic files avoid partial JSONL appends.
    event = {'at': _now(), 'action': action, 'value': value}
    _atomic(root / 'audit' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '_' + uuid.uuid4().hex + '.json'), event)


def _commercial_snapshot(calc, params, payload):
    baseline = _number(calc['project_cost']['cost_baseline_chf'], 'cost baseline')
    margin = _number(payload.get('margin_pct', params['commercial']['target_margin_pct']), 'margin', False)
    if not 0 <= margin < 100:
        raise ValueError('margin must be in [0,100)')
    bid = _number(payload.get('bid_amount_chf', baseline / (1 - margin / 100)), 'bid amount')
    selected_margin = margin
    margin = 100 * (1 - baseline / bid)
    context = copy.deepcopy(payload.get('prebid_context', {}))
    if not isinstance(context, dict) or set(context) - dataset.BID_FIELDS:
        raise ValueError('prebid_context contains unsupported or post-award fields')
    context.update(bid_amount_chf=bid, cost_amount_chf=baseline, margin_pct=margin)
    snap = {
            'bid_amount_chf': bid, 'margin_pct': margin, 'selected_margin_pct': selected_margin, 'cost_baseline_chf': baseline,
            'prebid_input': context, 'calc': copy.deepcopy(calc), 'params': copy.deepcopy(params),
            'prediction': copy.deepcopy(calc.get('recommended_bid_range'))}
    cfg = params.get('stretch_bid_optimization', {})
    if (snap.get('prediction') or {}).get('model', {}).get('kind') == 'heuristic' and cfg.get('enabled'):
        reference = baseline / (1 - _number(params['commercial']['target_margin_pct'], 'reference margin', False) / 100)
        probability = float(cfg.get('reference_win_probability', .55)) + float(cfg.get('strategic_appetite_adjustment', 0)) + float(cfg.get('competition_adjustment', 0)) - float(cfg.get('price_sensitivity_probability_points_per_1pct_price', .05)) * (bid / reference - 1) * 100
        snap['predicted_win_probability'] = max(float(cfg.get('minimum_probability', .05)), min(float(cfg.get('maximum_probability', .95)), probability))
    return snap


def capture_submission(folder, calc, params, payload):
    root = _root(folder)
    with _lock(root):
        if _outcome(root):
            raise ValueError('Submission cannot be captured after an outcome was recorded')
        old = _snapshot(root)
        if old:
            # Repeated clicks cannot overwrite the authoritative commercial snapshot.
            return old
        now = datetime.now(timezone.utc)
        submitted = _date(payload.get('submitted_at', now.isoformat()), 'submitted_at')
        if submitted > now + timedelta(minutes=5):
            raise ValueError('Submission cannot be in the future')
        snap = _commercial_snapshot(calc, params, payload)
        snap.update(schema_version=1, project_id=Path(folder).name,
                    captured_at=now.isoformat(), submitted_at=submitted.isoformat(),
                    training_eligible=submitted >= now-timedelta(minutes=5) and not payload.get('retrospective', False),
                    capture_context='retrospective' if payload.get('retrospective', False) else 'submission')
        _canonical(snap)
        snap['hash'] = _hash(snap)
        _atomic(root / 'submission.json', snap)
        _audit(root, 'submission_captured', {'hash': snap['hash'], 'training_eligible': snap['training_eligible']})
        return snap


def _invalidate_export(root):
    export = _read(root, 'export.json')
    if export:
        path = Path(export['path'])
        # Only the file explicitly written for this project can be revoked.
        if path.name == f"win_ratio_feedback_{export['project_id']}.jsonl":
            with _lock(path.parent):
                path.unlink(missing_ok=True)
        _atomic(root / 'export.json', dict(export, status='revoked', revoked_at=_now()))


def _offer(root, offer_id):
    if not isinstance(offer_id, str) or not re.fullmatch('[a-f0-9]{32}', offer_id):
        raise ValueError('Invalid offer identifier')
    value = _read(root, f'offers/{offer_id}.json')
    if value is None:
        raise ValueError('Saved offer was not found')
    if _hash({k:v for k,v in value.items() if k != 'hash'}) != value.get('hash'):
        raise ValueError('Saved offer integrity check failed')
    return value


def read_offer(folder, offer_id):
    with _lock(_root(folder)):
        return _offer(_root(folder), offer_id)


def capture_offer(folder, calc, params, commercial, descriptions, completed=False):
    """A download freezes evidence; it does not assert that an offer was submitted."""
    root = _root(folder)
    with _lock(root):
        price = calc['project_cost'].get('indicative_selling_price_chf')
        value = _commercial_snapshot(calc, params, {'margin_pct':commercial['margin'],
            'bid_amount_chf':price if price is not None else round(calc['project_cost']['cost_baseline_chf']/(1-commercial['margin']/100), 2)})
        value.update(schema_version=1, project_id=Path(folder).name, commercial=commercial,
                     descriptions=descriptions, captured_before_completion=not completed and not _outcome(root))
        fingerprint = _hash(value)
        for path in sorted((root/'offers').glob('*.json')):
            old = _offer(root, path.stem)
            if old['fingerprint'] == fingerprint:
                return old
        value.update(id=uuid.uuid4().hex, captured_at=_now(), fingerprint=fingerprint)
        value['hash'] = _hash(value)
        _atomic(root/'offers'/f"{value['id']}.json", value)
        _audit(root, 'offer_downloaded', {'offer_id':value['id'], 'hash':value['hash']})
        return value


def confirm_offer_submission(folder, payload):
    root = _root(folder)
    with _lock(root):
        if _outcome(root):
            raise ValueError('Submission cannot change after an outcome was recorded')
        old = _snapshot(root)
        if old:
            return old
        offer = _offer(root, payload.get('offer_id'))
        submitted = _date(payload.get('submitted_at'), 'submitted_at')
        captured = _date(offer['captured_at'], 'captured_at')
        if submitted < captured:
            raise ValueError('The selected offer was downloaded after the submission date')
        if submitted > datetime.now(timezone.utc)+timedelta(minutes=5):
            raise ValueError('Submission cannot be in the future')
        if payload.get('bid_amount_chf') is not None and abs(_number(payload['bid_amount_chf'], 'bid amount')-offer['bid_amount_chf']) > .005:
            raise ValueError('Submitted price must match the selected offer')
        snap = {k:copy.deepcopy(v) for k,v in offer.items() if k not in ('id','hash','fingerprint','descriptions','captured_before_completion')}
        snap.update(offer_id=offer['id'], offer_hash=offer['hash'], confirmed_at=_now(),
                    submitted_at=submitted.isoformat(), training_eligible=offer['captured_before_completion'],
                    capture_context='downloaded_offer')
        snap['hash'] = _hash(snap)
        _atomic(root/'submission.json', snap)
        _audit(root, 'submission_confirmed', {'offer_id':offer['id'], 'hash':snap['hash']})
        return snap


def _measurement(root):
    value = _read(root, 'productivity.json')
    if value and value.get('revision') is not None:
        if value != _read(root, f"productivity_revisions/{value['revision']:06d}.json"):
            raise ValueError('Productivity revision integrity check failed')
    return value


def record_outcome(folder, payload):
    root = _root(folder)
    with _lock(root):
        snap = _snapshot(root)
        if not snap:
            raise ValueError('Capture submission before recording an outcome')
        outcome = payload.get('outcome')
        if outcome not in {'won', 'lost', 'withdrawn'}:
            raise ValueError('outcome must be won, lost or withdrawn')
        observed = _date(payload.get('observed_at', _now()), 'observed_at')
        if observed <= _date(snap['submitted_at'], 'submitted_at'):
            raise ValueError('Outcome must be observed after submission')
        if observed > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError('Outcome cannot be in the future')
        verified = payload.get('verified', False)
        confirmed = payload.get('reasons_confirmed', False)
        if not isinstance(verified, bool) or not isinstance(confirmed, bool):
            raise ValueError('verified/reasons_confirmed must be booleans')
        evidence = str(payload.get('evidence_reference', '')).strip()[:4000]
        if verified and not evidence:
            raise ValueError('Verified outcomes require an evidence reference')
        codes = payload.get('reason_codes', [])
        if not isinstance(codes, list) or any(c not in REASON_CODES for c in codes):
            raise ValueError('Invalid reason codes')
        if codes and confirmed and not evidence:
            raise ValueError('Confirmed reasons require evidence')
        competitors = payload.get('competitors', [])
        if not isinstance(competitors, list) or len(competitors) > 100:
            raise ValueError('competitors must be a list of at most 100 entries')
        checked = []
        for competitor in competitors:
            if not isinstance(competitor, dict) or not isinstance(competitor.get('comparable', False), bool):
                raise ValueError('Invalid competitor entry')
            checked.append({'name': str(competitor.get('name', ''))[:500],
                            'price_chf': _number(competitor.get('price_chf'), 'competitor price'),
                            'currency': str(competitor.get('currency', 'CHF'))[:10],
                            'comparable': competitor.get('comparable', False)})
        current = _outcome(root)
        if 'expected_revision' in payload and payload['expected_revision'] != (current or {}).get('revision', 0):
            raise ValueError('Outcome revision changed; reload before saving')
        result = {'schema_version': 1, 'submission_hash': snap['hash'],
                  'outcome': outcome, 'observed_at': observed.isoformat(), 'verified': verified,
                  'evidence_reference': evidence, 'reason_codes': sorted(set(codes)),
                  'reasons_confirmed': confirmed, 'narrative': str(payload.get('narrative', ''))[:20000],
                  'competitors': checked, 'winner': str(payload.get('winner', payload.get('winner_name', '')))[:500],
                  'award_price_comparable': payload.get('award_price_comparable') is True,
                  'award_price_chf': None if payload.get('award_price_chf') in (None, '') else _number(payload['award_price_chf'], 'award price')}
        if current and all(current.get(k) == v for k,v in result.items()):
            return current
        result.update(revision=(current or {}).get('revision', 0) + 1, recorded_at=_now())
        _invalidate_export(root)
        _atomic(root / 'outcome_revisions' / f"{result['revision']:06d}.json", result)
        _atomic(root / 'outcome.json', result)
        _audit(root, 'outcome_recorded', result)
        (root / 'analysis.json').unlink(missing_ok=True)
        return result


def gather_evidence(folder, urls):
    if not isinstance(urls, list) or not 1 <= len(urls) <= 20:
        raise ValueError('Provide 1–20 simap project URLs')
    # Validate all URLs before any network call; collector also validates redirects.
    for url in urls:
        simap.project_id(url)
    root = _root(folder)
    with _lock(root):
        result = simap.collect_sources(urls, root / 'public_evidence')
        previous = _read(root, 'evidence.json') or {}
        records = {r.get('publication_id', _hash(r)):r for r in previous.get('records', [])}
        records.update({r.get('publication_id', _hash(r)):r for r in result.get('records', [])})
        result['records'] = list(records.values())
        result['source_count'] = len(records)
        result['urls'] = sorted(set(previous.get('urls', [])) | set(urls))
        result['participation_inferred'] = False
        _atomic(root / 'evidence.json', result)
        _audit(root, 'evidence_gathered', {'counts': result['counts'], 'errors': result['errors'], 'urls': urls})
        return result


def _analysis(root):
    snap, outcome = _snapshot(root), _outcome(root)
    missing, observations = [], []
    if not snap:
        missing.append('Submission snapshot is missing.')
    if not outcome:
        missing.append('Outcome has not been recorded.')
    elif not outcome['verified']:
        missing.append('Outcome evidence has not been verified.')
    if outcome and not (outcome['reason_codes'] and outcome['reasons_confirmed']):
        missing.append('Confirmed debrief reasons are missing; price differences cannot establish why a bid lost.')
    if snap and not snap['training_eligible']:
        missing.append('Snapshot was captured retrospectively; excluded from training to prevent post-award leakage.')
    comparisons = []
    if snap and outcome:
        prices = [dict(c) for c in outcome.get('competitors', []) if c['comparable'] and c['currency'] == 'CHF']
        if outcome.get('award_price_chf') and outcome.get('award_price_comparable'):
            prices.append({'name': outcome.get('winner') or 'Award', 'price_chf': outcome['award_price_chf']})
        for competitor in prices:
            comparisons.append({'name': competitor['name'], 'price_chf': competitor['price_chf'],
                                'our_price_difference_chf': round(snap['bid_amount_chf'] - competitor['price_chf'], 2),
                                'our_price_difference_pct': round((snap['bid_amount_chf'] / competitor['price_chf'] - 1) * 100, 2)})
        if not prices:
            missing.append('No confirmed comparable CHF competitor or award price.')
    positions = (snap or {}).get('calc', {}).get('position_results', [])
    missing_quotes = [p for p in positions if p.get('status') == 'supplier_quote_required' or p.get('price_source') == 'supplier_quote_required']
    quote_share = len(missing_quotes) / len(positions) if positions else None
    if missing_quotes:
        observations.append(f'{len(missing_quotes)} of {len(positions)} submission positions required supplier quotes; this is a pricing completeness observation, not a loss reason.')
    eligible = bool(snap and snap['training_eligible'] and outcome and outcome['verified'] and outcome['outcome'] in {'won','lost'} and _date(outcome['observed_at'], 'observed_at') > _date(snap['captured_at'], 'captured_at'))
    return {'schema_version': 1, 'submission_hash': (snap or {}).get('hash'),
            'project_name': (snap or {}).get('calc', {}).get('project', {}).get('name', root.parent.name),
            'our_bid_chf': (snap or {}).get('bid_amount_chf'), 'submitted_at': (snap or {}).get('submitted_at'),
            'observed_at': (outcome or {}).get('observed_at'), 'evidence_reference': (outcome or {}).get('evidence_reference'),
            'outcome_revision': (outcome or {}).get('revision'), 'training_eligible': eligible,
            'outcome': (outcome or {}).get('outcome'), 'verified': (outcome or {}).get('verified', False),
            'confirmed_reason_codes': outcome['reason_codes'] if outcome and outcome['reasons_confirmed'] else [],
            'unconfirmed_reason_codes': outcome['reason_codes'] if outcome and not outcome['reasons_confirmed'] else [],
            'narrative': (outcome or {}).get('narrative', ''), 'comparisons': comparisons,
            'missing_quote_count': len(missing_quotes), 'position_count': len(positions),
            'missing_quote_share': quote_share, 'missing_information': missing,
            'observations': observations, 'causal_conclusion': 'No causal loss explanation is inferred. Confirmed reasons are attributed to the supplied evidence.',
            'report_markdown': 'reports/postmortem.md', 'report_html': 'reports/postmortem.html'}


def analyze(folder):
    root = _root(folder)
    with _lock(root):
        result = _analysis(root)
        _atomic(root / 'analysis.json', result)
        lines = ['Tendif - Tender outcome review', result['project_name'], '',
                 'Outcome: ' + (result['outcome'] or 'Not recorded').capitalize(),
                 'Our submitted offer: ' + (f"CHF {result['our_bid_chf']:,.2f}" if result['our_bid_chf'] else 'Not recorded'),
                 'Submitted: ' + str(result['submitted_at'] or 'Not recorded'),
                 'Result received: ' + str(result['observed_at'] or 'Not recorded'),
                 'Evidence: ' + str(result['evidence_reference'] or 'Not provided'),
                 '', 'Confirmed reasons: ' + (', '.join(c.replace('_',' ') for c in result['confirmed_reason_codes']) or 'Not provided'),
                 'Notes: ' + (result['narrative'] or 'None'), '', 'Missing information:']
        lines.extend('- ' + text for text in result['missing_information'])
        lines.extend(['', 'Observations:'] + ['- ' + text for text in result['observations']])
        lines.extend(['', 'Comparable prices:'] + [f"- {c['name']}: CHF {c['price_chf']:,.2f}; our offer {c['our_price_difference_pct']:+.2f}% (CHF {c['our_price_difference_chf']:+,.2f})." for c in result['comparisons']])
        lines.extend(['', result['causal_conclusion']])
        _atomic(root / 'reports/postmortem.txt', '\n'.join(lines) + '\n', raw=True)
        # Escaping all supplied text also makes Markdown safe in renderers allowing HTML.
        escaped = '\n'.join(html.escape(line) for line in lines)
        markdown = ''.join('\\' + ch if ch in '\\`*_{}[]()#+-.!|>' else ch for ch in escaped)
        _atomic(root / 'reports/postmortem.md', markdown + '\n', raw=True)
        _atomic(root / 'reports/postmortem.html', '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Tendif - Tender outcome review</title><style>body{max-width:850px;margin:40px auto;padding:0 24px;color:#24272b;background:#fff}pre{font:15px/1.7 system-ui,sans-serif;white-space:pre-wrap;overflow-wrap:anywhere;border-top:4px solid #c4420c;padding-top:24px}</style><main><pre>' + escaped + '</pre></main></html>', raw=True)
        return result


def export_feedback(folder, uploads):
    root = _root(folder)
    with _lock(root):
        snap, outcome = _snapshot(root), _outcome(root)
        if not _analysis(root)['training_eligible']:
            _invalidate_export(root)
            return {'status': 'withheld', 'task': 'win_ratio', 'record_count': 0, 'note': 'Only verified won/lost outcomes observed after a prospective submission snapshot can be exported.'}
        record = {'project_id': snap['project_id'], 'source_kind': 'own_bid',
                  'bid_submitted_at': snap['submitted_at'], 'outcome_observed_at': outcome['observed_at'],
                  'input': snap['prebid_input'], 'target': {'outcome': outcome['outcome']},
                  'submission_hash': snap['hash'], 'outcome_revision': outcome['revision'],
                  'evidence_reference': outcome['evidence_reference']}
        dataset.validate_record(record, 'win_ratio')
        uploads = Path(uploads)
        with _lock(uploads):
            path = uploads / f"win_ratio_feedback_{snap['project_id']}.jsonl"
            if path.parent.resolve() != uploads.resolve():
                raise ValueError('Invalid project identifier')
            _atomic(path, _canonical(record) + '\n', raw=True)
        result = {'status': 'exported', 'task': 'win_ratio', 'path': str(path.resolve()),
                  'project_id': snap['project_id'], 'revision': outcome['revision'],
                  'record_hash': _hash(record), 'record_count': 1,
                  'note': 'Feedback exported; no model is trained or promoted automatically.'}
        old = _read(root, 'export.json')
        _atomic(root / 'export.json', result)
        if old != result:
            _audit(root, 'feedback_exported', result)
        return result


def overview(folder):
    root = _root(folder)
    with _lock(root):
        return {'submission': _snapshot(root), 'outcome': _outcome(root),
                'analysis': _read(root, 'analysis.json'), 'evidence': _read(root, 'evidence.json'),
                'export': _read(root, 'export.json'), 'reason_codes': sorted(REASON_CODES),
                'productivity': _measurement(root),
                'offers': sorted([{k:v for k,v in _offer(root, p.stem).items() if k in
                    ('id','hash','captured_at','bid_amount_chf','captured_before_completion')}
                    for p in (root/'offers').glob('*.json')], key=lambda r:r['captured_at'], reverse=True)}
