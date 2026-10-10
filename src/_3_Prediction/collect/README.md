The simap collector uses the unauthenticated publication API. It downloads exact raw JSON snapshots, hashes them, and writes normalized public references separately from internal won/lost bids. Public award justification describes the buyer's award decision; it does not prove why Equans lost or create supervised win labels.

From the repository root:

```bash
python src/_3_Prediction/collect/simap.py \
  --url https://www.simap.ch/de/project-detail/d849c22b-3fc4-48d8-94c9-c45457544ab1 \
  --search-hvac --max-pages 5 --max-awards 50
```

Defaults: 2 pages per term and 20 awards; bounds: 10 pages per term, 100 awards, 20 explicit URLs. German Lüftung/HLK and French ventilation queries search separate language indexes; client-side HVAC title filtering avoids unrelated search hits. Page size is controlled by simap (currently 20), using `pagination.lastItem`. This command is a modest sample, not exhaustive historical coverage. To collect more history, invoke `collect_sources` with specific multilingual search terms and a bounded page count, or extend the checked CLI bounds after assessing collection needs. It currently begins at the newest page each run; normalized records merge by publication ID. Failed detail fetches are recorded and can be retried on a later run.

`collect_sources(urls, output_dir, searches=[('Lüftung', 'de')], max_pages=2, max_awards=20)` returns a manifest with `records`, `counts`, `errors`, `market_awards_path`, and `public_tenders_path`. Empty searches collect only explicit sources. Only HTTPS simap project-detail URLs are accepted; credentials, arbitrary ports, query strings, fragments, other hosts and redirects are rejected. All actual requests target fixed public API routes with validated UUIDs.

Outputs: `market_awards.jsonl`, `public_tenders.jsonl`, `collection_manifest.json`, `raw/simap/<sha256>.json`. Provenance carries API URL, public source URL, retrieval timestamp, raw path, hash and attribution. Values retain source VAT treatment; do not compare VAT-inclusive and VAT-exclusive prices without normalization. Multiple listed winners are retained without assuming they are losing bidders. Raw snapshots can contain publication contacts and should remain local, with appropriate retention/access controls.

Requests are spaced by at least one second with 30-second timeouts, an 8 MiB response cap, and three attempts for 429/transient server errors (honoring numeric Retry-After up to 30 seconds). Collection errors are surfaced; they do not generate synthetic records. This is not an official publication. Refer to simap for authoritative notices, corrections and terms: https://www.simap.ch/de/about/legal.

The user-provided project currently has only the tender publication `39697-01` (2026-08-06); it is preserved in `public_tenders.jsonl`, with no invented award or own outcome. This observation is time-dependent and should be refreshed before use.

Offline checks:

```bash
python -m unittest discover -s src/_3_Prediction/tests -p test_simap.py -v
```
