# Outcome feedback and recursive improvement

`_4` turns verified outcomes and measured productivity into `_3` training evidence.
The local workflow, evaluation packages and review history are implemented. Cloud
execution, calibration of a trained model and adapter activation await the Docker
service's API contract. The serving predictor remains the current heuristic.

## Tender workflow

1. **Download an offer** in PDF, HTML or Word. Pending position edits are saved.
   `feedback/offers/<id>.json` freezes the calculation, commercial choices,
   descriptions, bid amount and forecast with a SHA-256 digest. Identical downloads
   reuse the snapshot. A download alone does not claim the bid was submitted.
2. **Tender finalised** saves the estimate and opens the outcome form at the top.
   Choose the downloaded offer actually submitted and enter its submission date.
   The price is taken from that snapshot. Alternatively, enter another offer's
   price and date; this retrospective entry supports reporting but not win training.
3. Record won/lost/withdrawn, result date and supporting documents. Verify the
   outcome against an evidence reference before it can become a training label.
   Optional decision details include confirmed reasons and comparable CHF prices.
4. Save corrections through revision checks. Reopening enables estimation again
   and retains submission/outcome evidence. The confirmed submission is immutable.
5. Download the outcome report. Public simap notices can be imported separately;
   multiple imports preserve earlier evidence. Collection failure does not prevent
   a report explaining the information that remains missing.

An eligible submission must come from an offer preserved before completion,
submitted on or after preservation, and observed before its verified result. Offers
first downloaded after finalisation or outcome recording cannot become prospective
training evidence. A submission initially captured through the legacy API is only
prospective if its date is within five minutes of capture and it is not marked
retrospective. All timestamps include time zones.

Public awards never prove our participation or defeat. Award prices are compared
only when the user confirms the same scope, CHF currency and VAT basis. Price gaps
do not establish why a bid lost. Confirmed debrief reasons remain attributed to
supplied evidence. Reports include our bid, chronology, evidence, missing information
and readable price comparisons, in Markdown/HTML/PDF.

Eligible results export to `uploads/lora_data/win_ratio_feedback_<id>.jsonl`.
Only frozen prebid features enter the prompt. Submission hash, outcome revision,
evidence reference and chronology survive separately in `_3`'s `examples.json`.
Corrections replace the stable export; withdrawal or revoking verification removes
it. Deleting a tender removes its current outcome/productivity exports too.
Previously prepared datasets and reviews remain historical artifacts: prepare new
ones after corrections. Nothing trains automatically.

## Productivity evidence

**Actual productivity** inside the finalised tender accepts measured factors and a
verified timesheet/measurement reference. Values reload for editing. Corrections
have archived revisions and stale edits are rejected. **Exclude from learning**
retains the measurement/audit record while removing the current training export.
Re-verifying and saving restores it. A retry repairs a missing export without
creating a new measurement revision.

The stable export is `productivity_factors_feedback_<id>.jsonl`. Measurements never
change active calculator factors; those remain editable in Settings. Historical
prepared datasets are not silently rewritten after measurement corrections.

## Monitoring and candidate review

Open **Settings → Learning from completed tenders**. The collapsed workspace shows
verified wins/losses, saved forecasts and Brier error (lower is better). The monitoring
API also exposes calibration bins, signed bias, comparable competitor prices and
two-sided Page-Hinkley diagnostics. Retrospective captures are excluded from forecast
quality. The existing parameters (`minimum_instances=10`, `threshold=8`, `delta=.005`,
`alpha=.9999`) are diagnostic choices, not validated calibration guarantees.

**Prepare review** persists a package under the runtime `feedback_reviews/<id>/`:

- `evaluation_inputs.jsonl`: tender IDs, frozen prebid inputs and input hashes.
- `evaluation_request.json`: intended model, pending transport, exact response
  shape and training exclusion/cutoff requirements. Status remains `not_submitted`.
- `manifest.json`: count, blockers and hashes of public handoff artifacts.
- `handoff.zip`: those three files only. Reference outcomes, evidence references
  and current forecast scores remain local in `reference.json`.

At least ten eligible bids and both outcomes are needed for a review. An insufficient
package is still downloadable with explicit blockers, like `_3` dataset preparation.

Once the model runs externally, use **Import results**. The JSON must identify the
review and candidate model, contain verified source/training provenance, and return
exactly one finite probability and matching input hash per tender. The request file
is the authoritative schema. Local labels and baseline scores supply the comparison;
labels uploaded by the candidate are not trusted.

