# Unified AutoTender context

Updated 2026-10-10. Start here for future work. This file supersedes conflicting
assumptions in the six `context_agent_*` research reports; those remain research history.

## Product and module boundaries

Equans AutoTender assists a human estimator with ventilation tenders (BKP 244),
source traceability, catalogue/supplier matching, labour costs and indicative bids.
It does not autonomously submit offers. `materials/README.md` defines the challenge;
`materials/expected_output_example.json` defines verified example arithmetic.

- `_1_AI_InputProcessing`: proposed PDF segmentation, extraction and catalogue matching.
  Currently research/todo only. PDF upload stores the document; it does not extract LV positions.
- `_2_Calculator`: implemented four-step material/labour/direct/project cost pipeline.
  Uses Decimal half-up money rounding, YAML settings, catalogue/productivity tables,
  project parameters and per-tender `AUTOTENDER_CALC_OUT` output.
- `_3_Prediction`: implemented public collection, supervised dataset preparation,
  persisted preparation jobs, provider handoff and heuristic bid scenarios.
- `_4_RecursiveImprovement`: research/todo only. Future verified debriefs feed own-bid
  labels and measured productivity; there is no automatic retraining/deployment loop yet.
- `web_ui`: localhost stdlib HTTP server; persistent independent tender folders,
  positions CSV upload, editable calculations, margin/waste/overhead controls,
  PDF/HTML/DOCX offers and settings. Start `python3 src/web_ui/server.py 8080`.
- `src/autoTender.py`: implemented CLI with `calculate` (four calculator steps plus
  prediction) and `prepare` (tracked task datasets, existing corpus/sponsor sources).

Dependencies: Python with PyYAML for the calculator; prediction, collection,
preparation and UI otherwise use the standard library. Optional local training
uses PyTorch, transformers, PEFT and accelerate in a separate training environment.
No GLM credential from the conversation is written into project files or required.
Research search engine: `http://127.0.0.1:8888/search?q=...&format=json` (SearxNG).
Search availability/results vary; primary documentation and live API probes take precedence.

## Corrected assumptions

1. Public simap announcements disclose tenders and awards, not all losing bids or
   Equans's participation, costs or reasons for losing. Never synthesize own losses
   by assuming everybody except the published winner bid and lost.
2. The supplied project `d849c22b-3fc4-48d8-94c9-c45457544ab1` currently has tender
   publication `39697-01`, dated 2026-08-06, and no award. It is a real source example,
   not a won/lost training label.
3. Post-award winner price, actual bidder count and debrief reasons are unavailable
   when bidding. They must not be prediction inputs for that same bid. Historical
   priors require a temporal cutoff. The old proposed ratio of our price to the
   eventual award price is target leakage.
4. Binary confirmed outcomes train outcome classification, not a fabricated numeric
   probability target. LLM classification output is not automatically calibrated.
5. Public structured extraction examples train public notice extraction; they do not
   teach full LV/PDF segmentation or catalogue matching without reviewed LV examples.
6. Measured productivity labels need evidence. Existing AI productivity suggestions
   remain editable demo defaults and are not output of a trained adapter.
7. A chat/completions endpoint does not imply LoRA training or adapter loading support.
   Friendly UI model names are not guaranteed provider or Hugging Face model IDs.
8. Dataset readiness, completed training, evaluation and deployment are distinct.
   Preparing a dataset never creates or selects a working LoRA version.
9. Golden scenario arithmetic uses the example subset baseline. Live UI predictions
   use the full project baseline, including services/allowances; those are different.

## Serving contract and commercial arithmetic

Calculator flow: positions -> material and labour -> position direct costs ->
project services/allowances -> overhead baseline -> selling price. Margin is gross
margin on selling price, not markup: `price = baseline / (1 - margin/100)`.
Commercial scenario bids round upwards to configured `commercial.round_to_chf`.
Expected contribution is full-precision heuristic P(win) times (bid minus baseline).
Displayed probabilities round to two decimals; calculating contribution from the
rounded display probability will not reproduce the golden example exactly.

`_3_Prediction/predict.py` enriches `calc.json.recommended_bid_range` after UI
recalculation and edits. `GET /api/tenders/<id>/wincurve?baseline=<CHF>` supports live
unsaved cost changes; margin movement interpolates the materialized curve locally.
Three configured scenarios include price, margin, estimated win probability and
expected contribution. Model metadata says heuristic/untrained/uncalibrated.
The min/mid/max probability band is +/-5 percentage point sensitivity, bounded by
configured limits, not a statistical confidence interval. Scenario presets choose
low/medium/high margins. No selected adapter currently changes prediction serving.
Unavailable predictions display unavailable rather than old fabricated demo odds.

## Public collection

Use `_3_Prediction/collect/simap.py` for reproducible bounded collection.
Public API: `https://www.simap.ch/api/publications/v2/project/project-search`
(GET, language-specific search, `lastItem` pagination), project headers and
`/api/publications/v1/project/{projectId}/publication-details/{publicationId}`.
Use German and French vocabulary; searching French terms with `lang=de` misses records.
Collector archives raw responses, identifiers, source URLs, timestamps and hashes,
normalizes public tender/award records, preserves null unknowns and deduplicates.
Bounded requests, retries, timeouts and approved simap URLs protect the local tool.
Public data remains separate from own-bid supervision. Raw snapshots and generated
runtime corpora are workspace artifacts, ignored by git.

## Dataset and training workflow

