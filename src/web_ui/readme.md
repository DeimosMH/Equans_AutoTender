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
   a preserved client-facing offer as **PDF**, **HTML** (standalone page) or **DOCX**
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
removes the directory and its current outcome/productivity training exports.

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

## LoRA settings

Open **LoRA settings** in the sidebar, or `/#training`. The **LoRAs** tab follows
the three tasks in `todo`: input processing, productivity factors and success
probability. It has three simple menus:

- **Select LoRAs**: choose a version for each task. Each option shows its base
  model, which is selected automatically with the LoRA. Expert productivity
  values remain an explicit option, with a link to edit them.
- **Update LoRAs**: select a task, use internal training data, **Upload data** from
  local files and/or add data links, then save an update request. Files show their
  names and sizes and can be removed individually. A task without a selected
  version offers Create LoRA.
- **Base models**: choose a base LLM independently for each task. Changing a base
  clears an incompatible LoRA without affecting the other tasks.

The URL follows every menu and task tab. For example,
`/#lora-settings/advanced/configuration/input-processing/cloud` opens Configuration
with Input processing and Cloud selected, and
`/#lora-settings/loras/update/productivity-factors` opens that task's update form.
Copied links, reloads and browser Back/Forward restore those tabs. Existing
`/#training` links still work. Configuration URLs include the Local/Cloud selection;
older links without it use the current browser selection (Cloud by default).
Endpoints, paths, model choices, files and other form values are not included.
Opening a link changes the displayed selection without saving configuration.

These are interactive **UI previews**, as requested while the backend is pending.
Choices, paths, parameters and the latest update request per task persist in this
browser's `tendif_lora_preferences_v1` localStorage entry. Existing version metadata
comes from `/api/settings`; selecting it does not certify, activate or retrain an
adapter. Update requests capture the selected version/base, source choices, links,
selected-file metadata, parameters and execution choice. Local requests include
filesystem paths; cloud requests include only the cloud endpoint, which can be
pending. File objects stay in the
current browser session; after reloading, a reminder asks for the files again.
File contents are not uploaded or stored in localStorage. Requests are not submitted
to a remote queue. The saved
example count comes from Tendif's current inventory; custom directories are not scanned.

**Advanced** contains:

- **Configuration**: choose **Local** or **Cloud** for the model service. Cloud
  is the default and shows an optional endpoint field; it can be supplied later.
  Local shows model/LoRA/data/cache directories. Switching preserves both sets
  of values. Per-task rank, alpha, dropout, epochs and learning rate apply to
  either choice. These remain browser-local preview settings; no connection is
  tested or started. Endpoint URLs must use HTTP(S) without embedded credentials.
- **Data preparation**: the working dataset tools, with model ID, **Save as default**,
  existing-source selection, validated JSONL imports, example previews, split
  counts and downloadable bundles. Tender results and measurements can be opened
  from here. Connection details are collapsed.
- **Sources**: import simap projects or search historical ventilation awards.
- **History**: reopen previous preparations and collections.
- **Evaluation**: review outcome/forecast history, prepare candidate evaluation
  bundles and import model results.

Fresh settings default to `glm-5.3-flash`; existing model settings are preserved.
An Advanced model override applies to that preparation unless saved as default.
Advanced is a UI separation for administrators, not an access-control boundary;
the app remains a local tool without authentication.

The model will run in cloud Docker. Its endpoint and LoRA API contract are pending;
preparation does not submit training or activate a model. The training workflow
never asks for a key in the UI.
See [unified context](../../PROJECT_CONTEXT.md) for boundaries and API contracts.

## Settings

Settings contains editable productivity factors and appearance. Monitoring and
candidate evaluation live in **LoRA settings → Advanced → Evaluation**. The target model for a new dataset
is configured in **LoRA settings → Advanced → Data preparation**. Preview choices
are separate from these working preparation settings and calculator factors.
AI productivity factors are demo values until a trained adapter is integrated.
Manual and demo factors both remain editable and feed the calculator.

Tender edits are retained in memory when visiting Settings or Training and
returning to the same tender; Save changes persists them. Refreshing the browser
still requires saving first. Reloading reopens the selected tender. Saving
positions preserves the current margin, overhead and waste controls.