A historical backtest requires a complete `trained_project_ids` list without any
evaluation projects and a training cutoff before every evaluated submission. An
already-trained candidate cannot use bids that contributed to its training as a
held-out test. Generation timestamps must include a timezone and cannot be in the
future. Source verification is an explicit assertion; the app cannot independently
prove a remote provider's training lineage before that contract exists.

Changed/revoked outcome evidence or damaged artifacts block result import. A valid
review persists its response, paired scores and recommendation, survives reloads,
and has a downloadable result. Retries are idempotent. A different candidate needs
a new review. Comparison uses a descriptive Brier noninferiority margin of 0.02;
passing recommends human review, not statistical significance or model activation.
Old completed reviews describe the evidence as evaluated at that time.

## API

| Endpoint | Function |
|---|---|
| `POST /api/tenders/<id>/offers` | Save `{edits, margin, overhead, waste}` and freeze an offer |
| `GET /api/tenders/<id>/pdf?offer=<offer-id>&format=pdf\|html\|docx` | Export frozen offer values |
| `POST /api/tenders/<id>/submission` | Confirm `{offer_id, submitted_at, bid_amount_chf?}`; legacy capture also supported |
| `POST /api/tenders/<id>/outcome` | Save revision, analyze and export eligible evidence |
| `POST /api/tenders/<id>/gather-evidence` `{urls:[]}` | Collect 1–20 public simap project URLs |
| `POST /api/tenders/<id>/export-feedback` | Rebuild eligible own-bid export |
| `POST /api/tenders/<id>/productivity-feedback` | Record verified measured factors |
| `POST /api/tenders/<id>/revoke-productivity` `{expected_revision}` | Remove current measurement export |
| `GET /api/tenders/<id>/feedback` | Offers, submission, outcome, measurement, analysis, evidence, export |
| `GET /api/tenders/<id>/postmortem?format=md\|html\|pdf` | Outcome report |
| `GET /api/feedback/monitoring` | Aggregate outcomes and diagnostic forecasts |
| `POST /api/feedback/reviews` `{}` | Prepare evaluation handoff for configured model |
| `GET /api/feedback/reviews` | Persistent review history |
| `GET /api/feedback/reviews/<id>` | Review and result |
| `GET /api/feedback/reviews/<id>/artifacts/<name>` | Allowlisted, integrity-checked download |
| `POST /api/feedback/reviews/<id>/evaluate` | Import results against frozen local references |
| `POST /api/feedback/evaluate` `{records:[]}` | Legacy externally supplied paired review; archived as external |

Outcome payload: `{outcome, observed_at, verified, evidence_reference, reason_codes?,
reasons_confirmed?, narrative?, award_price_chf?, award_price_comparable?, winner?,
competitors?, expected_revision?}`. Competitors use `{name, price_chf, currency,
comparable}`. Productivity payload: `{verified:true, measurement_reference,
input:{...}, target:{factor:value}, expected_revision?}`. The UI always includes
revision expectations. JSON requests are limited to 5 MB.

## CLI and validation

From repository root:

```sh
python3 src/autoTender.py feedback submission --folder src/web_ui/tenders/<id> --data submission.json
python3 src/autoTender.py feedback outcome --folder src/web_ui/tenders/<id> --data outcome.json
python3 src/autoTender.py feedback gather --folder src/web_ui/tenders/<id> --data links.json
python3 src/autoTender.py feedback analyze --folder src/web_ui/tenders/<id>
python3 src/autoTender.py feedback export --folder src/web_ui/tenders/<id>
python3 src/autoTender.py feedback productivity --folder src/web_ui/tenders/<id> --data measurement.json
python3 src/autoTender.py feedback revoke-productivity --folder src/web_ui/tenders/<id> --data revision.json
python3 src/autoTender.py feedback monitor --folder src/web_ui/tenders
python3 src/autoTender.py feedback prepare-review --folder src/web_ui/tenders --base-model glm-5.3-flash
python3 src/autoTender.py feedback review --folder src/web_ui/tenders --review-id <id> --data results.json
python3 -m unittest discover -s src/_4_RecursiveImprovement/tests -v
python3 src/web_ui/tests/browser_feedback.py
```

`--reviews` changes the CLI review store; its default shares the UI history.
The server's `AUTOTENDER_UI_DATA_DIR` isolates reviews along with other runtime
state. File locking uses Unix `fcntl`, matching the Linux/local usage model. Test
outcomes are synthetic and isolated; no real tender outcomes were fabricated.
See [PROJECT_CONTEXT.md](../../PROJECT_CONTEXT.md) for the unified handoff.
