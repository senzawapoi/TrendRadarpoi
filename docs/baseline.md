# Phase 0 Runtime Baseline

This baseline records the behavior that configuration and architecture work must preserve. Run all
commands from the repository root with Python 3.10 or newer.

## Runtime Entry Points

These commands are production entry points and may access public APIs, feeds, configured providers,
or long-running transports. They are documented here but are not used by the offline test suite.

```powershell
python -m trendradar
python -m trendradar.ai_frontier
python -m mcp_server.server --transport stdio
```

The main crawler reads `config/config.yaml` by default and persists date-partitioned databases under
`output/news/` and `output/rss/`. AI Frontier defaults to `output/ai_frontier.db`.

Phase 1-5 extends the default-on unified path at `output/intelligence.db`. The legacy databases above
remain authoritative for current reports, notifications, and MCP; see [intelligence.md](intelligence.md)
for canonical, Story, Security, Assistant, Feishu, rollback, and backfill contracts. The opt-in
`python -m trendradar.integrations.feishu` runner is separate from the three legacy entry points.
Its `--check` mode validates configuration without opening SQLite or connecting to providers.

## Offline Verification

```powershell
python -m pytest tests/baseline -q
python -m pytest tests -q
python -m ruff check tests/baseline
```

The entrypoint checks only import modules and inspect public callables. The storage checks create real
SQLite databases exclusively under pytest's `tmp_path`, assert the current tables and uniqueness
contracts, close all connections, and never write to `output/`.

## Compatibility Contract

- Main news tables: `platforms`, `news_items`, `title_changes`, `rank_history`, `crawl_records`,
  `crawl_source_status`, and `push_records`.
- RSS tables: `rss_feeds`, `rss_items`, `rss_crawl_records`, `rss_crawl_status`, and
  `rss_push_records`.
- Main uniqueness: non-empty `(url, platform_id)` for news and `(url, feed_id)` for RSS.
- AI Frontier uniqueness: `(source, url)`; a repeated upsert updates the existing row.
- Default paths and schemas remain unchanged during Phase 0.

## Recorded Result

Before Phase 0 additions on 2026-08-21, `python -m pytest tests -q` completed with `91 passed`.
After adding the five offline characterization cases, the same command completed with
`96 passed, 1 warning in 1.33s`. The warning is an upstream OpenTelemetry deprecation warning
raised while importing FastMCP; no test failed and no network or server process was started.

After the unified settings migration and its compatibility coverage, the Phase 0 closeout run
completed with `111 passed, 1 warning in 1.45s`. Changed-scope Ruff, runtime entrypoint imports,
environment-file tracking checks, and the single-loader `yaml.safe_load` assertion also passed.

## Phase 1 Compatibility Checkpoint

The Phase 0 numbers above are retained as historical evidence. After Phase 1 introduced canonical
models, adapters, deduplication, unified storage, rollback, and backfill coverage, the full suite
completed with `153 passed, 1 warning`. Changed-scope Ruff, offline imports, YAML parsing,
`backfill --help`, and legacy SQLite schema checks also passed. Tests keep generated databases under
`tmp_path`; a normal verification run must not leave `output/intelligence.db` behind.

## Phase 2 Verification Checkpoint

Phase 2 adds deterministic clustering, stable incremental Stories, explainable Importance ranking,
an additive Story report, and best-effort integration for normal ingestion and historical backfill.
The closeout run completed with `208 passed, 1 warning`. Changed-scope Ruff, compilation, YAML and
plan parsing, backfill CLI help, rollback checks, and the cross-source chronological backfill test
also passed. The warning is the pre-existing OpenTelemetry deprecation emitted while importing
FastMCP.

## Phase 3 Verification Checkpoint

Phase 3 adds bounded CISA KEV, NVD CVE 2.0, and security RSS ingestion plus deterministic Security
Stories, actionable ranking, freshness, and an additive report. The closeout run completed with
`247 passed, 1 warning`; compatibility, changed-scope Ruff, compilation, YAML, offline imports, and
failure-isolation checks also passed.

## Phase 4 Verification Checkpoint

Phase 4 centralizes Gemini behind `trendradar.ai`, migrates existing consumers, advances
`intelligence.db` to schema v3, and adds principal-scoped Assistant sessions, bounded local
retrieval, immutable citations, and three static local-read tools. The closeout run completed with
`340 passed, 1 warning`. Changed-scope Ruff, compilation, YAML, offline imports, dependency and
credential scans, rollback checks, and runtime-artifact checks passed. The warning remains the
upstream OpenTelemetry deprecation emitted while importing FastMCP.

## Phase 5 Verification Checkpoint

Phase 5 adds the opt-in official Feishu SDK transport, configurable identities, private/group
mentions, text/image input, durable event deduplication, saved-reply delivery retry, reconnect cooldown, and Shanghai-time daily
Story delivery. Schema v4/v5 adds `feishu_events` and `feishu_deliveries` without changing legacy
schemas. The 2026-09-12 closeout run completed with `397 passed, 1 warning`; scoped Ruff, four
offline entrypoint imports, and the disabled Feishu `--check` passed. Detailed evidence and
crash-window limitations are in [Phase 5 verification](../.planning/phases/05-feishu-assistant/VERIFICATION.md).
At that closeout, real tenant permissions, Gemini responses and production delivery were unverified.
Later selected Windows Lark/Gemini results and remaining live gaps are recorded in
[Phase 5 UAT](../.planning/phases/05-feishu-assistant/05-LIVE-UAT.md); production VPS acceptance
remains open. These historical counts do not validate the current Phase 7 repairs.
