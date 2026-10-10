#!/usr/bin/env python3
"""Step 3 - combine material and labour into per-position results (todo item 3).

Adds direct_position_cost_chf = material + labour and re-orders each position
dict to the field order of materials/expected_output_example.json so
output/calc.json reads like the golden example (extra fields we add, e.g.
labour_role, are appended after the golden fields).
"""
from common import D, load_calc, r2, save_calc

GOLDEN_FIELD_ORDER = [
    "lv_id", "source_page", "matched_product_id", "install_code", "quantity",
    "unit", "net_unit_cost_chf", "material_cost_chf", "adjusted_install_hours",
    "labour_cost_chf", "direct_position_cost_chf", "price_source",
    "match_confidence", "review_required", "status",
]


def main():
    calc = load_calc()
    ordered = []
    for pos in calc["position_results"]:
        pos["direct_position_cost_chf"] = r2(
            D(pos["material_cost_chf"]) + D(pos["labour_cost_chf"])
        )
        extras = [k for k in pos if k not in GOLDEN_FIELD_ORDER]
        ordered.append({k: pos[k] for k in GOLDEN_FIELD_ORDER} | {k: pos[k] for k in extras})
    calc["position_results"] = ordered

    save_calc(calc)
    total = sum(D(p["direct_position_cost_chf"]) for p in ordered)
    print(f"step3 combine: {len(ordered)} positions, direct total {total} CHF")


if __name__ == "__main__":
    main()
