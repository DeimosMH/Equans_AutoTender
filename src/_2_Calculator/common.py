"""Shared helpers for the _2_Calculator step scripts.

Requires pyyaml for settings.yaml (the only non-stdlib dependency).
"""
import csv
import json
import os
import sys
from decimal import Decimal, ROUND_HALF_UP, getcontext
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

# 34 digits keeps every terminating factor product in this dataset exact
getcontext().prec = 34

BASE = Path(__file__).resolve().parent
OUTPUT = BASE / "output"
# the web UI runs the steps per tender and redirects the result via this env var
CALC_JSON = (Path(os.environ["AUTOTENDER_CALC_OUT"])
             if os.environ.get("AUTOTENDER_CALC_OUT") else OUTPUT / "calc.json")
SETTINGS_YAML = BASE / "settings.yaml"
EXPECTED_JSON = BASE.parent.parent / "materials" / "expected_output_example.json"

# golden example assigns match confidence purely by price source; reuse until
# _1_AI_InputProcessing provides a real matcher score
MATCH_CONFIDENCE = {"catalog": 0.92, "supplier_package": 0.72}


def D(x) -> Decimal:
    return Decimal(str(x))


def r2(x: Decimal) -> float:
    """Round to 2 decimals, half-up (matches the golden example: 11.235 -> 11.24)."""
    return float(x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def load_settings() -> dict:
    if yaml is None:
        sys.exit("settings.yaml needs pyyaml: python3 -m pip install --user pyyaml")
    if not SETTINGS_YAML.exists():
        sys.exit(f"settings file not found: {SETTINGS_YAML}")
    settings = yaml.safe_load(SETTINGS_YAML.read_text())
    settings.setdefault("mode", "dev")
    return settings


def resolve_positions_file(settings: dict | None = None) -> Path:
    """Positions csv: the dev file from settings, or the newest match in prod."""
    settings = settings or load_settings()
    if settings["mode"] != "prod":
        return BASE / settings["files"]["positions"]
    directory = (BASE / settings["prod"]["positions_dir"]).resolve()
    pattern = settings["prod"]["positions_pattern"]
    candidates = sorted(directory.glob(pattern))
    if not candidates:
        sys.exit(f"prod mode: no {pattern!r} found in {directory} - "
                 f"run _1_AI_InputProcessing first or adjust settings.yaml")
    # newest by mtime, name as tie-break so runs are deterministic
    return max(candidates, key=lambda p: (p.stat().st_mtime, p.name))


def _file_setting(settings: dict, key: str) -> Path:
    return BASE / settings["files"][key]


def _read_csv(path: Path) -> list:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def load_params(settings: dict | None = None) -> dict:
    settings = settings or load_settings()
    return json.loads(_file_setting(settings, "parameters").read_text())


def load_productivity(settings: dict | None = None) -> dict:
    settings = settings or load_settings()
    return {row["install_code"]: row
            for row in _read_csv(_file_setting(settings, "productivity"))}


def load_catalog(settings: dict | None = None) -> dict:
    settings = settings or load_settings()
    return {row["product_id"]: row
            for row in _read_csv(_file_setting(settings, "catalog"))}


def load_positions(path: Path | None = None) -> list:
    return _read_csv(path or resolve_positions_file())


def load_calc() -> dict:
    return json.loads(CALC_JSON.read_text())


def save_calc(calc: dict) -> None:
    OUTPUT.mkdir(exist_ok=True)
    CALC_JSON.write_text(json.dumps(calc, indent=2) + "\n")


def combined_factor(factor_keys: str, factors: dict) -> Decimal:
    """Product of the project factors for a rule; site_efficiency enters as 1/value.

    Direct factors are multiplied first and site_efficiency divides last, so
    terminating products (e.g. 1.1*1.07/0.88 = 1.3375) stay exact and the
    half-up rounding of hours hits the true value (11.235 h -> 11.24).
    """
    keys = [k for k in factor_keys.split("|") if k]
    f = Decimal(1)
    for k in keys:
        if k != "site_efficiency":
            f *= D(factors[k])
    if "site_efficiency" in keys:
        f /= D(factors["site_efficiency"])
    return f
