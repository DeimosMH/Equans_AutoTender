#!/usr/bin/env python3
"""Golden arithmetic regression and heuristic safety/monotonicity checks."""
import json
from pathlib import Path
from predict import predict

ROOT = Path(__file__).resolve().parents[2]
params = json.loads((ROOT / 'materials/project_parameters.json').read_text())
golden = json.loads((ROOT / 'materials/expected_output_example.json').read_text())
result = predict({'project_cost': {'cost_baseline_chf': 414489.12}}, params)
for actual, expected in zip(result['scenarios'], golden['recommended_bid_range']['scenarios']):
    for key, value in expected.items():
        assert actual[key] == value, (key, actual[key], value)
assert result['model']['calibrated'] is False
assert result['model']['trained'] is False
curve = result['curve']
assert all(a['p_win']['mid'] >= b['p_win']['mid'] for a, b in zip(curve, curve[1:]))
assert all(0 <= p['p_win']['min'] <= p['p_win']['mid'] <= p['p_win']['max'] <= 1 for p in curve)
for bad in [0, -1, 'nan', 'Infinity']:
    try:
        predict({}, params, bad)
    except ValueError:
        pass
    else:
        raise AssertionError(f'invalid baseline accepted: {bad}')
assert predict({}, {'stretch_bid_optimization': {'enabled': False}})['curve'] == []
print('PASS: golden scenario arithmetic, monotonicity, sensitivity bounds, invalid input and disabled mode')
