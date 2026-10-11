# Tendif unified implementation context

Updated 2026-10-11. This is the authoritative project handoff. The historical
`context_agent_*` reports are research notes; resolve conflicts using this file
and the executable tests. No credential from the conversation belongs in source,
UI settings, training files, logs or this document.

## Product and user decisions

Tendif helps a human estimate ventilation tenders (BKP 244): review
positions and catalogue matches, calculate material/labour/project cost, compare
indicative bid scenarios, and learn from evidence after submission. It does not
submit offers automatically. `materials/README.md` defines the challenge and
`materials/expected_output_example.json` defines the reference arithmetic.

The user rejected a previous UI for bloat, inconsistent styling and layout bugs.
Preserve the existing tender editor, orange/neutral theme, editable table and
pricing controls. **LoRA settings** has two tabs. **LoRAs** follows the original
`src/web_ui/todo`: Select LoRAs / Update LoRAs / Base models, each for input
processing, productivity factors and success probability. Selecting a version
also chooses its base model; changing a task's base clears an incompatible LoRA.
Manual expert productivity remains an explicit fallback. **Advanced** contains
Configuration (paths and per-task LoRA parameters), Data preparation, Sources
History and Evaluation. Public-notice extraction remains an admin dataset task. This is a UI split,
not an authentication boundary; the server remains localhost-only with no auth.
General Settings contains productivity and appearance. Outcome monitoring and
candidate evaluation are under **LoRA settings → Advanced → Evaluation**.
Active tenders show pricing and positions only: margin chips remain, while the
extra scenario comparison and implementation disclaimer are removed. **Tender
finalised** saves edits/commercial choices, locks the estimate and reveals
**Tender outcome** at the top, with document upload and a short result form.
Decision details, public notices and actual productivity are collapsed. Reopening
restores editing and retains existing results/documents. Shared theme tokens keep
links and controls readable in both themes; there are no default blue links.

The requested base model is **GLM-5.3-Flash**. Default preparation ID:
`glm-5.3-flash`; the provider may use another ID, so custom IDs are accepted and
captured in each preparation run. Existing settings and old runs are retained.
Advanced → Data preparation allows a per-run override and an explicit
**Save as default** action; it does not silently replace an existing model setting.

The latest user explicitly requested the resulting selection/update UI before
backend integration. `static/lora-settings.js` therefore stores preview choices
in browser localStorage (`tendif_lora_preferences_v1`), separately from live
calculator factors, server settings and preparation jobs. Version metadata is
read from settings; no metadata is promoted to a verified or active adapter.
The latest request per task captures base/version, internal-data selection,
links, data directory and proposed LoRA parameters with a timestamp. The UI
also offers **Upload data** for every task, with multiple files, sizes and removal.
File objects stay separate per task for the current session; only their metadata
is retained in saved requests. After reloading, the UI asks for files to be selected
again. Uploading file contents awaits the backend. The UI
validates link syntax but does not fetch links, scan custom directories, queue
remote jobs or fabricate trained versions. Saved example counts reflect the
existing Tendif inventory. Connect the UI to a validated model registry and
activation/update API when the cloud contract is supplied; preserve per-task
base/version compatibility and keep activation separate from preparation.
The user confirms the model/training service will run in **Docker in the cloud**.
Its endpoint and training API contract have not been provided. Remote upload,
training, job polling and adapter serving are therefore pending integrations.
Preparation and review work now; no successful training is implied.

## Modules and dependencies

- `_1_AI_InputProcessing`: research/todo. PDF upload stores a document; it does
  not yet extract full LV positions. Sponsor matching examples are not labels
  for physical PDF-page extraction.
- `_2_Calculator`: working four-step material/labour/direct/project calculation.
  Python and PyYAML; Decimal half-up money rounding; catalogue/productivity tables
  and project parameters. `AUTOTENDER_CALC_OUT` isolates each tender's result.
- `_3_Prediction`: working simap collection, evidence validation, grouped dataset
  preparation, persisted jobs, download bundles and heuristic bid scenarios.
  Standard library. `train_lora.py` is an optional generic causal-LM PEFT trainer,
  not a validated GLM-5.3 cloud training runtime.
- `_4_RecursiveImprovement`: immutable bid snapshots, verified outcome revisions,
  source evidence, debrief reports, revisioned/revocable measured productivity,
  monitoring and persisted candidate evaluation handoffs/results. Verified exports enter the corresponding `_3` uploads. No automatic
  model activation. See its readme for detailed payloads.
