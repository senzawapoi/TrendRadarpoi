# Phase 3 Validation Strategy

## Automated Coverage

- Source fixtures: CISA and NVD contract parsing, CVSS precedence, pagination, caps, errors, RSS.
- Normalize: UTC, exact CVE extraction, canonical official URL, security metadata and observations.
- Story: exact shared-CVE cross-source/cross-window joins, conflict isolation, stable incremental ID.
- Analyze: severity, KEV, due/action weighting, reasons, missing metadata, deterministic ordering.
- Freshness/report: current and last-success runs, stale status, escaping, evidence, empty output.
- Integration: switches, config precedence, one fetch, source/report failure isolation, no refetch,
  legacy schema/report/notification preservation, and idempotent SQLite writes.

## Commands

```powershell
python -m pytest tests/intelligence -q
python -m pytest tests -q
python -m ruff check trendradar/core/models/content.py trendradar/core/settings.py trendradar/core/loader.py trendradar/domains trendradar/sources/security.py trendradar/intelligence trendradar/__main__.py tests/intelligence tests/test_settings.py
python -m compileall -q trendradar mcp_server
```

