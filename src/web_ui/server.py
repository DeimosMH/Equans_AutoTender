#!/usr/bin/env python3
"""Web UI for the AutoTender calculator (stdlib only).

Multi-tender workflow: each tender lives in tenders/<id>/ (meta.json, the
uploaded positions csv and its own calc.json produced by the _2_Calculator
steps - redirected there via the AUTOTENDER_CALC_OUT env var). The live
scenario recalculation (margin slider, overhead/waste inputs, inline value
edits) runs in the browser; "Save changes" persists manual position edits
and recomputes server-side with the calculator's own Decimal logic.

Run: python3 server.py [port]    -> http://127.0.0.1:<port>   (default 8080)
"""
import csv
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

BASE = Path(__file__).resolve().parent
CALC_DIR = BASE.parent / "_2_Calculator"
TENDERS = BASE / "tenders"
UPLOADS = BASE / "uploads"
UI_SETTINGS = BASE / "ui_settings.json"
INDEX = BASE / "static" / "index.html"

# reuse the calculator's loaders/rounding so paths and maths stay in one place
_spec = importlib.util.spec_from_file_location("calc_common", CALC_DIR / "common.py")
calc_common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(calc_common)
D, r2 = calc_common.D, calc_common.r2

REQUIRED_CSV_COLUMNS = ["lv_id", "source_page", "quantity", "unit", "suggested_product_id"]
EDITABLE_FIELDS = ("quantity", "net_unit_cost_chf", "labour_cost_chf")


# ---------------------------------------------------------------- tender store

def tid_valid(tid: str) -> bool:
    return bool(re.fullmatch(r"t[0-9a-z_]+", tid or ""))


def meta_path(tid: str) -> Path:
    return TENDERS / tid / "meta.json"


def calc_path(tid: str) -> Path:
    return TENDERS / tid / "calc.json"


def positions_path(tid: str) -> Path:
    return TENDERS / tid / "positions.csv"


def load_meta(tid: str) -> dict:
    return json.loads(meta_path(tid).read_text())


def save_meta(meta: dict) -> None:
    meta_path(meta["id"]).parent.mkdir(parents=True, exist_ok=True)
    meta_path(meta["id"]).write_text(json.dumps(meta, indent=2) + "\n")


def create_tender(name: str) -> dict:
    tid = time.strftime("t%Y%m%d_%H%M%S") + f"_{os.urandom(2).hex()}"
    meta = {
        "id": tid,
        "name": (name or "").strip() or f"Tender {time.strftime('%Y-%m-%d %H:%M')}",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": "new",
    }
    save_meta(meta)
    return meta


def list_tenders() -> list:
    out = []
    if TENDERS.exists():
        for d in TENDERS.iterdir():
            if tid_valid(d.name) and meta_path(d.name).exists():
                out.append(load_meta(d.name))
    out.sort(key=lambda m: m["created_at"], reverse=True)
    return out


# app settings - LoRA model selection per task (backend connects later)
TASK_KEYS = ("input_processing", "productivity_factors", "win_ratio")
BASE_MODELS = ["GLM-4.6", "GLM-4.5-Air", "Llama-3.3-70B", "Qwen3-32B"]

DEFAULT_SETTINGS = {
    "base_model": "GLM-4.6",
    "tasks": {
        "input_processing": {"versions": [{"version": "2026-09-12", "base": "GLM-4.6"}],
                             "selected": None, "links": ""},
        "productivity_factors": {"versions": [], "selected": None, "links": ""},
        "win_ratio": {"versions": [{"version": "2026-10-02", "base": "GLM-4.6"}],
                      "selected": None, "links": ""},
    },
    "advanced": {"models_dir": "/data/models", "loras_dir": "/data/loras",
                 "cache_dir": "/data/cache"},
}


def _norm_settings(data) -> dict:
    """Accept partial or legacy payloads; produce one well-formed settings dict.
    Versions trained for another base model stay stored but are not selectable
    (they would need retraining)."""
    data = data if isinstance(data, dict) else {}
    base = str(data.get("base_model") or DEFAULT_SETTINGS["base_model"]).strip()[:80]
    if base not in BASE_MODELS:
        base = DEFAULT_SETTINGS["base_model"]

    tasks_in = data.get("tasks")
    if isinstance(tasks_in, dict):
        tasks = {}
        for k in TASK_KEYS:
            t = tasks_in.get(k) or {}
            versions = [{"version": str(v.get("version", "")).strip()[:40],
                         "base": str(v.get("base") or base).strip()[:80]}
                        for v in t.get("versions") or []
                        if str(v.get("version", "")).strip()]
            selected = str(t.get("selected") or "").strip()[:40]
            if not any(v["version"] == selected and v["base"] == base for v in versions):
                selected = next((v["version"] for v in versions if v["base"] == base), "")
            tasks[k] = {"versions": versions, "selected": selected or None,
                        "links": str(t.get("links", ""))[:2000]}
    else:
        # legacy flat lora list: route entries to tasks by name heuristics
        tasks = {k: {"versions": [], "selected": None, "links": ""} for k in TASK_KEYS}
        for m in data.get("loras") or []:
            name = str(m.get("name", "")).lower()
            k = ("input_processing" if "input" in name
                 else "productivity_factors" if "prod" in name or "factor" in name
                 else "win_ratio")
            tasks[k]["versions"].append(
                {"version": time.strftime("%Y-%m-%d"),
                 "base": str(m.get("base_model") or base).strip()[:80]})
        for t in tasks.values():
            t["selected"] = next((v["version"] for v in t["versions"]
                                  if v["base"] == base), None)

    adv_in = data.get("advanced") or {}
    adv = dict(DEFAULT_SETTINGS["advanced"])
    for k in adv:
        if k in adv_in:
            adv[k] = str(adv_in[k])[:200]
    return {"base_model": base, "tasks": tasks, "advanced": adv}


def load_ui_settings() -> dict:
    data = json.loads(UI_SETTINGS.read_text()) if UI_SETTINGS.exists() else {}
    settings = _norm_settings(data)
    settings["base_models"] = BASE_MODELS  # option list for the client
    return settings