- `web_ui`: localhost stdlib HTTP server and dependency-free HTML/CSS/JS. Training
  admin preparation code is `static/training.js` / `static/training.css`;
  `static/lora-settings.js` owns the task-based UI preview. Tender/settings logic stays
  in `static/index.html`; `static/learning.js` handles Advanced → Evaluation.
  `static/workspace.css` contains shared accessibility and
  completed-tender styles. No frontend build step.
- `src/autoTender.py`: `calculate` runs calculator plus prediction; `prepare`
  creates persisted task datasets from uploaded and existing sources.

Start from repository root:

```sh
python3 src/web_ui/server.py 8080
# http://127.0.0.1:8080/#training
```

`AUTOTENDER_UI_DATA_DIR` optionally redirects tenders, uploads, settings and jobs
and feedback reviews for isolated tests/review. Default storage remains `src/web_ui/`. Public corpus
and sponsor inputs remain shared read-only inputs to preparation. Generated
corpora, raw snapshots, user tenders, settings and jobs are gitignored.

## Calculator and prediction assumptions

Positions -> material/labour -> direct costs -> services/allowances -> overhead
baseline -> selling price. Margin means gross margin on sale, not markup:
`price = baseline / (1 - margin_pct/100)`. Scenario bids round upward to configured
`commercial.round_to_chf`. Expected contribution uses full-precision heuristic
P(win) multiplied by bid minus baseline. Displayed probability is rounded.

`predict.py` enriches `calc.json.recommended_bid_range` after recalculation/edits.
`GET /api/tenders/<id>/wincurve?baseline=<CHF>` evaluates unsaved cost changes.
Aggressive/Target/Conservative use configured margins. All estimates currently
remain **heuristic, untrained and uncalibrated**. The +/-5 percentage-point band
is sensitivity, not statistical confidence. Golden example arithmetic uses the
example subset baseline; the UI uses full project baseline including services.

In-session tender edits and scenario inputs survive visiting Training/Settings
and returning to the tender. Explicit Save persists position edits. Browser
reload is not a draft persistence mechanism; it does retain the selected tender.
Saving positions preserves the current pricing inputs. Finalising saves the
commercial choices for reloads and later reports. PDF/HTML/DOCX offers and table
sorting continue to use the existing calculator workflow.

The user explicitly approved **automatic preservation of downloaded offers**.
Download saves pending position edits and freezes calculation, chosen margin,
overhead/waste, descriptions, actual price and probability under
`feedback/offers/<id>.json`. Identical offers reuse the same snapshot. Frozen offer
exports ignore later live edits and query-price overrides. The forecast keeps the
configured reference margin: selecting another margin must move its probability.

Finalisation is a lifecycle marker, not proof of submission. In **Tender outcome**,
choose the downloaded offer actually submitted and enter its real submission date.
The selected snapshot supplies the price. A download alone creates no submission.
Offer preservation must precede submission and the verified outcome to be eligible.
Downloads first made after completion are excluded. Choosing **Other offer** makes
a retrospective capture, excluded from win training/calibration. The confirmed
submission is immutable; subsequent downloads never overwrite it.

Outcome corrections preserve revision checks and competitor/reason evidence.
Supporting documents are retained with hashes and are not automatically parsed or
made into labels. Reports contain the bid, dates, evidence, missing information and
readable comparisons. Public notice imports accumulate evidence and never infer our
participation. Actual productivity reloads for editing; archived revisions protect
corrections, and **Exclude from learning** revokes its current export. Deleting a
tender removes its active win/productivity exports. Already prepared datasets and
reviews remain historical: prepare new artifacts after correcting their evidence.

## Evidence boundaries

1. Public tenders/awards disclose procurement information, not Equans's private
   costs, participation or losing bids. Never invent own losses from other winners.
2. The supplied simap project `d849c22b-3fc4-48d8-94c9-c45457544ab1` is a real tender
   source (publication `39697-01`, 2026-08-06). A fresh API collection on this review
   still returned a tender, not an own-bid outcome.
3. Post-award prices, bidder counts, winners and debrief explanations cannot be
   features for predicting that same bid. Historical priors need temporal cutoffs.
4. Won/lost labels train outcome classification; LLM output is not a calibrated
   numeric probability. Use verified own bids, chronological evaluation and
   calibration before replacing the heuristic.
