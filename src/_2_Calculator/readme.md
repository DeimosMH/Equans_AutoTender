# _2_Calculator

Turns matched LV positions into costs: material and labour per position, direct
position cost, and project-level totals. Sits between `_1_AI_InputProcessing`
(which will produce the real tender positions and product matches) and
`_3_Prediction` (bid optimization). Stdlib plus pyyaml (for `settings.yaml`):
`python3 -m pip install --user pyyaml`.

## Settings - dev vs prod input

`settings.yaml` controls where input data comes from:

- `mode: dev` (default) - the checked-in example files listed under `files:`.
- `mode: prod` - the positions csv is the **newest** file (by mtime) matching
  `positions_pattern` in `positions_dir`, i.e. the latest output of
  `_1_AI_InputProcessing`. Catalog, productivity and parameters still come
  from `files:` - they are stable reference data, not per-tender output.
  The prod location is a guess based on the `_1` todo; adjust it in
  `settings.yaml` once that module's real output layout exists.

Step 1 records what it used in `calc.json` under `input` (`mode` +
`positions_file`) so every result is traceable to its source file.

## Inputs and output

| Path | Content |
|---|---|
| `settings.yaml` | input mode + file locations (see above) |
| `input/example_lv_positions.csv` | LV positions with `suggested_product_id` (today the verified 22-position example; in prod mode replaced by the newest `_1_AI_InputProcessing` output) |
| `input/catalog.csv` | products/supplier packages: `net_cost_chf`, `install_code`, `source_type`, `supplier_quote_required` |
| `data/productivity.csv` | install rules: `base_hours_per_unit`, `labour_role`, `default_hourly_rate_chf`, `factor_keys` |
| `data/project_parameters.json` | project factors, allowances, services, overhead/margin |
| `output/calc.json` | all results (the file everything below writes into) |

`data/` and `input/` are working copies of `materials/` and stay in sync with it.

## Scripts - one per todo item, run in order

```sh
cd src/_2_Calculator
python3 step1_material.py   # todo 1: material cost per item
python3 step2_labour.py     # todo 2: hours, role, rate, labour cost per item
python3 step3_combine.py    # todo 3: direct cost per item + golden field order
python3 step4_project.py    # todo 4: summaries, services and allowances once
python3 validate.py         # checks calc.json against materials/expected_output_example.json
```

Each step reads `output/calc.json`, adds its fields and writes it back, so the
file grows step by step. Step 1 rebuilds `position_results` from the input CSV,
so it must run before 2-4. The scripts resolve paths relative to their own
location (`common.BASE`) and can be started from any working directory.

`common.py` holds the shared loaders and the rounding helper; nothing else is shared.

## How the calculation works

All money is `Decimal`, rounded half-up to 2 decimals (the golden example rounds
`11.235 h -> 11.24`, which Python's float `round()` gets wrong).

**1. Material** (`step1_material.py`), per position:

```
material_cost_chf = quantity x net_cost_chf x (1 + material_waste_pct / 100)
```

The position's `suggested_product_id` is looked up in the catalog; the catalog
also decides the review flags:

- `price_source` = catalog `source_type`
- `match_confidence` = 0.92 (catalog) / 0.72 (supplier_package) - the heuristic
  the golden example uses, until `_1_AI_InputProcessing` provides real match scores
- `review_required` = catalog `supplier_quote_required`; if true, `status` is
  `supplier_quote_required`, otherwise `calculated`

**2. Labour** (`step2_labour.py`), per position, driven by the `install_code`
of the matched product:

```
factor        = product of factor_keys values, with site_efficiency as 1/value
hours         = quantity x base_hours_per_unit x factor
labour_cost   = hours x hourly_rate     # uses UNROUNDED hours
```

`adjusted_install_hours` is stored rounded to 2 decimals for display, but
`labour_cost_chf` is computed from the unrounded hours - the golden example
stores `4.35 h` with `417.30 CHF = 4.346875 h x 96`. Example factor for
`DIFFUSER` (`site_efficiency|mounting_height_school|school_logistics`):
`1.1 x 1.07 / 0.88 = 1.3375`, so LV0001 = `5 x 0.65 x 1.3375 = 4.346875 h`.

**3. Combine** (`step3_combine.py`): `direct_position_cost_chf = material +
labour`, and positions are re-ordered to the field order of the golden example.

**4. Project** (`step4_project.py`) writes two blocks:

- `example_subset_summary` - same fields and numbers as the golden example:
  `cost_baseline_chf = direct x (1 + transport_equipment_pct) x (1 + overhead_pct)`
  (i.e. `372700.12 x 1.025 x 1.085 = 414489.12`). It contains no services
  because the golden subset covers positions only.
- `project_cost` - todo item 4: position direct costs plus one-off services
  (engineering, commissioning, hygiene inspection, documentation from
  `project_costs`) and allowances (small material on total material, supplier
  contingency on supplier-package material only, transport on direct cost),
  then `overhead_pct` and an indicative selling price at `target_margin_pct`.
  Allowance bases are our reading of `materials/README.md`; adjust in
  `step4_project.py` if the tender team prefers other bases.

## Adding a new item

In dev mode: add a row to `input/example_lv_positions.csv` (with a
`suggested_product_id` that exists in `input/catalog.csv`) and rerun
step1-step4. The new position is calculated like any other; `validate.py`
will report it as an extra position, because it pins the 22 example rows to
the golden output. In prod mode the same happens automatically whenever
`_1_AI_InputProcessing` drops a newer positions file.

## Validation

`validate.py` compares every field of every golden position plus the subset
summary (tolerance 0.01) and exits non-zero listing all differences - use it
as a regression check after touching scripts or data. Current state:
**22/22 positions and the subset summary match** `materials/expected_output_example.json`.

Not implemented here: `recommended_bid_range` (the Aggressive/Target/Conservative
scenarios) - that is the stretch goal owned by `_3_Prediction`.