def save_ui_settings(data: dict) -> dict:
    settings = _norm_settings(data)
    # the UI never edits versions directly - keep stored ones when not sent
    if UI_SETTINGS.exists():
        old = _norm_settings(json.loads(UI_SETTINGS.read_text()))
        for k in TASK_KEYS:
            if not settings["tasks"][k]["versions"]:
                settings["tasks"][k]["versions"] = old["tasks"][k]["versions"]
            sel, base = settings["tasks"][k]["selected"], settings["base_model"]
            vers = settings["tasks"][k]["versions"]
            if not any(v["version"] == sel and v["base"] == base for v in vers):
                settings["tasks"][k]["selected"] = next(
                    (v["version"] for v in vers if v["base"] == base), None)
    UI_SETTINGS.write_text(json.dumps(settings, indent=2) + "\n")
    settings["base_models"] = BASE_MODELS
    return settings


def run_steps(calc_out: Path, scripts: list, positions_csv: Path | None = None) -> str:
    env = dict(os.environ, AUTOTENDER_CALC_OUT=str(calc_out))
    for script, extra in scripts:
        r = subprocess.run([sys.executable, script, *extra],
                           cwd=CALC_DIR, capture_output=True, text=True, env=env)
        if r.returncode != 0:
            raise RuntimeError(f"{script} failed:\n{r.stderr.strip()[-400:]}")
    return r.stdout.strip()


def calc_tender(tid: str) -> str:
    """Full pipeline (step1-4) on the tender's stored positions csv."""
    return run_steps(calc_path(tid), [
        ("step1_material.py", [str(positions_path(tid))]),
        ("step2_labour.py", []),
        ("step3_combine.py", []),
        ("step4_project.py", []),
    ])


def apply_edits(tid: str, edits: dict) -> dict:
    """Persist manual position edits, recompute with calculator maths, rebuild
    summaries via step3/step4. quantity/net recompute material (and labour by
    rules for quantity); an explicit labour_cost_chf is kept as an override
    until the next rules-based recompute."""
    meta = load_meta(tid)
    calc = json.loads(calc_path(tid).read_text())
    rules = calc_common.load_productivity()
    params = calc_common.load_params()
    factors = params["productivity_factors"]
    waste = D(params["allowances"]["material_waste_pct"]) / 100
    by_lv = {p["lv_id"]: p for p in calc["position_results"]}
    touched = 0

    for lv_id, fields in edits.items():
        pos = by_lv.get(lv_id)
        if pos is None or not fields:
            continue
        fields = {k: v for k, v in fields.items() if k in EDITABLE_FIELDS and v is not None}
        if "quantity" in fields:
            pos["quantity"] = float(D(fields["quantity"]))
        if "net_unit_cost_chf" in fields:
            pos["net_unit_cost_chf"] = float(D(fields["net_unit_cost_chf"]))
        if "quantity" in fields or "net_unit_cost_chf" in fields:
            pos["material_cost_chf"] = r2(
                D(pos["quantity"]) * D(pos["net_unit_cost_chf"]) * (1 + waste))
        if "labour_cost_chf" in fields:
            pos["labour_cost_chf"] = r2(D(fields["labour_cost_chf"]))
        elif "quantity" in fields:  # labour scales with quantity, from the rules
            rule = rules[pos["install_code"]]
            factor = calc_common.combined_factor(rule["factor_keys"], factors)
            hours = D(pos["quantity"]) * D(rule["base_hours_per_unit"]) * factor
            pos["adjusted_install_hours"] = r2(hours)
            pos["labour_cost_chf"] = r2(hours * D(rule["default_hourly_rate_chf"]))
        pos["direct_position_cost_chf"] = r2(
            D(str(pos["material_cost_chf"])) + D(str(pos["labour_cost_chf"])))
        touched += 1

    calc_path(tid).write_text(json.dumps(calc, indent=2) + "\n")
    run_steps(calc_path(tid), [("step3_combine.py", []), ("step4_project.py", [])])
    meta["status"] = "calculated"
    save_meta(meta)
    result = json.loads(calc_path(tid).read_text())
    result["_edited_positions"] = touched
    return result


# ---------------------------------------------------------------- PDF export
# Hand-rolled PDF painter (no dependencies): base-14 Helvetica fonts, filled
# rectangles, and precise left/center/right text alignment via the standard
# Adobe AFM width tables. Enough for a sleek flat-design client document.

PAGE_W, PAGE_H, MARGIN = 595.0, 842.0, 48.0
ORANGE = (0.851, 0.282, 0.059)    # #d9480f brand accent
INK = (0.122, 0.137, 0.157)       # #1f2328
MUTED = (0.42, 0.447, 0.502)      # #6b7280
CARD = (0.965, 0.969, 0.976)      # #f6f7f9
BORDER = (0.886, 0.898, 0.918)    # #e2e5ea
WHITE = (1.0, 1.0, 1.0)
CREAM = (1.0, 0.88, 0.80)         # light text on orange
GREEN = (0.216, 0.569, 0.318)
GREEN_BG = (0.914, 0.965, 0.925)
AMBER = (0.741, 0.365, 0.039)
AMBER_BG = (1.0, 0.957, 0.898)

# Adobe AFM widths (per mille) for ASCII 32..126; digits are tabular (556)
_W_REG = {" ": 278, "!": 278, '"': 355, "#": 556, "$": 556, "%": 889, "&": 667,
          "'": 191, "(": 333, ")": 333, "*": 389, "+": 584, ",": 278, "-": 333,
          ".": 278, "/": 278, "0": 556, "1": 556, "2": 556, "3": 556, "4": 556,
          "5": 556, "6": 556, "7": 556, "8": 556, "9": 556, ":": 278, ";": 278,
          "<": 584, "=": 584, ">": 584, "?": 556, "@": 1015, "A": 667, "B": 667,
          "C": 722, "D": 722, "E": 667, "F": 611, "G": 778, "H": 722, "I": 278,
          "J": 500, "K": 667, "L": 556, "M": 833, "N": 722, "O": 778, "P": 667,
          "Q": 778, "R": 722, "S": 667, "T": 611, "U": 722, "V": 667, "W": 944,
          "X": 667, "Y": 667, "Z": 611, "[": 278, "\\": 278, "]": 278, "^": 469,
          "_": 556, "`": 333, "a": 556, "b": 556, "c": 500, "d": 556, "e": 556,
          "f": 278, "g": 556, "h": 556, "i": 222, "j": 222, "k": 500, "l": 222,
          "m": 833, "n": 556, "o": 556, "p": 556, "q": 556, "r": 333, "s": 500,
          "t": 278, "u": 556, "v": 500, "w": 722, "x": 500, "y": 500, "z": 500,
          "{": 334, "|": 260, "}": 334, "~": 584}