5. Public structured API normalization is an auxiliary extraction task, distinct
   from full PDF/LV extraction, catalogue matching and win prediction.
6. Productivity labels require positive finite measurements and a reference.
   Current settings' AI factors are demo defaults, not trained adapter output.
7. Dataset readiness, completed training, evaluated quality and deployed adapters
   are separate states. Preparation never registers/selects a working adapter.

## Collection and reusable source library

`collect/simap.py` uses simap's public JSON API: project search and headers in v2,
publication details in v1. API responses are archived with URL, timestamp, SHA-256,
publication/project identifiers and attribution; unknown values remain null.
German/French searches use their respective language indexes. Only validated
HTTPS simap project URLs are accepted; requests are bounded with pacing/retries.
The public page is a SPA; the public JSON API supplies the usable records.

The UI offers **explicit project collection** separately from an optional
**historical HVAC award search**. Entering a URL alone does not silently search
for more awards. The current bounded search collects at most 20 awards over two
pages per configured term; it is a sample, not the complete archive.

Collection jobs archive their own source snapshots. Advanced → Sources combines
the checked-in-workspace corpus with completed job collections, deduplicated by
publication ID, preferring newer archived job snapshots. Preparation reuses this
library without fetching again. No source data is repurposed as an own-bid label.
Source failures appear in collection results; an empty failed collection cannot
report success. Hash mismatches or missing raw public snapshots fail preparation.

This workspace has 45 real awards plus the supplied tender (46 publications).
Source files are local generated artifacts, not guaranteed on a fresh checkout.
Use Advanced → Sources → supplied example / optional historical search to rebuild.
SearxNG is available at `http://127.0.0.1:8888/search?q=...&format=json`; its initial
GLM search returned no results. Use primary documentation when search is empty.

## Dataset tasks and artifacts

Task-specific JSONL schemas: `src/_3_Prediction/dataset_formats.md`.
All records require a project ID, nonempty input and appropriate target.

| Task | Evidence | Current workspace readiness |
| --- | --- | --- |
| `market_extraction` | Raw public API snapshots and normalized metadata | 46 examples, 38 train / 4 validation / 4 test |
| `input_processing` | Reviewed catalogue/position examples | 22 sponsor examples, one project; blocked |
| `win_ratio` | Own bids with submission/outcome chronology and won/lost labels | Requires verified independent own-bid projects and both classes |
| `productivity_factors` | Measured factors and measurement references | Requires independent measured project evidence |

`dataset.py` validates and deduplicates examples, groups by project, deterministically
splits into train/validation/test and writes messages JSONL. Project overlap is
prevented, but this default split is **not a chronological backtest**. Structural
readiness alone is not enough data or evidence of useful model quality.

Each new preparation produces:

- `train.jsonl`, `validation.jsonl`, `test.jsonl` (system/user/assistant messages).
- `manifest.json`: task/model, accepted/rejected/split/project counts, assignments,
  source-file digests, artifact hashes, status and blockers.
- `examples.json`: split/line/project mapping, example fingerprints, source
  provenance or measurement/bid chronology, submission hash, outcome/measurement
  revision and evidence reference outside the model prompt. Its own hash
  is in the manifest. This preserves source review without leaking evidence fields
  into bid prediction inputs.
- `rejected.json`: validation/duplicate reasons.
- `training_request.json`: intended model, LoRA operation/proposed settings,
  cloud Docker execution expectation, hashes, evidence blockers and evaluation
  requirements. `submission_status` remains `not_submitted`.
- `dataset_bundle.zip`: the above files for review/handoff. The held-out test file
  is included for later evaluation; the request explicitly forbids training on it.

Jobs persist across reloads; interrupted preparation/collection is marked failed
on server restart. Old runs remain downloadable. Sources apply only to relevant
tasks: public corpus to notice extraction, sponsor records to tender matching,
uploaded/internal feedback to the corresponding task. This avoids unrelated
public-source failures blocking a productivity or own-bid dataset.

## UI/API contracts

