#!/usr/bin/env python3
"""Step 1 - material cost per LV position (todo item 1).

material_cost = quantity x net unit cost x (1 + material waste %)

Rebuilds position_results in output/calc.json from input/example_lv_positions.csv:
ids, matched product, pricing basis, material cost, review flags and status.
Replaces any previous position_results, so run this first, then steps 2-4.
"""
from common import (
    BASE,
    D,
    MATCH_CONFIDENCE,
    load_catalog,
    load_params,
    load_positions,
    load_settings,
    r2,
    resolve_positions_file,
    save_calc,
)


def main():
    settings = load_settings()
    params = load_params(settings)
    catalog = load_catalog(settings)
    positions_file = resolve_positions_file(settings)
    waste = D(params["allowances"]["material_waste_pct"]) / 100

    results = []
    for row in load_positions(positions_file):
        product = catalog[row["suggested_product_id"]]
        qty = D(row["quantity"])
        net = D(product["net_cost_chf"])
        review = product["supplier_quote_required"].strip().lower() == "true"
        results.append({
            "lv_id": row["lv_id"],
            "source_page": int(row["source_page"]),
            "matched_product_id": product["product_id"],
            "install_code": product["install_code"],
            "quantity": float(qty),
            "unit": row["unit"],
            "net_unit_cost_chf": float(net),
            "material_cost_chf": r2(qty * net * (1 + waste)),
            "price_source": product["source_type"],
            "match_confidence": MATCH_CONFIDENCE[product["source_type"]],
            "review_required": review,
            "status": "supplier_quote_required" if review else "calculated",
        })

    save_calc({
        "schema_version": params["schema_version"],
        "project": params["project"],
        "input": {
            "mode": settings["mode"],
            "positions_file": str(positions_file.relative_to(BASE))
            if positions_file.is_relative_to(BASE) else str(positions_file),
        },
        "position_results": results,
    })
    total = sum(D(p["material_cost_chf"]) for p in results)
    print(f"step1 material: {len(results)} positions, material total {total} CHF")


if __name__ == "__main__":
    main()