_W_BOLD = {" ": 278, "!": 333, '"': 474, "#": 556, "$": 556, "%": 889, "&": 722,
           "'": 238, "(": 333, ")": 333, "*": 389, "+": 584, ",": 278, "-": 333,
           ".": 278, "/": 278, "0": 556, "1": 556, "2": 556, "3": 556, "4": 556,
           "5": 556, "6": 556, "7": 556, "8": 556, "9": 556, ":": 333, ";": 333,
           "<": 584, "=": 584, ">": 584, "?": 611, "@": 975, "A": 722, "B": 722,
           "C": 722, "D": 722, "E": 667, "F": 611, "G": 778, "H": 722, "I": 278,
           "J": 556, "K": 722, "L": 611, "M": 833, "N": 722, "O": 778, "P": 667,
           "Q": 778, "R": 722, "S": 667, "T": 611, "U": 722, "V": 666, "W": 944,
           "X": 667, "Y": 667, "Z": 611, "[": 333, "\\": 278, "]": 333, "^": 584,
           "_": 556, "`": 333, "a": 556, "b": 611, "c": 556, "d": 611, "e": 556,
           "f": 333, "g": 611, "h": 611, "i": 278, "j": 278, "k": 556, "l": 278,
           "m": 889, "n": 611, "o": 611, "p": 611, "q": 611, "r": 389, "s": 556,
           "t": 333, "u": 611, "v": 556, "w": 778, "x": 556, "y": 556, "z": 500,
           "{": 389, "|": 280, "}": 389, "~": 584}


def _esc(t) -> str:
    return (str(t).replace("\\", "\\\\").replace("(", "\\(")
            .replace(")", "\\)").encode("latin-1", "replace").decode("latin-1"))


def _tw(s, font, size) -> float:
    w = _W_BOLD if font == "F2" else _W_REG
    return sum(w.get(ch, 556) for ch in str(s)) * size / 1000.0


def _wrap(s, font, size, max_w) -> list:
    lines, cur = [], ""
    for word in str(s).split():
        trial = (cur + " " + word).strip()
        if cur and _tw(trial, font, size) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines or [""]


def _trunc(s, font, size, max_w) -> str:
    s = str(s)
    if _tw(s, font, size) <= max_w:
        return s
    while s and _tw(s + "...", font, size) > max_w:
        s = s[:-1]
    return s + "..."


