"""Descriptive feedback monitoring and paired candidate review; never promotes models.

Page-Hinkley recurrence follows scikit-multiflow's positive cumulative sum:
https://github.com/scikit-multiflow/scikit-multiflow/blob/master/src/skmultiflow/drift_detection/page_hinkley.py
Parameters below are application choices, not statistically validated guarantees.
"""
import hashlib
import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import median
import core


def _date(value):
    result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timestamps must include a timezone')
    return result.astimezone(timezone.utc)


def _probability(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('probability must be a finite number in [0,1]')
    return float(value)


def _frozen_probability(submission):
    direct = submission.get('predicted_win_probability')
    if direct is not None:
        return _probability(direct)
    prediction = submission.get('prediction') or {}
    curve = prediction.get('curve') or prediction.get('scenarios') or []
    if not curve:
        return None
    margin = float(submission['margin_pct'])
    if not math.isfinite(margin):
        raise ValueError('invalid frozen margin')
    points = []
    for point in curve:
        x = float(point['margin_pct'])
        y = _probability((point.get('p_win') or {}).get('mid',point.get('estimated_win_probability')))
        if not math.isfinite(x): raise ValueError('invalid prediction curve margin')
        points.append((x,y))
    points.sort()
    for x,y in points:
        if abs(x-margin) < 1e-9: return y
    for (left,p_left),(right,p_right) in zip(points,points[1:]):
        if left < margin < right:
            return p_left + (p_right-p_left)*(margin-left)/(right-left)
    raise ValueError('submitted margin lies outside captured prediction curve')


class PageHinkley:
    """One-sided increase detector; use a second instance on negative signed errors."""
    def __init__(self, minimum_instances=10, threshold=8, delta=.005, alpha=.9999):
        if minimum_instances < 1 or threshold <= 0 or delta < 0 or not 0 < alpha <= 1:
            raise ValueError('invalid drift detector parameters')
        self.minimum_instances, self.threshold, self.delta, self.alpha = minimum_instances, threshold, delta, alpha
        self.count, self.mean, self.cumulative, self.alert = 0, 0., 0., False

    def update(self, value):
        if not math.isfinite(value):
            raise ValueError('nonfinite drift observation')
        self.count += 1
        self.mean += (value - self.mean) / self.count
        self.cumulative = max(0., self.alpha * self.cumulative + value - self.mean - self.delta)
        self.alert = self.count >= self.minimum_instances and self.cumulative > self.threshold
        return self.alert


def monitor_tenders(tenders_root):
    root = Path(tenders_root)
    completed, predictions, rejected, competitors = [], [], [], {}
    for folder in sorted(root.iterdir()) if root.exists() else []:
        if not folder.is_dir():
            continue
        submission_path, outcome_path = folder/'feedback'/'submission.json', folder/'feedback'/'outcome.json'
        if not submission_path.exists() or not outcome_path.exists():
            continue
        try:
            with core._lock(folder/'feedback'):
                submission = core._snapshot(folder/'feedback')
                outcome = json.loads(outcome_path.read_text())
                submission_digest = hashlib.sha256(submission_path.read_bytes()).hexdigest()
                outcome_digest = hashlib.sha256(outcome_path.read_bytes()).hexdigest()
                if outcome.get('revision') is not None:
                    core._outcome(folder/'feedback')
            snapshot_hash = submission['hash']
            if outcome.get('submission_hash') != snapshot_hash:
                raise ValueError('outcome snapshot linkage failed')
            if outcome.get('verified') is not True:
                raise ValueError('outcome is not verified')
            label = outcome.get('outcome')
            if label not in ('won', 'lost'):
                raise ValueError('outcome is not won/lost')
            submitted, observed = _date(submission['submitted_at']), _date(outcome['observed_at'])
            if observed <= submitted:
                raise ValueError('outcome must be observed after submission')
            if not outcome.get('evidence_reference'):
                raise ValueError('verified outcome requires evidence_reference')
            row = {'tender_id':folder.name,'outcome':label,'observed_at':observed.isoformat(),
                   'submission_hash':snapshot_hash,'outcome_revision':outcome.get('revision'),
                   'submitted_at':submitted.isoformat(),'evidence_reference':outcome['evidence_reference'],
                   'submission_sha256':submission_digest, 'outcome_sha256':outcome_digest}
            completed.append(row)
            try:
                if submission.get('training_eligible') is not True or _date(submission['captured_at']) >= observed:
                    raise ValueError('retrospective snapshot excluded from forecast-quality monitoring')
                probability = _frozen_probability(submission)
                if probability is not None:
                    predictions.append(dict(row,probability=probability,y=int(label=='won'),error=probability-int(label=='won'),
                        prediction_model=(submission.get('prediction') or {}).get('model'),
                        interpretation='Diagnostic frozen forecast; heuristic probabilities are not calibrated model output.'))
            except (ValueError,TypeError,KeyError) as exc:
                rejected.append({'tender_id':folder.name,'scope':'prediction','reason':str(exc)})
            own_price = submission.get('bid_amount_chf')
            if isinstance(own_price,(int,float)) and not isinstance(own_price,bool) and math.isfinite(own_price) and own_price > 0:
                for competitor in outcome.get('competitors',[]):
                    name, price = str(competitor.get('name','')).strip(), competitor.get('price_chf')
                    if not name or competitor.get('currency','CHF') != 'CHF' or competitor.get('comparable') is not True:
                        continue
                    if not isinstance(price,(int,float)) or isinstance(price,bool) or not math.isfinite(price) or price <= 0:
                        continue
                    stats = competitors.setdefault(name, {'observations':[], 'observed_award_wins':0})
                    if outcome.get('winner') == name:
                        stats['observed_award_wins'] += 1
                    stats['observations'].append({'tender_id':folder.name,'observed_at':observed.isoformat(),
                        'evidence_reference':outcome['evidence_reference'],'delta_pct':100*(own_price/price-1)})
        except (ValueError, KeyError, TypeError, OSError) as exc:
            rejected.append({'tender_id':folder.name,'scope':'record','reason':str(exc)})
    predictions.sort(key=lambda r:(_date(r['observed_at']),r['tender_id']))
    higher, lower = PageHinkley(), PageHinkley()
    alerts = []
    for row in predictions:
        increasing = higher.update(row['error'])
        decreasing = lower.update(-row['error'])
        if increasing or decreasing:
            alerts.append({'tender_id':row['tender_id'],'observed_at':row['observed_at'],
                'direction':'overprediction' if increasing else 'underprediction',
                'recommendation':'Review retraining or rollback; no automatic changes.'})
    for stats in competitors.values():
        stats.update(samples=len(stats['observations']),median_delta_pct=median(r['delta_pct'] for r in stats['observations']),
            interpretation='Observed comparable total-price gaps; no causal explanation or position-level inference.')
    n = len(predictions)
    bins = []
    for start in range(10):
        entries = [r for r in predictions if min(9,int(r['probability']*10))==start]
        if entries:
            bins.append({'lower':start/10,'upper':(start+1)/10,'samples':len(entries),
                         'mean_prediction':sum(r['probability'] for r in entries)/len(entries),
                         'observed_win_rate':sum(r['y'] for r in entries)/len(entries)})
    return {'schema_version':1,'completed_count':len(completed),'wins':sum(r['outcome']=='won' for r in completed),
            'losses':sum(r['outcome']=='lost' for r in completed),'prediction_count':n,
            'brier_score':sum(r['error']**2 for r in predictions)/n if n else None,
            'calibration_bias':sum(r['error'] for r in predictions)/n if n else None,
            'calibration_bins':bins,'predictions':predictions,'completed':completed,'rejected':rejected,
            'competitors':competitors,'drift':{'minimum_instances':10,'threshold':8,'delta':.005,'alpha':.9999,
                'method':'two-sided via positive Page-Hinkley instances on signed error and its negative',
                'alerts':alerts,'alert':bool(alerts),'overprediction_statistic':higher.cumulative,
                'underprediction_statistic':lower.cumulative},'automatic_model_changes':False}


def evaluate_candidate(records, minimum_samples=10, margin=.02):
    """Rows are paired, held-out predictions with explicit provenance, not training labels.

    Each row: tender_id (or bid_id), submitted_at, observed_at, outcome,
    champion_probability, candidate_probability, prediction_provenance={source,
    verified:true, model_id, generated_at, evaluation_mode:'prospective'|'historical_backtest'}.
    Historical backtests require training_cutoff and trained_project_ids (even empty).
    Optional trained_project_ids always excludes matching tender/project ids.
    """
    if not isinstance(records,list) or isinstance(minimum_samples,bool) or minimum_samples < 10:
        raise ValueError('records must be a list and minimum_samples at least 10')
    if not isinstance(margin,(int,float)) or isinstance(margin,bool) or not math.isfinite(margin) or margin < 0:
        raise ValueError('margin must be nonnegative and finite')
    paired, rejected, seen, model_ids = [], [], set(), set()
    evaluation_ids = {str(r.get('bid_id') or r.get('tender_id') or '') for r in records if isinstance(r,dict)}
    evaluation_ids.update(str(r['project_id']) for r in records if isinstance(r,dict) and r.get('project_id'))
    for index, record in enumerate(records):
        try:
            if not isinstance(record,dict): raise ValueError('record must be object')
            key = str(record.get('bid_id') or record.get('tender_id') or '').strip()
            if not key or key in seen: raise ValueError('missing or duplicate bid/tender id')
            seen.add(key)
            submitted = _date(record.get('submitted_at') or record.get('bid_submitted_at'))
            observed = _date(record.get('observed_at') or record.get('outcome_observed_at'))
            if observed <= submitted: raise ValueError('invalid submission/outcome chronology')
            if record.get('outcome') not in ('won','lost'): raise ValueError('outcome must be won/lost')
            if record.get('outcome_verified') is not True or not record.get('evidence_reference'):
                raise ValueError('verified outcome and evidence_reference required')
            champion, candidate = _probability(record.get('champion_probability')), _probability(record.get('candidate_probability'))
            provenance = record.get('prediction_provenance')
            if not isinstance(provenance,dict) or provenance.get('verified') is not True or not provenance.get('model_id') or not provenance.get('source'):
                raise ValueError('explicit verified prediction provenance required')
            generated = _date(provenance['generated_at'])
            if generated > datetime.now(timezone.utc)+timedelta(minutes=5):
                raise ValueError('prediction generation cannot be in the future')
            mode = provenance.get('evaluation_mode','prospective')
            trained = record.get('trained_project_ids',provenance.get('trained_project_ids'))
            if trained is not None and (not isinstance(trained,list) or any(not isinstance(t,str) for t in trained) or evaluation_ids.intersection(trained)):
                raise ValueError('evaluation project overlaps training or trained_project_ids invalid')
            if mode == 'historical_backtest':
                if trained is None or _date(provenance['training_cutoff']) >= submitted or _date(provenance['training_cutoff']) > generated:
                    raise ValueError('historical backtest requires held-out ids and training cutoff before submission')
            elif mode == 'prospective':
                if generated > submitted: raise ValueError('prospective predictions must be generated by submission')
            else: raise ValueError('unsupported evaluation mode')
            model_ids.add(str(provenance['model_id']))
            y = int(record['outcome']=='won')
            paired.append({'tender_id':key,'outcome':record['outcome'],'submitted_at':submitted.isoformat(),
                'observed_at':observed.isoformat(),'champion_probability':champion,'candidate_probability':candidate,
                'champion_brier':(champion-y)**2,'candidate_brier':(candidate-y)**2,'prediction_provenance':provenance})
        except (ValueError,KeyError,TypeError) as exc:
            rejected.append({'record_index':index,'reason':str(exc)})
    paired.sort(key=lambda r:(_date(r['observed_at']),r['tender_id']))
    blockers=[]
    if rejected: blockers.append('Invalid or unverifiable records must be resolved before candidate review.')
    if len(paired)<minimum_samples: blockers.append(f'At least {minimum_samples} valid paired held-out outcomes required.')
    if {r['outcome'] for r in paired}!={'won','lost'}: blockers.append('Both won and lost outcomes required.')
    if len(model_ids)>1: blockers.append('Candidate predictions must use one model identifier.')
    n=len(paired)
    champion=sum(r['champion_brier'] for r in paired)/n if n else None
    candidate=sum(r['candidate_brier'] for r in paired)/n if n else None
    difference=candidate-champion if n else None
    noninferior=not blockers and difference <= margin
    return {'schema_version':1,'status':'blocked' if blockers else 'evaluated','samples':n,'blockers':blockers,
        'rejected':rejected,'paired_records':paired,'champion_brier':champion,'candidate_brier':candidate,
        'brier_difference':difference,'noninferiority_margin':margin,'noninferior':noninferior,
        'recommendation':'Eligible for human review; sample mean meets noninferiority margin.' if noninferior else
                         'Resolve evaluation blockers.' if blockers else 'Retain champion; candidate exceeds permitted Brier regression.',
        'interpretation':'Descriptive paired sample means; no statistical significance or causal guarantee.',
        'automatic_model_changes':False,'promotion_performed':False}
