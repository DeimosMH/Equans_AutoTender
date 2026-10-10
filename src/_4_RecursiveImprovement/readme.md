# Outcome feedback and recursive improvement

`_4` connects reviewed bid outcomes and measured productivity to `_3`'s dataset
preparation. It preserves evidence, reports missing information and monitors frozen
forecasts. It does not automatically train, modify catalogue prices or promote models.

## Tender workflow

1. Calculate/save the tender. In **Bid outcome and learning**, record submission
   before its outcome. A locked, immutable `feedback/submission.json` captures the
   saved calculator, parameters, bid, actual margin and prediction with a SHA-256
   digest. Later recalculation/edits never rewrite this snapshot. UI capture requires
   saved positions and default overhead/waste. A manually entered bid overrides the
   calculated bid; actual margin and heuristic probability use that bid.
2. Record won/lost/withdrawn, observed timestamp and evidence reference. Confirm the
   own-bid outcome explicitly before exporting it. Add evidence-backed reason codes,
   optional comparable CHF award/competitor prices and a narrative. Outcomes have
   archived revisions and an audit trail. Expected revisions protect concurrent edits.
3. Optionally gather public evidence from HTTPS simap project-detail URLs. The `_3`
   collector archives notices and reports collection errors. It never infers that our
   company participated or lost. Unknown losing bids/reasons remain unknown.
4. Analysis describes price differences and quote completeness, distinguishes
   confirmed/unconfirmed reasons, and generates Markdown/HTML reports even when
   evidence is incomplete. The UI also exports a PDF using the existing PDF painter.
5. Eligible own outcomes export to the stable file
   `uploads/lora_data/win_ratio_feedback_<tender-id>.jsonl`. It uses only frozen
   prebid inputs and the `_3` schema. Corrections replace the record; withdrawing or
   revoking verification removes its prior export. Prepare a new dataset in Settings
   to incorporate updated feedback. Previously prepared datasets remain historical
   artifacts and must not be treated as the latest corrected labels.

Snapshots backdated more than five minutes are marked retrospective and cannot
produce training labels or forecast-quality metrics. Outcomes observed before
snapshot capture are also excluded from training. Existing sponsor/public data is
not automatically upgraded into verified bid outcomes. No real outcomes were invented
for this implementation; synthetic outcomes are confined to automated tests.

Reason codes: `price`, `technical_score`, `references`, `capacity`, `compliance`,
`delivery`, `relationship`, `other`, `quality`, `withdrawal`. A higher comparable bid
price is a descriptive observation, not proof that price caused the loss.
All prices require consistent scope/currency/VAT basis to be marked comparable.

## Productivity evidence

The tender panel accepts JSON values for configured factors, a verified measurement
and a measurement reference. `productivity.py` validates and exports a stable
`productivity_factors_feedback_<tender-id>.jsonl` record. Measurements do not alter
active calculator factors. Users can still edit active factors through Settings.
Measurements have atomic persistence and audit history; one latest record per tender
is exported. Review measurements before using them as supervision.

## Monitoring and candidate evaluation

Settings → Feedback monitoring aggregates verified outcomes chronologically from
submission/outcome artifacts. It checks snapshot integrity and revision linkage;
reports Brier score, signed calibration bias (`p - y`) and calibration bins only
for prospectively frozen probabilities; and computes descriptive per-competitor
price medians from explicitly comparable CHF evidence.

The two-sided drift check runs two one-sided Page-Hinkley detectors on signed error
and its negative (`minimum_instances=10`, `threshold=8`, `delta=.005`, `alpha=.9999`).
These are application parameters, not empirically validated guarantees. Alerts
recommend calibration, retraining and rollback review; they never change adapters.
The current heuristic remains the serving fallback, with its existing uncalibrated
metadata. With no trained/evaluated adapters, there is no working adapter to switch.

Settings → Candidate evaluation accepts a JSON array (or `{"records": [...]}`)
containing paired held-out forecasts. Example schema (illustrative, not real evidence):

