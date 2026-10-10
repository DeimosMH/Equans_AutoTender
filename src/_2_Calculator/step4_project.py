#!/usr/bin/env python3
"""Step 4 - project-level totals (todo item 4).

Adds two blocks to output/calc.json:

example_subset_summary - field names and numbers of the golden example, so
    validate.py can check them 1:1. cost_baseline here is
    direct x (1 + transport %) x (1 + overhead %), which is what reproduces
    materials/expected_output_example.json (372700.12 -> 414489.12).

project_cost - todo item 4: item costs summed, one-off services and
allowances added once, then overhead. Allowance bases are our reading of
materials/README.md: small material on total material, supplier contingency
on supplier-package material only, transport/equipment on direct cost.
"""
from common import D, load_calc, load_params, r2, save_calc


def main():
    params = load_params()
    allowances = params["allowances"]
    commercial = params["commercial"]
    services_cfg = params["project_costs"]
    calc = load_calc()

    material = sum(D(p["material_cost_chf"]) for p in calc["position_results"])
    labour = sum(D(p["labour_cost_chf"]) for p in calc["position_results"])
    direct = material + labour
    supplier_material = sum(
        D(p["material_cost_chf"]) for p in calc["position_results"]
        if p["price_source"] == "supplier_package"
    )
    transport_pct = D(allowances["transport_equipment_pct"]) / 100
    overhead_pct = D(commercial["overhead_pct"]) / 100
    margin_pct = D(commercial["target_margin_pct"]) / 100

    calc["example_subset_summary"] = {
        "material_cost_chf": r2(material),
        "labour_cost_chf": r2(labour),
        "direct_cost_chf": r2(direct),
        "cost_baseline_chf": r2(direct * (1 + transport_pct) * (1 + overhead_pct)),
    }

    services = {
        "engineering_chf": r2(D(services_cfg["engineering_hours"]) * D(services_cfg["engineering_rate_chf_per_h"])),
        "commissioning_chf": r2(D(services_cfg["commissioning_hours"]) * D(services_cfg["commissioning_rate_chf_per_h"])),
        "hygiene_inspection_chf": float(D(services_cfg["hygiene_inspection_chf"])),
        "documentation_chf": float(D(services_cfg["documentation_chf"])),
    }
    services_total = sum(D(v) for v in services.values())

    allowance_lines = {
        "small_material_chf": r2(material * D(allowances["small_material_pct"]) / 100),
        "supplier_package_contingency_chf": r2(supplier_material * D(allowances["supplier_package_contingency_pct"]) / 100),
        "transport_equipment_chf": r2(direct * transport_pct),
    }
    allowances_total = sum(D(v) for v in allowance_lines.values())

    project_direct = direct + services_total + allowances_total
    calc["project_cost"] = {
        "scope_note": (
            "positions + one-off services and allowances + overhead; the "
            "example_subset_summary above mirrors the golden subset and "
            "deliberately excludes services"
        ),
        "positions_direct_cost_chf": r2(direct),
        "services_chf": {**services, "total_chf": r2(services_total)},
        "allowances_chf": {**allowance_lines, "total_chf": r2(allowances_total)},
        "project_direct_cost_chf": r2(project_direct),
        "overhead_chf": r2(project_direct * overhead_pct),
        "cost_baseline_chf": r2(project_direct * (1 + overhead_pct)),
        "indicative_selling_price_chf": r2(project_direct * (1 + overhead_pct) / (1 - margin_pct)),
    }

    save_calc(calc)
    print(f"step4 project: subset baseline {calc['example_subset_summary']['cost_baseline_chf']} CHF, "
          f"project baseline {calc['project_cost']['cost_baseline_chf']} CHF")


if __name__ == "__main__":
    main()
