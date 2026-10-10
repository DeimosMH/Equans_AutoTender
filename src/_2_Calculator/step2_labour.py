#!/usr/bin/env python3
"""Step 2 - installation hours and labour cost per position (todo item 2).

hours       = quantity x base hours per unit x project factors
labour cost = hours x hourly rate

Labour cost is computed from the UNROUNDED hours (the golden example stores
4.35 h but 417.30 CHF = 4.346875 h x 96); only the stored hours value is
rounded for display. Adds adjusted_install_hours, labour_role,
hourly_rate_chf and labour_cost_chf to each position in output/calc.json.

The AUTOTENDER_FACTORS env var (JSON, set by the web UI from its settings -
manual values or AI suggestions) overrides the productivity factors of
project_parameters.json.
"""
import json
import os

from common import combined_factor, D, load_calc, load_params, load_productivity, r2, save_calc


def main():
    params = load_params()
    rules = load_productivity()
    calc = load_calc()
    override = json.loads(os.environ.get("AUTOTENDER_FACTORS") or "{}")
    factors = {**params["productivity_factors"], **override}

    for pos in calc["position_results"]:
        rule = rules[pos["install_code"]]
        factor = combined_factor(rule["factor_keys"], factors)
        hours = D(pos["quantity"]) * D(rule["base_hours_per_unit"]) * factor
        rate = D(rule["default_hourly_rate_chf"])
        pos["adjusted_install_hours"] = r2(hours)
        pos["labour_role"] = rule["labour_role"]
        pos["hourly_rate_chf"] = float(rate)
        pos["labour_cost_chf"] = r2(hours * rate)

    save_calc(calc)
    total = sum(D(p["labour_cost_chf"]) for p in calc["position_results"])
    print(f"step2 labour: {len(calc['position_results'])} positions, labour total {total} CHF")


if __name__ == "__main__":
    main()