```json
{
  "tender_id": "example",
  "submitted_at": "2026-01-10T12:00:00Z",
  "observed_at": "2026-02-10T12:00:00Z",
  "outcome": "lost",
  "outcome_verified": true,
  "evidence_reference": "confirmed award letter",
  "champion_probability": 0.6,
  "candidate_probability": 0.5,
  "prediction_provenance": {
    "source": "provider evaluation",
    "verified": true,
    "model_id": "actual-candidate-id",
    "generated_at": "2026-01-10T11:00:00Z",
    "evaluation_mode": "prospective"
  }
}
```

At least ten paired outcomes, both classes, finite probabilities, one candidate
identifier and verified provenance are required. Invalid rows block the review.
Prospective forecasts must precede submission. `historical_backtest` requires a
training cutoff preceding submission and an explicit `trained_project_ids` list
with no evaluation overlap. The sample-mean Brier noninferiority margin is 0.02.
Passing recommends human review, not statistical significance, training success
or promotion. API review results are archived in module `output/evaluations/`.
Remote training/adapter evaluation and deployment need the future provider contract.

## API

| Endpoint | Function |
|---|---|
| `POST /api/tenders/<id>/submission` | Freeze saved calculation and bid |
| `POST /api/tenders/<id>/outcome` | Save revision, analyze, export eligible feedback |
| `POST /api/tenders/<id>/gather-evidence` `{urls:[]}` | Collect public notices |
| `POST /api/tenders/<id>/export-feedback` | Rebuild eligible own-bid upload |
| `POST /api/tenders/<id>/productivity-feedback` | Record verified measured factors |
| `GET /api/tenders/<id>/feedback` | Submission, outcome, analysis, evidence, export |
| `GET /api/tenders/<id>/postmortem?format=md\|html\|pdf` | Review report |
| `GET /api/feedback/monitoring` | Aggregate outcomes and diagnostic forecasts |
| `POST /api/feedback/evaluate` `{records:[]}` | Paired candidate review, no promotion |

Submission payload: `{submitted_at, margin_pct, bid_amount_chf?, prebid_context?}`.
Prebid context uses `_3/dataset.py`'s feature allowlist. Outcome payload:
`{outcome, observed_at, verified, evidence_reference, reason_codes?, reasons_confirmed?,
narrative?, award_price_chf?, award_price_comparable?, winner?, competitors?, expected_revision?}`.
Competitors use `{name, price_chf, currency, comparable}`. Productivity payload:
`{verified:true, measurement_reference, input:{...}, target:{factor:value}}`.

## CLI and validation

Run from repository root:

```sh
python3 src/autoTender.py feedback submission --folder src/web_ui/tenders/<id> --data submission.json
python3 src/autoTender.py feedback outcome --folder src/web_ui/tenders/<id> --data outcome.json
python3 src/autoTender.py feedback analyze --folder src/web_ui/tenders/<id>
python3 src/autoTender.py feedback gather --folder src/web_ui/tenders/<id> --data links.json
python3 src/autoTender.py feedback export --folder src/web_ui/tenders/<id>
python3 src/autoTender.py feedback monitor --folder src/web_ui/tenders
python3 src/autoTender.py feedback evaluate --data paired_predictions.json
python3 -m unittest discover -s src/_4_RecursiveImprovement/tests -v
```

Runtime artifacts live in gitignored tender feedback folders/module output. File
locking uses Unix `fcntl`, consistent with the Linux local tool environment; the
feedback persistence layer requires adaptation for Windows.
The root [PROJECT_CONTEXT.md](../../PROJECT_CONTEXT.md) is the unified handoff.

References checked: [River Page-Hinkley documentation](https://riverml.xyz/latest/api/drift/PageHinkley/),
[reference recurrence](https://github.com/scikit-multiflow/scikit-multiflow/blob/master/src/skmultiflow/drift_detection/page_hinkley.py),
[scikit-learn data leakage guidance](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage).