Settings upload accepts validated UTF-8 JSONL task records, not arbitrary PDFs or
CSV pretending to be training data. Each record requires `project_id`, `input` and
`target`; schema examples and commands are in `_3_Prediction/readme.md`.
Win records require own_bid provenance, submission/outcome chronology and confirmed
won/lost labels; only pre-bid allowed features enter prompts. Productivity records
need positive finite measured factors and a measurement reference. Input extraction
records need reviewed supervision. Public API extraction is a separate auxiliary task.

`dataset.py` deduplicates, groups by project, deterministically splits train,
validation and test, writes chat messages JSONL, rejected reasons and manifest
counts/hashes. Small data remains blocked pending independent held-out projects;
win training additionally requires both classes in the training partition.
These are structural checks, not evidence of enough data for a useful trained model.
Before deployment use chronological held-out evaluation, Brier/calibration for
probabilities, task accuracy and comparison against the heuristic baseline.

Settings Update starts an asynchronous persisted preparation job. UI polls status
and offers artifacts. Restarted unfinished jobs fail explicitly; failures never
register a successful model. Training request bundles declare dataset hashes,
base-model/task requirements and awaiting endpoint configuration. No external
training submission occurs without a provider implementation and capability contract.

`train_lora.py` provides optional actual local PEFT causal-LM LoRA training with
assistant-only loss, held-out validation, deterministic seed and saved adapter/
metrics/provenance. It requires an explicit compatible Hugging Face identifier,
chat template and sufficient hardware; no remote model code is enabled. `--check-only`
validates files without training dependencies. Output is `trained_unvalidated`,
never automatically promoted. Tokenizer template mismatch or wholly truncated
answers stop training. GPU execution has not been validated in this workspace.

The user confirms the future endpoint will support LoRA job creation (probably
OpenAI-compatible), but its exact contract is unavailable. The endpoint must specify: inference vs training routes, provider model IDs,
authentication, file upload requirements, job status/cancellation, adapter artifact
or model identifiers, supported LoRA configuration and evaluation metadata.
Environment names in the handoff: `AUTOTENDER_TRAINING_ENDPOINT` and
`AUTOTENDER_TRAINING_API_KEY`; values are not UI-persisted or embedded in artifacts.

## Primary sources checked

- [simap project](https://www.simap.ch/de/project-detail/d849c22b-3fc4-48d8-94c9-c45457544ab1)
  and live public JSON APIs: supplied project/tender and historical awards verified.
- [simap legal/API terms](https://www.simap.ch/de/about/legal): collection attribution
  and correction obligations should accompany downstream redistribution.
- [Hugging Face PEFT LoRA](https://huggingface.co/docs/peft/main/en/task_guides/lora_based_methods):
  LoRA configuration and adapter training APIs.
- [OpenAI supervised fine-tuning](https://developers.openai.com/api/docs/guides/supervised-fine-tuning):
  current documentation says the fine-tuning platform is winding down and inaccessible
  to new users. An OpenAI-compatible third-party provider can have different capabilities.

## Validation and remaining boundaries

Golden scenario and calculator regression checks, offline collection/dataset/job
tests, Python compilation, JavaScript syntax and localhost API smoke checks are
used for this implementation. See `_3_Prediction/readme.md` for commands.
No empirical calibrated predictor, actual trained weights, full PDF extraction,
recursive debrief implementation or remote training provider is claimed.

## Completed workspace data and checks

- `src/_3_Prediction/data/collection_manifest.json`: 45 distinct real awards, one
  supplied tender, zero collection errors, 62 raw snapshots. Awards span
  2026-06-24 to 2026-10-10; five are French. All 45 have bidder counts; 44 have prices.
  This bounded sample is not the complete historical simap corpus.
- `src/_3_Prediction/output/market_extraction/`: 38 training / 4 validation / 4 test
  structured notice normalization examples with provenance and training request.
- `src/_3_Prediction/output/sponsor_matching/`: 22 sponsor-reviewed catalogue-matching
  examples, one project, blocked on independent held-out projects. `prepare_sponsor.py`
  preserves the supplied PDF hash and avoids inventing extraction supervision.
  Spot checking physical PDF page 78 shows equipment different from the CSV's
  page-78 valve rows; review page alignment before using PDF pages as labels.
- 13 offline collection/dataset/job tests passed, both golden regressions passed,
  Python compilation and JavaScript syntax passed. Isolated localhost API smoke
  test covered settings, async jobs, artifact downloads, tender creation, full
  recalculation and overridden-baseline win curves. Optional trainer preflight
  passed on the real public extraction training/validation files.

## Follow-up implementation

The Settings page includes a separate Public notice extraction task and a checked
“Use collected data and sponsor examples” option. Existing market records are
merged/deduplicated with optional fresh collection; raw source hashes are verified.
Sponsor matching examples are loaded directly for Input processing without manual
re-upload. Public evidence never fills own-bid outcomes or measured productivity.
Two real persisted UI jobs were prepared from gathered workspace data: notice
extraction ready for training, sponsor matching blocked on held-out projects.
No external provider is needed for these preparation and calculator flows.

CLI examples from repository root:

```sh
python3 src/autoTender.py calculate --output /tmp/calculation.json
python3 src/autoTender.py prepare --task market_extraction --base-model <provider-model-id>
```

Use `--exclude-existing` to prepare only uploaded data/new URL sources; use
`--jobs src/web_ui/training_jobs` to expose CLI-prepared artifacts in Settings.
The CLI returns nonzero on preparation failure; a blocked dataset remains a
valid preparation result and carries explicit blockers. Remote upload/training
and inference remain pending the actual endpoint contract.
