# Bid scenarios and training preparation

`predict.py` enriches calculator JSON with `recommended_bid_range`. Run
`python3 src/_3_Prediction/predict.py --calc path/to/calc.json` from the repository root.
`AUTOTENDER_CALC_OUT` also selects the calculator output. `--params` selects project parameters.
The web server runs this enrichment after calculator recomputation and exposes
`GET /api/tenders/<id>/wincurve?baseline=<current CHF baseline>` for unsaved UI changes.

The current serving method is **heuristic, untrained and uncalibrated**. It uses the
existing `stretch_bid_optimization` parameters. Commercial bids are rounded upward
to `commercial.round_to_chf`; the reference bid is the unrounded baseline divided
by `(1-target margin)`. Expected contribution uses the full heuristic probability,
while scenario `estimated_win_probability` is rounded to two decimal places for
compatibility with the golden example. The curve uses the full probability.
Sensitivity bands are +/-5 percentage points, clamped to configured bounds; they
are illustrative parameter variations, not statistical confidence intervals.
No training job, LoRA selection or API response currently changes these numbers.

`python3 src/_3_Prediction/validate.py` checks the golden subset arithmetic,
monotonicity, probability bounds, invalid baselines and disabled mode. The UI shows
three configured margin presets, live heuristic estimates and expected contribution.
Unavailable predictions are shown as unavailable, with no fabricated fallback.

Historical public awards can support structured extraction datasets; they alone
cannot label whether our company lost a bid or expose our private cost baseline.
Our bid outcomes must come from verified internal bid records. Award price,
winner, post-award bidder count and debrief reasons are label/context fields,
never pre-bid win-prediction features. Existing context_agent reports are research
notes, not authoritative implementation specifications: their proposed award-price
ratios leak outcomes and their example LLM probability targets are invented.

## Collection and dataset preparation

See [collector usage](collect/README.md) and [task JSONL schemas](dataset_formats.md).
LoRA training → Datasets → Prepare dataset starts a tracked preparation job, polls progress and
provides downloadable JSONL, manifests and the training handoff. The Source library collects explicit project URLs; historical award search is
an opt-in checkbox. A URL alone does not launch additional searches. Public
notice extraction is offered as a separate auxiliary zip; it does not label own bids.

The current workspace contains 45 real market awards and the provided tender,
with source snapshots in `data/` (generated, gitignored). Rebuild/extend through
`collect/simap.py`. Prepare the entire archived corpus without additional requests:

```sh
python3 src/_3_Prediction/prepare_market.py --base-model glm-5.3-flash
python3 src/_3_Prediction/prepare_sponsor.py --base-model glm-5.3-flash
```

The provider model ID is configurable; `glm-5.3-flash` is the requested default.
The official weight repository uses `zai-org/GLM-5.3-Flash`. Market metadata extraction currently has
38 train / 4 validation / 4 test examples. Sponsor materials produce 22 reviewed
catalogue-matching examples with PDF provenance, all from one project: its manifest
is blocked pending independent validation/test projects. These matching examples
use sponsor CSV descriptions, not assumed physical PDF page alignment. The Tender matching task can load these sponsor examples directly.

## Local LoRA training and future endpoint

Install `requirements-training.txt` in a separate environment with hardware sized
for your actual base model. Run the dependency-free preflight first:

```sh
python3 src/_3_Prediction/train_lora.py --model <actual-model-id> \
  --train src/_3_Prediction/output/market_extraction/train.jsonl \
  --validation src/_3_Prediction/output/market_extraction/validation.jsonl \
  --output /path/to/new-adapter --check-only
```

For a compatible generic causal LM, remove `--check-only` to train locally.
The local trainer and dependency versions are not a validated GLM-5.3 runtime;
that multimodal model is intended for the user-managed cloud Docker provider. The trainer uses LoRA, assistant-only loss,
held-out validation and saved adapter metrics/provenance; it never activates weights.
Local GPU training has not been run here. Evaluate the held-out test file separately
before deployment. Market extraction evaluation is a structured JSON accuracy task;
win probabilities require verified own bid labels and calibration beyond token loss.

The intended provider will run in cloud Docker. Its LoRA job API contract and
endpoint are pending. `training_request.json` provides data hashes, files, task/base
model and required completion/evaluation fields. Configuring environment variables
alone does not submit anything: provider file upload, create/poll/download and
adapter-serving routes must be connected once their contract is known.

Validation:

```sh
python3 -m unittest discover -s src/_3_Prediction/tests -v
python3 src/_3_Prediction/validate.py
python3 src/_2_Calculator/validate.py
```

The repository-wide authoritative handoff is [PROJECT_CONTEXT.md](../../PROJECT_CONTEXT.md).

## Integrated CLI and existing sources

`python3 src/autoTender.py calculate --positions <csv> --output <json>` runs all
four calculator steps followed by prediction. `--factors <json-file>` supplies
productivity overrides.

`python3 src/autoTender.py prepare --task market_extraction --base-model <model-id>`
prepares the archived real corpus through tracked jobs without network access.
The same workflow is available in LoRA training → Public notices.
The existing-evidence checkbox is checked by default for public notices and
sponsor matching; uncheck it to prepare from uploads only. The CLI equivalent
is `--exclude-existing`. Add `--url <simap-project-url>` for fresh bounded collection.
Use `--jobs src/web_ui/training_jobs` to make CLI job artifacts appear in Run history.
The sponsor input-processing dataset remains one project and does not acquire
win/loss labels simply because the public corpus is included.

New jobs include `dataset_bundle.zip` and hashed `examples.json` evidence mapping.
See the unified context for the review APIs and cloud integration boundary.