| Route | Behavior |
| --- | --- |
| `GET /api/training` | Sources, validated evidence counts/distinct projects per task, calculated tenders, saved default model, runs, credential presence only |
| `POST /api/training/collect` | `{urls: [...], search_hvac: false}` -> persisted collection job |
| `POST /api/training/prepare` | `{task, base_model, include_existing: true}` -> persisted preparation |
| `GET /api/training/<job>/preview?split=train` | At most three examples with evidence metadata |
| `POST /api/settings/upload-data?task=...&name=...jsonl` | Atomic validated UTF-8 JSONL upload |
| `GET /api/settings/jobs/<job>` | Persisted status, errors, manifest and artifact names |
| `GET /api/settings/jobs/<job>/artifacts/<name>` | Allowlisted artifact download |
| `POST /api/tenders/<id>/offers` | Save pending edits and freeze chosen offer; returns offer ID |
| `GET /api/tenders/<id>/pdf?offer=<id>&format=pdf\|html\|docx` | Export frozen offer |
| `POST /api/tenders/<id>/submission` | Confirm `{offer_id, submitted_at}` or capture retrospective manual bid |
| `POST /api/tenders/<id>/finalise` | Save `{edits, margin, overhead, waste}` and lock estimate |
| `POST /api/tenders/<id>/reopen` | Restore editing without discarding outcome evidence |
| `GET /api/tenders/<id>/completion-documents` | List supporting documents |
| `POST /api/tenders/<id>/completion-documents?name=...` | Raw document, finalised tender only, 1 byte–20 MB |
| `GET /api/tenders/<id>/completion-documents/<document-id>` | Opaque-ID attachment download |

Legacy `/api/settings/update` remains supported for task URLs and preparation,
with explicit-source collection only. CLI `prepare --url` has the same behavior.
Use `--jobs src/web_ui/training_jobs` to show CLI runs in Advanced → History.

## `_4` evaluation preparation and review

The local phase is implemented at the same endpoint-pending boundary as `_3`.
**LoRA settings → Advanced → Evaluation** shows compact outcome/forecast
metrics and persistent candidate reviews. General Settings has no learning controls.
`POST /api/feedback/reviews` prepares from verified prospective snapshots using
the configured model ID. At least 10 bids and both won/lost outcomes are required;
insufficient bundles remain downloadable with blockers.

Runtime `feedback_reviews/<id>/` contains input JSONL, request, manifest and ZIP.
The ZIP exposes only tender IDs, prebid features, input hashes and the response
contract. Labels, evidence references and baseline probabilities stay in local
`reference.json`, outside the inference request. Nothing is sent remotely.

`POST /api/feedback/reviews/<id>/evaluate` imports a candidate response bound to
that review and its exact input hashes/case set. It requires the candidate ID,
verified source provenance, timezone-aware generation dates, an earlier training
cutoff and a complete training-project list excluding every evaluation project.
Results use local frozen labels and baseline forecasts. Corrected/revoked source
outcomes, training overlap, missing cases or integrity failures block import.
Provider lineage is declared evidence until an authenticated provider contract
can verify it. The app cannot establish remote training provenance on its own.

A descriptive Brier comparison uses the existing 0.02 noninferiority margin.
Results/provenance persist across reloads and download through allowlisted
`GET /api/feedback/reviews/<id>/artifacts/<name>`. Review history is available at
`GET /api/feedback/reviews`; legacy external paired-record reviews remain supported.
Passing recommends human review; it never activates, promotes or trains a model.
CLI `feedback prepare-review`, `review`, `productivity` and `revoke-productivity`
share the implementation. `_4/readme.md` documents payloads and commands.

## Cloud training integration still required

Z.ai documents API model ID `glm-5.3-flash`. The official HF weights are
`zai-org/GLM-5.3-Flash`, a multimodal `glm5_next` architecture. A compatible chat
endpoint confirms inference only. It does not confirm a training API, PEFT
support, target modules, the correct chat-template/assistant-loss mask, GPU
capacity, training precision, or adapter loading support.

When the Docker service is supplied, verify its model/framework versions and
connect authenticated file upload, idempotent job creation, status/polling,
cancellation, failure/restart semantics, artifact download and adapter IDs.
Environment variables: `AUTOTENDER_TRAINING_ENDPOINT`,
`AUTOTENDER_TRAINING_API_KEY`. They are never browser-persisted or embedded in
bundles. Mere environment configuration does not activate remote submission.

The generic `train_lora.py` plus `requirements-training.txt` supports optional
compatible causal LMs with assistant-only loss and saved metrics. Its dependency
range and model loader are **not validated for GLM-5.3-Flash**. Do not describe it
as the cloud GLM worker. `--check-only` validates dataset structure, not model
compatibility or GPU readiness. No weights were trained in this workspace.

