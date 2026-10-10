# web_ui

Multi-tender web UI on top of the calculator: a sidebar lists all tenders with
`+ Add tender` at the bottom; a fresh tender opens an empty page with a big
`Upload tender` button (click or drag & drop); once a positions csv is
uploaded, everything is calculated and stays interactive. Stdlib only.

## Run

```sh
./run.sh [port]              # or: python3 server.py [port]   (default 8080)
```

Then open http://127.0.0.1:8080. Note: a plain static server
(`python3 -m http.server`) is **not** enough - the UI needs this backend for
tenders, the calculator pipeline and PDF export; the root `index.html` exists
only to catch that mistake with instructions. Binds to 127.0.0.1 only (local
tool, no auth).

## Flow

1. **+ Add tender** (bottom of the tenders menu) creates `tenders/<id>/` with a
   `meta.json` (`status: new`) and opens the empty page with the big
   **Upload tender** button.
2. **Upload**:
   - positions `.csv` - validated for required columns
     (`lv_id, source_page, quantity, unit, suggested_product_id`), stored as the
     tender's `positions.csv`, and calculated immediately by running the
     `_2_Calculator` step1-4 pipeline with `AUTOTENDER_CALC_OUT` pointing at the
     tender's own `calc.json`.
   - tender `.pdf` - stored as `tender.pdf`, status `pdf_stored`, until
     `_1_AI_InputProcessing` exists.
3. **Calculated view**: margin slider + overhead/waste inputs recompute the
   price live in the browser (formula mirrors `step4_project.py`); clicking a
   column header sorts the table by that value (toggle asc/desc; numeric keys
   read the live cells, so edited values sort correctly). Table cells
   for **quantity, net unit cost and labour cost are editable** - edits mark
   the row, and **Save changes** persists them: the server recomputes material
   from quantity x net x waste, recomputes labour from the productivity rules
   when quantity changes (an explicit labour edit is kept as an override),
   then step3/step4 rebuild direct costs and summaries. **Recalculate** via
   `POST /api/tenders/<id>/recalc` re-runs the whole pipeline from the stored
   csv (manual overrides are replaced by rule values). **Download ▾** exports
   the client-facing offer as **PDF**, **HTML** (standalone page) or **DOCX**
   (editable Word) - same content and numbers in all three: branded cover
   (KPI cards, indicative selling price banner, status chip, a "how this
   price is built - and why" methodology) plus the position table with
   green/amber status. All generators are dependency-free (hand-rolled PDF
   painter, self-contained HTML, minimal OOXML zip).

Tender names are editable: the &#9998; next to the title renames the current
tender (`POST /api/tenders/<id>/rename`; Enter or clicking away saves, Esc
cancels).

## Tenders store

`tenders/<id>/` (gitignored): `meta.json` (name, status, timestamps),
`positions.csv` (latest upload), `calc.json` (this tender's calculation),
`tender.pdf` (raw tender upload, if any). Deleting a tender in the sidebar
removes the directory.

## Endpoints

| Route | Purpose |
|---|---|
| `GET /` | the single page (`static/index.html`) |
| `GET /api/tenders` | list tenders |
| `POST /api/tenders` `{name}` | create tender |
| `GET /api/tenders/<id>` | `{meta, calc, params}` |
| `POST /api/tenders/<id>/upload?name=<file>` | raw-body upload (`.csv` calculates, `.pdf` stores) |
| `POST /api/tenders/<id>/values` `{edits: {lv_id: {field: value}}}` | persist manual edits + recompute |
| `POST /api/tenders/<id>/rename` `{name}` | rename a tender |
| `GET /api/tenders/<id>/download?file=positions\|tender` | download the stored csv / uploaded tender pdf |
| `POST /api/tenders/<id>/recalc` | re-run the pipeline on the stored csv |
| `GET /api/tenders/<id>/pdf?format=pdf\|html\|docx&margin&overhead&waste` | export the offer (`&inline=1` previews HTML in the tab) |
| `DELETE /api/tenders/<id>` | delete tender |

## Settings

`⚙ Settings` manages LoRA models per task. Two clean sections plus Advanced
(persisted via `GET/POST /api/settings` in `ui_settings.json`, gitignored):

- **LoRA per task** - one row each for *Input processing*, *Productivity
  factors*, *Win-ratio prediction*; the selector lists that task's LoRA
  versions (dates) or `none`. Only versions trained for the current base
  model are listed - the rest stay stored but need retraining.
- **Update LoRAs** - the same three rows, each with **Upload data**
  (training data file, stored under `uploads/lora_data/`), a
  *provide links for tenders* field, and **Update**, which registers a new
  dated version and selects it (retraining itself is assumed automatic once
  the backend exists; endpoints `/api/settings/update` and
  `/api/settings/upload-data`).
- **Advanced** - the base model (changing it changes which versions are
  available) and the model paths (models / loras / cache dirs).
- **Appearance** - a dark mode toggle; applies to the whole app instantly and
  persists per browser (localStorage).

## Notes / limitations

- Raw-body upload instead of multipart: the stdlib `cgi` module was removed in
  Python 3.13.
- Browser/PDF recompute is indicative (JS floats); the authoritative numbers
  are computed by `_2_Calculator` with `Decimal` half-up rounding.
- Bid scenarios / win probability belong to `_3_Prediction` and are absent here.