For isolated review/tests, set `AUTOTENDER_UI_DATA_DIR` to a new directory. It holds
tenders, uploads, settings, jobs and feedback reviews; the default location remains this directory.

## Notes / limitations

- Raw-body upload instead of multipart: the stdlib `cgi` module was removed in
  Python 3.13.
- Browser/PDF recompute is indicative (JS floats); the authoritative numbers
  are computed by `_2_Calculator` with `Decimal` half-up rounding.
- Bid scenarios and live win curves now come from `_3_Prediction`: they are
  explicitly heuristic and uncalibrated until an evaluated predictor is integrated.
- Full context and remaining boundaries: [PROJECT_CONTEXT.md](../../PROJECT_CONTEXT.md).
- Task upload schemas: [dataset_formats.md](../_3_Prediction/dataset_formats.md).
- Preparation jobs: `GET /api/settings/jobs`, `GET /api/settings/jobs/<id>` and
  `GET /api/settings/jobs/<id>/artifacts/<filename>`.
- Prediction: `GET /api/tenders/<id>/wincurve?baseline=<CHF>`.

Preparation reuses public corpus for Public notices and sponsor examples for
Tender matching; other tasks use their own reviewed uploads and feedback.

## Outcome feedback

Active tenders show pricing and positions. **Tender finalised** saves pending
position edits and commercial choices, locks the estimate, and opens **Tender
outcome** at the top. Upload supporting documents, record the result and actual
submission date, choose the downloaded offer actually submitted (or enter another
offer manually), and correct the outcome later. Decision details, public
notices and measured productivity are collapsed. **Reopen tender** restores editing
without discarding the outcome or its documents.

Files are stored under `tenders/<id>/completion_documents/` with opaque IDs,
original names and hashes; PDFs, DOCX, text, CSV and images up to 20 MB are accepted.
They download as attachments; uploading a document does not parse or train on it.

| Route | Purpose |
|---|---|
| `POST /api/tenders/<id>/finalise` `{edits, margin, overhead, waste}` | Save and finalise the estimate |
| `POST /api/tenders/<id>/reopen` | Resume editing |
| `GET /api/tenders/<id>/completion-documents` | List supporting documents |
| `POST /api/tenders/<id>/completion-documents?name=<file>` | Upload an outcome document |
| `GET /api/tenders/<id>/completion-documents/<document-id>` | Download a document |

Downloading saves pending position edits and freezes the chosen calculation,
price and forecast automatically. Repeated downloads of an unchanged offer reuse
the snapshot. The finalised form offers these preserved bids for confirmation;
choosing one restores its price. An existing immutable submission is preserved.
Manually entering another offer after completion is retrospective and excluded
from win-probability training and calibration. Downloads first made after completion
are also excluded. Verified outcomes with a genuine prior snapshot and measured
productivity feed their corresponding `_3` uploads. Reports remain available as
Markdown/HTML/PDF; the UI links to PDF. No training runs automatically.
Measured factors reload for correction and can be excluded from learning.
**LoRA settings → Advanced → Evaluation** contains compact monitoring,
evaluation bundle preparation, result import and saved review history. It checks
candidate results against frozen local references, while keeping outcome labels
out of the cloud inference bundle. The endpoint is still pending; no remote job
is submitted and no adapter is activated.
See [recursive improvement documentation](../_4_RecursiveImprovement/readme.md).

## Verification

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
# With Playwright, Chromium and PyYAML installed in the test environment:
python3 tests/browser_training.py
python3 tests/browser_lora_settings.py
python3 tests/browser_feedback.py
```

The browser check uses temporary storage and covers preparation, previews,
downloads, uploads, navigation, tender editing, finalisation/reopening, persisted
outcome corrections, evidence documents, safe rendering of CSV text, dark mode
and responsive layouts.

The LoRA settings browser check covers model/version compatibility, per-task
choices, manual fallback, request contents, paths and parameter persistence. It
also checks shared tab links, reloads, Back/Forward and invalid-route fallbacks. It
asserts that the preview sends no writes to the backend and preserves server settings.

The feedback browser check also covers bound candidate imports, rejection of invalid
responses, persisted review results, downloads and light/dark/mobile layouts.