class Page:
    """One PDF page as a list of content-stream operators."""

    def __init__(self):
        self.ops = []

    def rect(self, x, y, w, h, fill) -> None:
        self.ops.append(f"{fill[0]:.3f} {fill[1]:.3f} {fill[2]:.3f} rg "
                        f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re f")

    def text(self, x, y, s, font="F1", size=9, color=INK,
             align="left", max_w=None) -> None:
        if max_w is not None:
            s = _trunc(s, font, size, max_w)
        w = _tw(s, font, size)
        if align == "right":
            x -= w
        elif align == "center":
            x -= w / 2
        self.ops.append(f"BT /{font} {size} Tf {color[0]:.3f} {color[1]:.3f} "
                        f"{color[2]:.3f} rg 1 0 0 1 {x:.2f} {y:.2f} Tm "
                        f"({_esc(s)}) Tj ET")


def build_pdf(pages: list) -> bytes:
    """Assemble Page objects into a PDF: F1 Helvetica, F2 Helvetica-Bold,
    F3 Helvetica-Oblique, one content stream per page."""
    objs: dict[int, bytes] = {}
    page_refs = []
    next_num = 6
    for _ in pages:
        page_refs.append((next_num, next_num + 1))
        next_num += 2
    kids = " ".join(f"{n} 0 R" for n, _ in page_refs)
    objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode()
    objs[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    objs[4] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"
    objs[5] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique >>"
    for (num, cnum), page in zip(page_refs, pages):
        objs[num] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> "
            f"/Contents {cnum} 0 R >>"
        ).encode()
        stream = ("\n".join(page.ops) + "\n").encode("latin-1", "replace")
        objs[cnum] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"endstream"

    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for i in range(1, next_num):
        offsets[i] = len(out)
        out += f"{i} 0 obj\n".encode() + objs[i] + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {next_num}\n".encode() + b"0000000000 65535 f \n"
    out += b"".join(f"{offsets[i]:010d} 00000 n \n".encode() for i in range(1, next_num))
    out += (f"trailer\n<< /Size {next_num} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n").encode()
    return bytes(out)


def _offer_data(calc: dict, params: dict, waste: float, overhead: float,
                margin: float, descriptions: dict | None = None) -> dict:
    """Shared numbers + texts for all export formats (pdf/html/docx).
    Same recompute the browser does for the slider/inputs."""
    descriptions = descriptions or {}
    r2f = lambda x: round(x + 1e-9, 2)
    positions = calc["position_results"]
    material = labour = supplier_material = 0.0
    rows = []
    for p in positions:
        mat = r2f(p["quantity"] * p["net_unit_cost_chf"] * (1 + waste / 100))
        direct = r2f(mat + p["labour_cost_chf"])
        material += mat
        labour += p["labour_cost_chf"]
        if p["price_source"] == "supplier_package":
            supplier_material += mat
        rows.append((p, mat, direct,
                     descriptions.get(p["lv_id"]) or p["matched_product_id"]))
    material, labour = r2f(material), r2f(labour)
    supplier_material = r2f(supplier_material)
    direct = r2f(material + labour)
    services = calc.get("project_cost", {}).get("services_chf", {}).get("total_chf", 0.0)
    alw = params["allowances"]
    pcosts = params["project_costs"]
    pf = params["productivity_factors"]
    allowances = r2f(material * alw["small_material_pct"] / 100
                     + supplier_material * alw["supplier_package_contingency_pct"] / 100
                     + direct * alw["transport_equipment_pct"] / 100)
    baseline = r2f((direct + services + allowances) * (1 + overhead / 100))
    price = r2f(baseline / (1 - margin / 100))
    chf = lambda x: f"{x:,.2f}"
    num = lambda x: f"{x:g}"
    n = len(rows)
    review = sum(1 for p in positions if p["review_required"])
    rates = {}
    for rule in calc_common.load_productivity().values():
        if float(rule["default_hourly_rate_chf"]) > 0:
            rates[rule["labour_role"]] = rule["default_hourly_rate_chf"]
    rates_txt = ", ".join(f"{role.replace('_', ' ')} CHF {rate}/h"
                          for role, rate in sorted(rates.items()))
    src = calc.get("input", {}).get("positions_file", "").rsplit("/", 1)[-1] or "n/a"
    eff_pct = (1 / pf["site_efficiency"] - 1) * 100
    fp = lambda v: f"{(v - 1) * 100:+.0f}%"
    steps = [
        ("Every position matched and traceable",
         "Each LV position of the tender is matched to a priced catalog product or a "
         "supplier package. The tender source page is kept with every line, so any "
         "number in this document can be traced back to the original request."),
        ("Materials at net rates plus a waste allowance",
         f"Net unit costs reflect current supplier conditions; a {num(waste)}% "
         f"material-waste allowance covers cutting and handling losses. Supplier-package "
         f"items run at budget rates and are flagged for firm quotations."),
        ("Labour from measured productivity, adjusted for this building",
         f"Installation hours follow productivity rules (hours per unit per component). "
         f"For a school in operation we apply school logistics {fp(pf['school_logistics'])}, "
         f"mounting height {fp(pf['mounting_height_school'])}, timber interfaces "
         f"{fp(pf['timber_interface'])} and site efficiency {eff_pct:+.1f}%. "
         f"Hourly rates: {rates_txt}."),
        ("Project services and allowances added once",
         f"Engineering ({pcosts['engineering_hours']} h), commissioning "
         f"({pcosts['commissioning_hours']} h), hygiene inspection and documentation are "
         f"included once for the whole project. Allowances: small material "
         f"{alw['small_material_pct']}%, supplier contingency "
         f"{alw['supplier_package_contingency_pct']}%, transport and equipment "
         f"{alw['transport_equipment_pct']}%."),
        ("Overhead and the margin scenario",
         f"Company overhead of {num(overhead)}% is applied to the total cost. The margin "
         f"of {num(margin)}% is the scenario lever: the price above moves with it, so "
         f"competitiveness and contribution can be balanced deliberately."),
    ]
    return {"rows": rows, "material": material, "labour": labour, "direct": direct,
            "services": services, "allowances": allowances, "baseline": baseline,
            "price": price, "n": n, "review": review, "src": src, "steps": steps,
            "chf": chf, "num": num}


def pdf_report(calc: dict, params: dict, waste: float, overhead: float,
               margin: float, descriptions: dict | None = None) -> bytes:
    """Client-facing offer summary: branded cover with KPI cards, the big
    indicative price, a "how and why" methodology, and the position table."""
    d = _offer_data(calc, params, waste, overhead, margin, descriptions)
    (rows, material, labour, direct, services, allowances, baseline, price,
     n, review, src, steps, chf, num) = (
     d["rows"], d["material"], d["labour"], d["direct"], d["services"],
     d["allowances"], d["baseline"], d["price"], d["n"], d["review"],
     d["src"], d["steps"], d["chf"], d["num"])
    alw = params["allowances"]
    pcosts = params["project_costs"]
    pf = params["productivity_factors"]

    # ---------------------------------------------------------- cover page
    pg = Page()
    band_h = 132
    pg.rect(0, PAGE_H - band_h, PAGE_W, band_h, ORANGE)
    pg.rect(0, PAGE_H - band_h - 5, PAGE_W, 5, INK)
    pg.text(MARGIN, PAGE_H - 46, "INDICATIVE TENDER CALCULATION", "F2", 9.5, CREAM)
    title = calc["project"]["name"]
    tsize = 20  # shrink long project names until the full title fits the band
    while tsize > 12 and _tw(title, "F2", tsize) > 360:
        tsize -= 1
    pg.text(MARGIN, PAGE_H - 78, title, "F2", tsize, WHITE, max_w=360)
    pg.text(MARGIN, PAGE_H - 100, f"{n} LV positions - currency CHF excl. VAT - source: {src}",
            "F3", 7.5, CREAM, max_w=360)
    pg.text(PAGE_W - MARGIN, PAGE_H - 46, time.strftime("%d %b %Y"), "F2", 10, WHITE, align="right")
    pg.text(PAGE_W - MARGIN, PAGE_H - 62, "SCENARIO", "F3", 6.5, CREAM, align="right")
    pg.text(PAGE_W - MARGIN, PAGE_H - 76, f"waste {num(waste)}% / overhead {num(overhead)}%",
            "F1", 8.5, WHITE, align="right")
    pg.text(PAGE_W - MARGIN, PAGE_H - 90, f"margin {num(margin)}%", "F1", 8.5, WHITE, align="right")

    cards = [
        ("MATERIAL", chf(material), f"{n} positions incl. {num(waste)}% waste"),
        ("LABOUR", chf(labour), "adjusted installation hours"),
        ("DIRECT COST", chf(direct), "material + labour"),
        ("COST BASELINE", chf(baseline), f"+ services, allowances, {num(overhead)}% OH"),
    ]
    cw, gap, ch = (PAGE_W - 2 * MARGIN - 3 * 10) / 4, 10, 52
    y0 = PAGE_H - band_h - 5 - 26
    for i, (label, value, sub) in enumerate(cards):
        x = MARGIN + i * (cw + gap)
        pg.rect(x, y0 - ch, cw, ch, CARD)
        pg.rect(x, y0 - 2, cw, 2, ORANGE)
        pg.text(x + 8, y0 - 15, label, "F2", 6.5, MUTED)
        pg.text(x + 8, y0 - 33, value, "F2", 12.5, INK, max_w=cw - 12)
        pg.text(x + 8, y0 - 45, sub, "F1", 6.3, MUTED, max_w=cw - 14)

    bt = y0 - ch - 14
    pg.rect(MARGIN, bt - 56, PAGE_W - 2 * MARGIN, 56, INK)
    pg.text(MARGIN + 12, bt - 21, "INDICATIVE SELLING PRICE", "F2", 8.5, CREAM)
    pg.text(MARGIN + 12, bt - 44, f"at {num(margin)}% target margin - not a binding offer",
            "F1", 7.5, (0.75, 0.78, 0.82))
    pg.text(PAGE_W - MARGIN - 14, bt - 38, f"CHF {chf(price)}", "F2", 21, WHITE, align="right")

    ry = bt - 56 - 12
    if review:
        pg.rect(MARGIN, ry - 17, PAGE_W - 2 * MARGIN, 17, AMBER_BG)
        pg.text(MARGIN + 8, ry - 12,
                f"{review} of {n} positions await firm supplier quotations - budget rates "
                f"used, marked amber in the table", "F1", 7.5, AMBER)
    else:
        pg.rect(MARGIN, ry - 17, PAGE_W - 2 * MARGIN, 17, GREEN_BG)
        pg.text(MARGIN + 8, ry - 12,
                f"All {n} positions priced from firm catalog rates", "F1", 7.5, GREEN)

    my = ry - 17 - 26
    pg.text(MARGIN, my, "How this price is built - and why", "F2", 12.5, INK)
    pg.rect(MARGIN, my - 6, 34, 2, ORANGE)
    sy = my - 24
    for i, (title, body) in enumerate(steps, 1):
        pg.rect(MARGIN, sy - 8, 9, 9, ORANGE)
        pg.text(MARGIN + 4.5, sy - 6, str(i), "F2", 6.5, WHITE, align="center")
        pg.text(MARGIN + 17, sy - 6.5, title, "F2", 9.5, INK)
        yy = sy - 19
        for line in _wrap(body, "F1", 7.8, PAGE_W - 2 * MARGIN - 17):
            pg.text(MARGIN + 17, yy, line, "F1", 7.8, MUTED)
            yy -= 9.6
        sy = yy - 8

    pg.text(MARGIN, sy - 4, "Why indicative?", "F2", 8, INK)
    note = ("This calculation makes the cost build-up transparent and reviewable. "
            "Supplier-package positions still carry budget rates until quotations arrive; "
            "the final offer replaces them and re-validates the totals. "
            "Generated by Equans AutoTender.")
    yy = sy - 15
    for line in _wrap(note, "F3", 7.5, PAGE_W - 2 * MARGIN):
        pg.text(MARGIN, yy, line, "F3", 7.5, MUTED)
        yy -= 9.2

    # ---------------------------------------------------------- position table
    COLS = [("LV", 56, "left"), ("DESCRIPTION", 100, "left"), ("QTY", 330, "right"),
            ("NET/UNIT", 386, "right"), ("MATERIAL", 442, "right"),
            ("HOURS", 472, "right"), ("LABOUR", 508, "right"), ("DIRECT", 547, "right")]

    def table_header(page, y, continued=False):
        if not continued:
            page.rect(MARGIN, y - 22, PAGE_W - 2 * MARGIN, 22, CARD)
            page.text(MARGIN + 10, y - 15, f"Positions ({n})", "F2", 10, INK)
            page.text(PAGE_W - MARGIN - 8, y - 15,
                      "green dot = firm catalog rate   amber dot = supplier quote pending",
                      "F1", 6.5, MUTED, align="right")
            y -= 30
        else:
            page.text(MARGIN, y, f"Positions ({n}) - continued", "F2", 8, MUTED)
            y -= 14
        for label, x, align in COLS:
            page.text(x, y, label, "F2", 6.3, MUTED, align=align)
        page.rect(MARGIN, y - 5, PAGE_W - 2 * MARGIN, 0.7, BORDER)
        return y - 17

    pages = [pg]
    tp = Page()
    pages.append(tp)
    y = table_header(tp, PAGE_H - 52)
    for i, (p, mat, direct, desc) in enumerate(rows):
        if y < 84:
            tp = Page()
            pages.append(tp)
            y = table_header(tp, PAGE_H - 52, continued=True)
        if i % 2 == 1:
            tp.rect(MARGIN, y - 3.8, PAGE_W - 2 * MARGIN, 12, CARD)
        tp.rect(48, y - 1.2, 4, 4, AMBER if p["review_required"] else GREEN)
        tp.text(56, y, p["lv_id"], "F1", 6.8, INK)
        tp.text(100, y, desc,
                "F1", 7, INK, max_w=214)
        tp.text(330, y, f"{num(p['quantity'])} {p['unit']}", "F1", 7, INK, align="right")
        tp.text(386, y, chf(p["net_unit_cost_chf"]), "F1", 7, INK, align="right")
        tp.text(442, y, chf(mat), "F1", 7, INK, align="right")
        tp.text(472, y, f"{p['adjusted_install_hours']:.2f}", "F1", 7, INK, align="right")
        tp.text(508, y, chf(p["labour_cost_chf"]), "F1", 7, INK, align="right")
        tp.text(547, y, chf(direct), "F2", 7, INK, align="right")
        y -= 13.2

    # ---------------------------------------------------------- footers
    for i, page in enumerate(pages, 1):
        page.rect(MARGIN, 66, PAGE_W - 2 * MARGIN, 0.7, BORDER)
        page.text(MARGIN, 56,
                  f"Equans AutoTender - {calc['project']['name']} - generated "
                  f"{time.strftime('%d %b %Y %H:%M')}", "F1", 6.3, MUTED, max_w=420)
        page.text(PAGE_W - MARGIN, 56, f"Page {i} / {len(pages)}",
                  "F1", 6.3, MUTED, align="right")
    return build_pdf(pages)


def html_report(calc: dict, params: dict, waste: float, overhead: float,
                margin: float, descriptions: dict | None = None) -> str:
    """Standalone HTML version of the offer (self-contained, prints nicely)."""
    d = _offer_data(calc, params, waste, overhead, margin, descriptions)
    rows, chf, num, n = d["rows"], d["chf"], d["num"], d["n"]
    e = lambda t: (str(t).replace("&", "&amp;").replace("<", "&lt;")
                   .replace(">", "&gt;").replace('"', "&quot;"))
    css = """
  body { margin:0; font:14px/1.5 system-ui, sans-serif; color:#1f2328; background:#f4f5f7; }
  .band { background:#d9480f; color:#fff; padding:26px 32px; display:flex;
          justify-content:space-between; gap:24px; flex-wrap:wrap; }
  .band h1 { margin:2px 0 6px; font-size:24px; }
  .band .k { font-size:11px; letter-spacing:.1em; color:#ffd9c7; font-weight:700; }
  .band .meta { text-align:right; font-size:12.5px; color:#ffd9c7; }
  .band .meta b { color:#fff; font-size:14px; }
  .wrap { max-width:1000px; margin:0 auto; padding:22px 18px 40px; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:10px; }
  .card { background:#fff; border:1px solid #e2e5ea; border-radius:10px; padding:10px 14px;
          border-top:3px solid #d9480f; }
  .card .k { font-size:10.5px; letter-spacing:.06em; color:#6b7280; }
  .card .v { font-size:17px; font-weight:700; margin-top:2px; }
  .price { background:#1f2328; color:#fff; border-radius:12px; padding:16px 22px;
           margin-top:14px; display:flex; justify-content:space-between; align-items:center;
           flex-wrap:wrap; gap:8px; }
  .price .v { font-size:26px; font-weight:800; }
  .price .k { font-size:11px; color:#ffbfa8; letter-spacing:.08em; }
  .chip { display:inline-block; margin-top:12px; padding:5px 12px; border-radius:999px;
          font-size:12.5px; }
  .chip.warn { background:#fff4e5; color:#9a3412; }
  .chip.ok { background:#e9f6ec; color:#22572c; }
  h2 { font-size:16px; margin:28px 0 10px; }
  .step { display:flex; gap:12px; margin:10px 0; }
  .step .no { flex:0 0 22px; height:22px; background:#d9480f; color:#fff; font-weight:700;
              border-radius:6px; display:flex; align-items:center; justify-content:center;
              font-size:12.5px; }
  .step b { display:block; }
  .step p { margin:2px 0 0; color:#6b7280; font-size:13px; }
  table { width:100%; border-collapse:collapse; background:#fff; font-size:12.5px; }
  th, td { padding:6px 8px; border-bottom:1px solid #e2e5ea; text-align:right;
           white-space:nowrap; }
  th { color:#6b7280; font-size:11px; }
  th:first-child, td:first-child { text-align:left; }
  tbody tr:nth-child(even) { background:#f8f9fb; }
  .st { padding:1px 8px; border-radius:999px; font-size:11px; background:#e9f6ec; color:#22572c; }
  .st.warn { background:#fff4e5; color:#9a3412; }
  footer { margin-top:22px; color:#6b7280; font-size:11.5px; }
  @media print { body { background:#fff; } .wrap { max-width:none; } }
"""
    cards = [
        ("MATERIAL", chf(d["material"]), f"{n} positions incl. {num(waste)}% waste"),
        ("LABOUR", chf(d["labour"]), "adjusted installation hours"),
        ("DIRECT COST", chf(d["direct"]), "material + labour"),
        ("COST BASELINE", chf(d["baseline"]), f"+ services, allowances, {num(overhead)}% OH"),
    ]
    steps = "".join(
        f'<div class="step"><div class="no">{i}</div><div><b>{e(t)}</b><p>{e(b)}</p></div></div>'
        for i, (t, b) in enumerate(d["steps"], 1))
    table_rows = "".join(
        f"<tr><td>{e(p['lv_id'])}</td><td style='text-align:left'>{e(desc)}</td>"
        f"<td>{e(num(p['quantity']))} {e(p['unit'])}</td><td>{chf(p['net_unit_cost_chf'])}</td>"
        f"<td>{chf(mat)}</td><td>{p['adjusted_install_hours']:.2f}</td>"
        f"<td>{chf(p['labour_cost_chf'])}</td><td><b>{chf(direct)}</b></td>"
        f"<td><span class='st {'warn' if p['review_required'] else ''}'>"
        f"{'quote req.' if p['review_required'] else 'priced'}</span></td></tr>"
        for p, mat, direct, desc in rows)
    chip = (f'<span class="chip warn">{d["review"]} of {n} positions await firm supplier '
            f"quotations - budget rates used</span>" if d["review"]
            else f'<span class="chip ok">All {n} positions priced from firm catalog rates</span>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Equans AutoTender - {e(calc["project"]["name"])}</title><style>{css}</style></head><body>
<div class="band">
  <div><div class="k">INDICATIVE TENDER CALCULATION</div>
    <h1>{e(calc["project"]["name"])}</h1>
    <div style="font-size:12.5px;color:#ffd9c7">{n} LV positions - currency CHF excl. VAT -
      source: {e(d["src"])}</div></div>
  <div class="meta"><b>{time.strftime("%d %b %Y")}</b><br>SCENARIO<br>
    waste {num(waste)}% / overhead {num(overhead)}%<br>margin {num(margin)}%</div>
</div>
<div class="wrap">
  <div class="cards">{"".join(f'<div class="card"><div class="k">{k}</div><div class="v">{v}</div><div class="k">{s}</div></div>' for k, v, s in cards)}</div>
  <div class="price"><div><div class="k">INDICATIVE SELLING PRICE</div>
    <div style="font-size:12px;color:#b9bec6">at {num(margin)}% target margin</div></div>
    <div class="v">CHF {chf(d["price"])}</div></div>
  {chip}
  <h2>How this price is built - and why</h2>{steps}
  <h2>Positions ({n})</h2>
  <table><thead><tr><th>LV</th><th style="text-align:left">DESCRIPTION</th><th>QTY</th>
    <th>NET/UNIT</th><th>MATERIAL</th><th>HOURS</th><th>LABOUR</th><th>DIRECT</th>
    <th>STATUS</th></tr></thead>
  <tbody>{table_rows}</tbody></table>
  <footer>Equans AutoTender - {e(calc["project"]["name"])} - generated
    {time.strftime("%d %b %Y %H:%M")}</footer>
</div></body></html>"""


def _xesc(t) -> str:
    return (str(t).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def docx_report(calc: dict, params: dict, waste: float, overhead: float,
                margin: float, descriptions: dict | None = None) -> bytes:
    """Minimal OOXML .docx (stdlib zipfile only): title, price, summary,
    methodology and the position table."""
    d = _offer_data(calc, params, waste, overhead, margin, descriptions)
    rows, chf, num, n = d["rows"], d["chf"], d["num"], d["n"]

    def para(text, bold=False, size=18, color=None, align=None, after=80):
        rpr = "<w:rPr>" + ("<w:b/>" if bold else "") + \
              (f'<w:sz w:val="{size}"/>' if size else "") + \
              (f'<w:color w:val="{color}"/>' if color else "") + "</w:rPr>"
        ppr = "<w:pPr>" + (f'<w:jc w:val="{align}"/>' if align else "") + \
              f'<w:spacing w:after="{after}"/>' + "</w:pPr>"
        return (f"<w:p>{ppr}<w:r>{rpr}"
                f'<w:t xml:space="preserve">{_xesc(text)}</w:t></w:r></w:p>')

    def cell(text, bold=False, fill=None, align="left", width=None, color=None):
        tcpr = "<w:tcPr>" + (f'<w:tcW w:w="{width}" w:type="dxa"/>' if width else "") + \
               (f'<w:shd w:val="clear" w:fill="{fill}"/>' if fill else "") + "</w:tcPr>"
        return (f"<w:tc>{tcpr}"
                f"{para(text, bold=bold, size=15, align=align, after=0, color=color)}</w:tc>")

    body = [
        para("INDICATIVE TENDER CALCULATION", bold=True, size=17, color="D9480F", after=40),
        para(calc["project"]["name"], bold=True, size=40, after=60),
        para(f"{n} LV positions - currency CHF excl. VAT - source: {d['src']} - "
             f"{time.strftime('%d %b %Y')}   |   scenario: waste {num(waste)}% / "
             f"overhead {num(overhead)}% / margin {num(margin)}%",
             size=15, color="6B7280", after=200),
        para("INDICATIVE SELLING PRICE", bold=True, size=17, color="D9480F", after=40),
        para(f"CHF {chf(d['price'])}", bold=True, size=52, after=40),
        para(f"at {num(margin)}% target margin", size=15, color="6B7280", after=200),
        para("MATERIAL", bold=True, size=15, color="6B7280", after=20),
        para(chf(d["material"]) + f"  ({n} positions incl. {num(waste)}% waste)", size=19, after=120),
        para("LABOUR", bold=True, size=15, color="6B7280", after=20),
        para(chf(d["labour"]) + "  (adjusted installation hours)", size=19, after=120),
        para("DIRECT COST", bold=True, size=15, color="6B7280", after=20),
        para(chf(d["direct"]) + "  (material + labour)", size=19, after=120),
        para("COST BASELINE", bold=True, size=15, color="6B7280", after=20),
        para(chf(d["baseline"]) + f"  (+ services, allowances, {num(overhead)}% overhead)",
             size=19, after=240),
        para("How this price is built - and why", bold=True, size=26, after=120),
    ]
    for i, (title, text) in enumerate(d["steps"], 1):
        body.append(para(f"{i}.  {title}", bold=True, size=18, after=20))
        body.append(para(text, size=16, color="52525B", after=140))
    body.append(para(f"Positions ({n})", bold=True, size=26, after=120))

    borders = "<w:tblBorders>" + "".join(
        f'<w:{side} w:val="single" w:sz="4" w:color="D9DDE5"/>'
        for side in ("top", "left", "bottom", "right", "insideH", "insideV")) + "</w:tblBorders>"
    header = ("<w:tr>" + "".join(
        cell(h, bold=True, fill="F6F7F9", align=al, width=w) for h, al, w in [
            ("LV", "left", 750), ("DESCRIPTION", "left", 2500), ("QTY", "right", 850),
            ("NET/UNIT", "right", 900), ("MATERIAL", "right", 950), ("HOURS", "right", 800),
            ("LABOUR", "right", 950), ("DIRECT", "right", 950), ("STATUS", "right", 850)])
        + "</w:tr>")
    trs = [header]
    for p, mat, direct, desc in rows:
        status = "quote req." if p["review_required"] else "priced"
        status_color = "B45309" if p["review_required"] else "37793F"
        trs.append("<w:tr>" + "".join([
            cell(p["lv_id"], width=750),
            cell(desc[:70], width=2500),
            cell(f"{num(p['quantity'])} {p['unit']}", align="right", width=850),
            cell(chf(p["net_unit_cost_chf"]), align="right", width=900),
            cell(chf(mat), align="right", width=950),
            cell(f"{p['adjusted_install_hours']:.2f}", align="right", width=800),
            cell(chf(p["labour_cost_chf"]), align="right", width=950),
            cell(chf(direct), bold=True, align="right", width=950),
            cell(status, align="right", width=850, color=status_color),
        ]) + "</w:tr>")
    body.append(f"<w:tbl><w:tblPr>{borders}</w:tblPr>{''.join(trs)}</w:tbl>")
    body.append(para(f"Equans AutoTender - {calc['project']['name']} - generated "
                     f"{time.strftime('%d %b %Y %H:%M')}", size=13, color="6B7280", after=0))
    body.append('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
                '<w:pgMar w:top="1000" w:right="720" w:bottom="1000" w:left="720"/></w:sectPr>')

    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                f'<w:body>{"".join(body)}</w:body></w:document>')
    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/word/document.xml" ContentType="application/vnd.'
                     'openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", document)
    return buf.getvalue()


def _offer_disposition(meta: dict, ext: str, inline: bool = False) -> dict:
    """Content-Disposition header naming the file '<tender name>_offer.<ext>'
    (ASCII fallback + RFC 5987 UTF-8 name when the tender name needs it)."""
    base = re.sub(r"[^\w .()-]", "_", meta.get("name", "")).strip(" .") or "tender"
    disp = "inline" if inline else "attachment"
    fname = f"{base}_offer.{ext}"
    ascii_fname = fname.encode("ascii", "replace").decode().replace("?", "_")
    header = f'{disp}; filename="{ascii_fname}"'
    if fname != ascii_fname:
        header += f"; filename*=UTF-8''{quote(fname)}"
    return {"Content-Disposition": header}


# ---------------------------------------------------------------- HTTP server

class Handler(BaseHTTPRequestHandler):
    server_version = "AutoTenderUI/0.2"

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} {fmt % args}", file=sys.stderr)

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _body_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        try:
            if url.path == "/":
                self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
            elif parts[:2] == ["api", "tenders"] and len(parts) == 2:
                self._json(200, list_tenders())
            elif parts[:2] == ["api", "settings"]:
                self._json(200, load_ui_settings())
            elif parts[:2] == ["api", "tenders"] and len(parts) == 3:
                tid = parts[2]
                meta = load_meta(tid)
                try:
                    calc = json.loads(calc_path(tid).read_text())
                except FileNotFoundError:
                    calc = None
                self._json(200, {"meta": meta, "calc": calc,
                                 "params": calc_common.load_params()})
            elif parts[:2] == ["api", "tenders"] and len(parts) == 4 and parts[3] == "download":
                which = (parse_qs(url.query).get("file") or ["positions"])[0]
                src = positions_path(parts[2]) if which == "positions" else TENDERS / parts[2] / "tender.pdf"
                if not src.exists():
                    self._json(404, {"error": f"no {which} file stored for this tender"})
                    return
                self._send(200, src.read_bytes(),
                           "text/csv" if which == "positions" else "application/pdf",
                           {"Content-Disposition": f'attachment; filename="{src.name}"'})
            elif parts[:2] == ["api", "tenders"] and len(parts) == 4 and parts[3] == "pdf":
                tid = parts[2]
                calc = json.loads(calc_path(tid).read_text())
                params = calc_common.load_params()
                descriptions = {}
                if positions_path(tid).exists():  # client-facing text from the upload
                    with positions_path(tid).open(newline="") as f:
                        descriptions = {r["lv_id"]: r.get("description", "")
                                        for r in csv.DictReader(f)}
                q = parse_qs(url.query)
                num = lambda key, default: float(q.get(key, [default])[0])
                waste = num("waste", params["allowances"]["material_waste_pct"])
                overhead = num("overhead", params["commercial"]["overhead_pct"])
                margin = num("margin", params["commercial"]["target_margin_pct"])
                fmt = (q.get("format") or ["pdf"])[0]
                offer_disp = _offer_disposition(load_meta(tid), fmt)
                if fmt == "html":
                    if q.get("inline"):
                        offer_disp["Content-Disposition"] = \
                            offer_disp["Content-Disposition"].replace("attachment", "inline")
                    self._send(200, html_report(calc, params, waste, overhead,
                                                margin, descriptions).encode(),
                               "text/html; charset=utf-8", offer_disp)
                elif fmt == "docx":
                    self._send(200, docx_report(calc, params, waste, overhead,
                                                margin, descriptions),
                               "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                               offer_disp)
                else:
                    pdf = pdf_report(calc, params, waste, overhead, margin, descriptions)
                    self._send(200, pdf, "application/pdf", offer_disp)
            else:
                self._json(404, {"error": f"unknown path {url.path}"})
        except FileNotFoundError:
            self._json(404, {"error": "tender not found"})
        except Exception as e:
            self._json(500, {"error": f"{type(e).__name__}: {e}"})

    def do_POST(self):
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        try:
            if parts[:2] == ["api", "tenders"] and len(parts) == 2:
                self._json(201, create_tender(self._body_json().get("name", "")))
            elif parts[:2] == ["api", "settings"] and len(parts) == 3 and parts[2] == "update":
                body = self._body_json()
                task = body.get("task")
                if task not in TASK_KEYS:
                    self._json(400, {"error": f"unknown task {task!r}"})
                    return
                settings = load_ui_settings()
                t = settings["tasks"][task]
                t["links"] = str(body.get("links", ""))[:2000]
                version = time.strftime("%Y-%m-%d")
                if any(v["version"] == version for v in t["versions"]):
                    version = time.strftime("%Y-%m-%d %H:%M")
                t["versions"].append({"version": version, "base": settings["base_model"]})
                t["selected"] = version
                settings = save_ui_settings(settings)
                self._json(200, {"ok": True, "version": version, "settings": settings})
            elif parts[:2] == ["api", "settings"] and len(parts) == 3 and parts[2] == "upload-data":
                q = parse_qs(url.query)
                task = (q.get("task") or [""])[0]
                if task not in TASK_KEYS:
                    self._json(400, {"error": f"unknown task {task!r}"})
                    return
                name = re.sub(r"[^A-Za-z0-9._-]", "_",
                              Path(unquote(q.get("name", ["data"])[0])).name) or "data"
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                dest = UPLOADS / "lora_data"
                dest.mkdir(parents=True, exist_ok=True)
                (dest / f"{task}_{time.strftime('%Y%m%d_%H%M%S')}_{name}").write_bytes(body)
                self._json(200, {"ok": True, "message": "data stored"})
            elif parts[:2] == ["api", "settings"]:
                settings = save_ui_settings(self._body_json())
                self._json(200, {"ok": True, "settings": settings})
            elif parts[:2] == ["api", "tenders"] and len(parts) == 4 and parts[3] == "rename":
                meta = load_meta(parts[2])
                name = str(self._body_json().get("name", "")).strip()[:60]
                if not name:
                    self._json(400, {"error": "name must not be empty"})
                    return
                meta["name"] = name
                save_meta(meta)
                self._json(200, {"ok": True, "name": name})
            elif parts[:2] == ["api", "tenders"] and len(parts) == 4 and parts[3] == "upload":
                self._upload(parts[2], parse_qs(url.query))
            elif parts[:2] == ["api", "tenders"] and len(parts) == 4 and parts[3] == "recalc":
                tid = parts[2]
                if not positions_path(tid).exists():
                    self._json(400, {"error": "no positions csv uploaded for this tender"})
                    return
                out = calc_tender(tid)
                self._json(200, {"ok": True, "message": out})
            elif parts[:2] == ["api", "tenders"] and len(parts) == 4 and parts[3] == "values":
                result = apply_edits(parts[2], self._body_json().get("edits", {}))
                self._json(200, {"ok": True, "message": f"{result.pop('_edited_positions')} position(s) updated",
                                 "calc": result})
            else:
                self._json(404, {"error": f"unknown path {url.path}"})
        except FileNotFoundError:
            self._json(404, {"error": "tender not found"})
        except Exception as e:
            self._json(500, {"error": f"{type(e).__name__}: {e}"})

    def do_DELETE(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        try:
            if parts[:2] == ["api", "tenders"] and len(parts) == 3 and tid_valid(parts[2]):
                shutil.rmtree(TENDERS / parts[2], ignore_errors=True)
                self._json(200, {"ok": True})
            else:
                self._json(404, {"error": "unknown tender"})
        except Exception as e:
            self._json(500, {"error": f"{type(e).__name__}: {e}"})

    def _upload(self, tid: str, q: dict) -> None:
        # raw-body upload (filename via query param): avoids multipart parsing,
        # which the stdlib cgi module used to provide (removed in Python 3.13)
        load_meta(tid)  # 404 if unknown
        name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(unquote(q.get("name", ["upload"])[0])).name)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        ext = Path(name).suffix.lower()
        meta = load_meta(tid)

        if ext == ".csv":
            rows = list(csv.DictReader(io.StringIO(body.decode("utf-8-sig"))))
            missing = [c for c in REQUIRED_CSV_COLUMNS if c not in (rows[0] if rows else {})]
            if not rows or missing:
                self._json(400, {"error": f"csv must have columns {REQUIRED_CSV_COLUMNS}, missing: {missing}"})
                return
            positions_path(tid).write_bytes(body)
            out = calc_tender(tid)
            meta.update(status="calculated", uploaded_file=name)
            save_meta(meta)
            n = len(json.loads(calc_path(tid).read_text())["position_results"])
            self._json(200, {"ok": True,
                             "message": f"{name}: calculated {n} positions from {len(rows)} rows - {out}"})
        elif ext == ".pdf":
            (TENDERS / tid / "tender.pdf").write_bytes(body)
            meta.update(status="pdf_stored", uploaded_file=name)
            save_meta(meta)
            self._json(200, {"ok": True,
                             "message": f"{name} stored; AI input processing (_1_AI_InputProcessing) "
                                        "is not implemented yet - upload a positions .csv to calculate"})
        else:
            self._json(400, {"error": "unsupported file type, expected .csv or .pdf"})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        sys.exit(f"cannot bind port {port} ({e}) - try another one, "
                 f"e.g. python3 server.py {port + 1}")
    print(f"AutoTender UI: http://127.0.0.1:{port}  "
          f"({len(list_tenders())} tender(s), Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
