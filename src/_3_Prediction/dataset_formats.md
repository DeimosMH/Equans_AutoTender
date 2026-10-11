Task uploads are UTF-8 JSONL: one JSON object per line, maximum 20 MiB. Every record must include a stable `project_id`; all records for that project stay in the same split. Never use a publication ID for the same project's multiple announcements. Exact duplicate examples are rejected in preparation. Invalid uploads are rejected before storage.

`win_ratio` example (real own bids only):

```json
{"project_id":"own-project-001","source_kind":"own_bid","bid_submitted_at":"2024-01-10T12:00:00+01:00","outcome_observed_at":"2024-03-01T12:00:00+01:00","input":{"sector":"HVAC","canton":"ZH","bid_amount_chf":120000,"cost_amount_chf":108000,"margin_pct":10},"target":{"outcome":"won"}}
```

Allowed win inputs: `sector`, `canton`, `procedure`, `cpv_codes`, `estimated_value_chf`, `bid_amount_chf`, `cost_amount_chf`, `margin_pct`, `evaluation_criteria`, `competition_count_known_at_bid`, `deadline`, `scope`, `publication_date`. Values must reflect facts known when submitting the bid. Outcome must be `won` or `lost`, observed after submission. Public awards do not tell us whether Equans competed or lost. Neither public award winner prices nor award rationales belong in bid inputs. Labels are observed outcomes, never invented probabilities. Data must include both outcomes in the training split, and at least three distinct projects to separate train, validation and test.

`input_processing` example (human-reviewed LV/document extraction):

```json
{"project_id":"own-project-001","reviewed":true,"input":{"document_text":"Reviewed original LV text here"},"target":{"positions":[{"lv_id":"1","quantity":12,"unit":"m"}]}}
```

`productivity_factors` example (measured supervision):

```json
{"project_id":"own-project-001","measurement_reference":"approved time sheet ref 2024-001","input":{"site_type":"school","work_type":"duct installation"},"target":{"site_efficiency":0.9}}
```

Examples illustrate schemas only; do not upload them as actual training evidence. Productivity targets must be positive finite measured factors. Operators are responsible for reviewing measurements and source permissions.

Public simap collection generates a separate `market_extraction` bundle: raw structured API document input with deterministic normalized public metadata targets, retaining source provenance. This is structured metadata extraction, not LV extraction or win prediction. Awards remain separate auditable market observations. Its manifest identifies structured API normalization as the supervision source; downstream training and quality evaluation remain necessary.

Preparation writes `train.jsonl`, `validation.jsonl`, `test.jsonl`, `manifest.json`, `rejected.json`, `training_request.json`; splits use deterministic project grouping and SHA-256 file hashes. Chat JSONL formats are a provider-neutral handoff and may need adaptation once the actual endpoint is known. The future user-provided endpoint is expected to support LoRA job creation, but capability, upload, job polling and adapter-serving contracts remain pending. No external training submission occurs today.

`market_extraction` is a separate UI task. Preparation uses archived API records
with verified raw snapshot hashes, plus any provided simap sources. Sponsor CSV
matching examples are included only in `input_processing`, with one project ID.

New preparation bundles also include `examples.json` (split/line/project and source
evidence mapping) and `dataset_bundle.zip`. Provenance stays outside model inputs.
Cloud training must keep `test.jsonl` held out, as declared in the request.
