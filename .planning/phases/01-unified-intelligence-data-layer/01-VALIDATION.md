# Phase 1 Validation

## Automated Coverage

- Model and normalize: UTC, identity, serialization, tracking parameters, Unicode, tags, invalid data.
- Compatibility: complete `NewsItem`, `RSSItem`, and `AIItem` round trips.
- SQLite: schema/version, PRAGMAs, rollback, provenance, source runs, concurrency, idempotency.
- Adapter: bounds, NewsNow serialization, failure isolation, passive health, partial normalization.
- Deduplicate: cross-source URL, same-source title rules, windows, stable canonical, repeat writes.
- Entrypoints: default adapters, environment rollback, write degradation, projections, imports.
- Backfill: dates, include, dry-run, corrupt/missing databases, AI filtering, second-run zero deltas.

## Commands

```powershell
python -m pytest tests -q
python -m ruff check trendradar/core/models trendradar/core/settings.py trendradar/core/loader.py trendradar/intelligence trendradar/sources trendradar/ai_frontier/fetcher.py trendradar/ai_frontier/translator.py trendradar/ai_frontier/__main__.py trendradar/__main__.py tests/intelligence tests/test_settings.py
python -m pytest tests/baseline/test_storage_compatibility.py -q
python -m trendradar.intelligence.backfill --help
```
