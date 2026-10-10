#!/usr/bin/env python3
"""Validate output/calc.json against materials/expected_output_example.json.

Compares every field the golden example contains (extra fields we add, like
labour_role, are ignored) and exits 1 listing all differences, so it works
as a regression check after any change to the step scripts or data.

recommended_bid_range is the stretch goal (see _3_Prediction) and is not
produced or checked here.
"""
import json
import sys

from common import CALC_JSON, EXPECTED_JSON

TOL = 0.011  # golden values are rounded to 2 decimals


def eq(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= TOL
    return a == b


def main():
    if not CALC_JSON.exists():
        sys.exit(f"FAIL: {CALC_JSON} not found - run step1..step4 first")
    if not EXPECTED_JSON.exists():
        sys.exit(f"FAIL: golden example not found at {EXPECTED_JSON} "
                 f"(validate.py must run inside the repository)")
    calc = json.loads(CALC_JSON.read_text())
    golden = json.loads(EXPECTED_JSON.read_text())
    errors = []

    calc_positions = {p["lv_id"]: p for p in calc["position_results"]}
    golden_positions = golden["position_results"]
    for gp in golden_positions:
        cp = calc_positions.get(gp["lv_id"])
        if cp is None:
            errors.append(f"{gp['lv_id']}: missing from calc.json")
            continue
        for key, gv in gp.items():
            if not eq(cp.get(key), gv):
                errors.append(f"{gp['lv_id']}.{key}: calc={cp.get(key)!r} golden={gv!r}")
    for lv_id in sorted(set(calc_positions) - {p["lv_id"] for p in golden_positions}):
        errors.append(f"{lv_id}: extra position not present in golden example")

    for key, gv in golden["example_subset_summary"].items():
        cv = calc.get("example_subset_summary", {}).get(key)
        if not eq(cv, gv):
            errors.append(f"example_subset_summary.{key}: calc={cv!r} golden={gv!r}")

    if errors:
        print(f"FAIL: {len(errors)} difference(s) vs golden example")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)
    print(f"OK: {len(golden_positions)} positions and the subset summary match the golden example")


if __name__ == "__main__":
    main()