Before deployment: evaluate held-out extraction/matching quality or measured-factor
error; for bid probabilities use chronological own-bid evaluation, Brier/calibration,
class coverage and comparison with the current heuristic. `_4` candidate review
records evidence and comparisons but does not automatically deploy adapters.

## Primary sources verified

- Model API ID: https://docs.z.ai/guides/vlm/glm-5.3-flash
- Official weights/architecture: https://huggingface.co/zai-org/GLM-5.3-Flash
- simap project and fresh public API collection:
  https://www.simap.ch/de/project-detail/d849c22b-3fc4-48d8-94c9-c45457544ab1
- LoRA implementation reference:
  https://huggingface.co/docs/peft/main/en/task_guides/lora_based_methods

## Verification commands

From repository root:

```sh
python3 -m unittest discover -s src/_3_Prediction/tests -v
python3 -m unittest discover -s src/_4_RecursiveImprovement/tests -v
python3 -m unittest discover -s src/web_ui/tests -p 'test_*.py' -v
python3 src/_3_Prediction/validate.py
python3 src/_2_Calculator/validate.py
# Optional browser environment: playwright + Chromium + PyYAML
python3 src/web_ui/tests/browser_training.py
python3 src/web_ui/tests/browser_lora_settings.py
python3 src/web_ui/tests/browser_feedback.py
```

The browser script starts its own server with temporary storage. It checks real
preparation, preview/split selection, bundle download, blocked sponsor evidence,
invalid/valid uploads, source filtering, run history, tender upload/edit/save,
draft navigation, finalisation/reopening, result corrections, document upload and
download, HTML-safe CSV rendering, dark mode and 1440/900/390px layouts. Runtime data used by the
browser suite is removed afterward. The workspace corpus is read, never modified.

Earlier baseline review: 43 backend tests passed (15 prediction/data, 20 feedback,
8 workspace API), both golden arithmetic checks passed, JavaScript syntax and
Python compilation passed. The real-browser workflow above passed. A live simap
import returned one source with zero errors; GLM-targeted public preparation
returned 38/4/4 with preserved hashes. Dataset-only trainer preflight passed;
remote/model-specific GPU training remains untested and unconnected.

The follow-up UI review also used Ponytail's coding/review skills and an axe-core
4.10.3 browser audit. Checked active/finalised tenders, Settings, Training and
Source library in light/dark themes, plus the mobile outcome form. All ten
checked screens passed the selected WCAG 2 A/AA and 2.1 AA automated rules after
fixing contrast, missing field labels and keyboard access to the positions scroller.
This is an automated check, not a full manual accessibility certification.

The `_4` follow-up adds regressions for preserved downloads/unsaved edits, immutable
export prices, later submission confirmation, retrospective exclusion, measurement
correction/revocation/retry, independent review bundles, input/hash/chronology gates,
source corrections, persistence/restart and reference-label isolation. The second
browser suite imports candidate results, checks review history/downloads and uses
axe when locally available; all evidence in these tests is synthetic and temporary.

Verified after this follow-up: **53 backend tests pass** (16 prediction/data,
28 feedback, 9 workspace API). Both Playwright browser workflows pass. Axe checks
pass for the ten existing screens and three additional candidate-review layouts
(light, dark and mobile). JSON-bound CLI preparation/import, Python compilation,
JavaScript syntax and diff whitespace checks pass. No cloud API calls, model
training or adapter activation were performed; those still require the endpoint.

The simplified Training / Advanced follow-up passes **10 workspace API tests**
and the updated Playwright training workflow. Coverage includes distinct-project
guidance, saved model defaults, exclusion of technical controls from Training,
immediate upload counts, keyboard focus across tabs and direct navigation to a
finalised tender's measurement form. A separate axe/layout check passes all 18
combinations of six training states (empty, ready, more evidence, admin details,
sources and history) in light, dark and 390px mobile layouts. The backend and
browser tests use temporary storage; existing tenders and settings are preserved.

The subsequent task-based LoRA UI review passes `browser_lora_settings.py` and
the updated `browser_training.py`. The new test checks per-task compatibility,
selection persistence, expert fallback, update/create request contents and advanced
configuration, and asserts that no backend writes occur from the preview. All 12
axe/layout combinations of Select LoRAs, Base models, Update LoRAs and Configuration
in light/dark/390px mobile layouts pass. Existing dataset preparation and tender
editing/finalisation/download workflows still pass with their new Advanced navigation.
