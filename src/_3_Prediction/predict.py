#!/usr/bin/env python3
"""Deterministic bid scenarios. These estimates are NOT trained/calibrated probabilities."""
import argparse
import json
import os
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODEL = {"task": "win_ratio", "kind": "heuristic", "version": "heuristic-v1",
         "calibrated": False, "trained": False,
         "warning": "Illustrative parameter-based estimates; no trained LoRA or empirical calibration.",
         "band_semantics": "Sensitivity +/-5 percentage points; not confidence intervals."}


def number(value, name):
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


def money(value):
    return float(value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def predict(calc, params, baseline=None):
    cfg = params.get('stretch_bid_optimization', {})
    if not cfg.get('enabled', False):
        return {"model": dict(MODEL, kind="disabled"), "scenarios": [], "curve": []}
    cost = number(baseline if baseline is not None else calc['project_cost']['cost_baseline_chf'], 'baseline')
    if cost <= 0:
        raise ValueError('baseline must be positive')
    target = number(params['commercial']['target_margin_pct'], 'target margin')
    if not 0 <= target < 100:
        raise ValueError('target margin must be in [0,100)')
    rounding = number(params['commercial'].get('round_to_chf', 1000), 'round_to_chf')
    if rounding <= 0:
        raise ValueError('round_to_chf must be positive')
    reference_price = cost / (1 - target / 100)
    ref = number(cfg.get('reference_win_probability', .55), 'reference probability')
    sensitivity = number(cfg.get('price_sensitivity_probability_points_per_1pct_price', .05), 'price sensitivity')
    low = number(cfg.get('minimum_probability', .05), 'minimum probability')
    high = number(cfg.get('maximum_probability', .95), 'maximum probability')
    if not 0 <= low <= high <= 1 or not 0 <= ref <= 1 or sensitivity < 0:
        raise ValueError('invalid probability bounds/reference/sensitivity')
    adjustment = number(cfg.get('strategic_appetite_adjustment', 0), 'appetite') + number(cfg.get('competition_adjustment', 0), 'competition')

    def point(margin):
        m = number(margin, 'margin')
        if not 0 <= m < 100:
            raise ValueError('margin must be in [0,100)')
        bid = (cost / (1 - m / 100) / rounding).to_integral_value(rounding=ROUND_CEILING) * rounding
        probability = min(high, max(low, ref + adjustment - sensitivity * (bid / reference_price - 1) * 100))
        return {"margin_pct": float(m), "bid_price_chf": money(bid),
                "estimated_win_probability": float(probability.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)),
                "expected_contribution_chf": money(probability * (bid - cost)),
                "p_win": {"min": float(max(low, probability - Decimal('.05'))),
                          "mid": float(probability), "max": float(min(high, probability + Decimal('.05')))}}

    scenarios = [dict(point(margin), scenario=name) for name, margin in cfg.get('scenario_margins_pct', {}).items()]
    return {"model": MODEL.copy(), "cost_baseline_chf": money(cost),
            "reference_price_chf": money(reference_price), "scenarios": scenarios,
            "curve": [point(Decimal(i) / 2) for i in range(31)],
            "selection_logic": "Compare bid price, margin, estimated win probability and expected contribution."}


def enrich(calc, params):
    calc['recommended_bid_range'] = predict(calc, params)
    return calc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--calc', type=Path, default=Path(os.environ.get('AUTOTENDER_CALC_OUT', ROOT.parent / '_2_Calculator/output/calc.json')))
    parser.add_argument('--params', type=Path, default=ROOT.parent / '_2_Calculator/data/project_parameters.json')
    args = parser.parse_args()
    result = enrich(json.loads(args.calc.read_text()), json.loads(args.params.read_text()))
    args.calc.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result['recommended_bid_range']))


if __name__ == '__main__':
    main()
