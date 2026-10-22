# Phase 2 Pattern Map

**Mapped:** 2026-09-04  
**Scope:** Phase 2 Story Intelligence. Assignments below use the locked context,
`02-RESEARCH.md`, roadmap/task documents, and current code.

## Existing Data Flow

The proven path is `adapter.fetch() -> AdapterRunner.run() -> ContentItem ->
persist_adapter_results_best_effort() -> legacy projection`. The new path should consume canonical
items after this write attempt: `ContentItem -> Cluster -> Story -> rank/importance -> additive
Story report`. Do not fetch again and do not make the Story path a prerequisite for legacy output.

**Boundary to copy:** `trendradar/intelligence/pipeline.py:46-64`,
`persist_adapter_results_best_effort(adapter_results, storage) -> DeduplicationResult`. It flattens
normalized items, catches unified-storage failure, logs it, deterministically deduplicates in memory,
and attaches canonical IDs. Story processing must accept the returned canonical items/results or read
the already-fetched batch; it must never call an upstream adapter.

## Models

| Proposed module | Role / data flow | Closest analog and exact callable boundary |
|---|---|---|
| `trendradar/core/models/story.py` (task-doc `core/models/story.py`) | model, transform | `trendradar/core/models/content.py:63-166`; copy `ContentItem.__post_init__`, `create`, `to_dict`, `from_dict`. Boundary: `Story` construction from a deterministic cluster and serialization/deserialization; retain `content_item_ids`/items, tags, importance components, and evidence references. |
| `trendradar/intelligence/clustering.py` (task-doc `pipeline/clustering.py`) | pure transform | `trendradar/intelligence/deduplicate.py:44-83`, `event_time()` at `:13-14`; boundary: `cluster_items(items: list[ContentItem], ...) -> list[Cluster]`. Sort input by `(event_time, id)`, use normalized title/tokens, entity keywords, tags, and bounded time; unmatched items produce one cluster. |
| `trendradar/intelligence/story_generator.py` (task-doc `ai/story_generator.py`) | service, request-response/transform | `trendradar/services/translation_service.py:15-40, 217-265`; boundary: `generate(cluster: Cluster, wording_client=None) -> Story`. Keep Gemini injected/optional; deterministic title, summary, identity, and membership are the fallback. Do not import `mcp_server` from this core path. |

Use `trendradar/core/models/__init__.py:3-33` as the lightweight export pattern; avoid wildcard or
eager external-client imports.

## Storage Migration

Extend `trendradar/intelligence/storage.py`, rather than touching `trendradar/storage/schema.sql`,
`rss_schema.sql`, or `ai_frontier/storage.py`.

**Analog/boundary:** `IntelligenceStorage._initialize_schema()` (`storage.py:149-151`) and
`write_batch()` (`:177-193`). Add a versioned Phase 2 schema/table set for clusters, stories,
story-membership, and persisted importance/reasons. Use stable primary keys and unique membership
constraints so reprocessing is an upsert, not a duplicate. Expose narrow read/write callables such as
`upsert_stories(...)`, `list_stories(...)`, and `list_story_evidence(...)` on
`IntelligenceStorage`; planner should keep SQL and row conversion inside this class.

**Transaction rule:** copy `transaction()` (`:166-175`) and keep one complete story batch (cluster
identity, membership changes, story fields, ranking/importance) inside one `BEGIN IMMEDIATE` /
`COMMIT`; any exception rolls back all derived rows. Do not commit per member or per story. Keep
canonical `content_items` and `content_observations` untouched. Bump only the unified DB version via
a forward migration; opening an old DB must preserve Phase 1 tables and data.

## Clustering And Story Service

`clustering.py` is deterministic and side-effect free, analogous to `Deduplicator.process()`
(`deduplicate.py:44-83`): deterministic ordering is required because later sources must not change
an existing identity merely by arriving in a different order. Reuse `normalize_identity_title()` and
`event_time()`; do not use fuzzy cross-entity merging. Preserve every canonical item and resolve
evidence through `IntelligenceStorage.list_observations(content_item_id)` (`storage.py:339-347`).

`story_generator.py` should follow the service's explicit optional-client/error pattern, but its
failure behavior must be stricter than wording: catch/log wording failure, then return the same
deterministic Story fallback. The exact service boundary is one cluster in, one Story out; batch
orchestration belongs to a separate caller and must not hide persistence errors.

There is no direct current Cluster/Story analog. Mark this as **no exact analog; role-match** and use
`ContentItem` plus `DeduplicationResult` as the identity/evidence contract.

## Ranking

| Proposed module | Closest analog / boundary |
|---|---|
| `trendradar/intelligence/ranking.py` | `trendradar/core/analyzer.py:14-55`, `calculate_news_weight(title_data, rank_threshold, weight_config) -> float`; expose pure `score_story(story, config) -> Importance` and `rank_stories(stories, config) -> list[Story]`. |

Persist component scores and readable reasons, not only a final float. Compute source diversity,
configured source reliability, activity/growth, recency, and user-interest matches with fixed tie
breakers `(importance descending, event time descending, story id ascending)`. Do not reuse legacy
rank weights as a hidden mutation of `NewsItem`; this is a new canonical derived layer.

## Report

| Proposed module | Closest analog and exact callable boundary |
|---|---|
| `trendradar/report/story.py` | `trendradar/report/generator.py:12-132` (`prepare_report_data`) plus `:135-223` (`generate_html_report`); use `prepare_story_report(stories, ...) -> dict` then `render_story_report(report_data, ...) -> str`/`generate_story_report(...) -> str`. |

Use `trendradar/report/html.py:12-24` (`render_html_content`) and `report/helpers.py:28-53`
(`html_escape`) for presentation/escaping. Report only Story data, evidence links, importance
reasons, and source labels. It is additive/local: do not replace the existing report payload,
filename, notification dispatcher input, or legacy HTML/index writes.

## Runtime Integration

Modify the composition boundaries, not collectors:

- `trendradar/intelligence/integration.py:66-104` `fetch_newsnow_with_adapters(...)` and
  `:131-156` `fetch_rss_with_adapters(...)`: retain adapter execution, call
  `persist_adapter_results_best_effort()` once, then pass its canonical result to the Story service.
- `trendradar/ai_frontier/fetcher.py:97-119` `fetch_and_process(...)`: retain the adapter/legacy
  switch and call the same best-effort canonical persistence boundary exactly once.
- `trendradar/__main__.py:175-220,299-322` and `trendradar/ai_frontier/__main__.py:159-182` are
  composition roots. Story failures are logged and skipped after acquisition; already-fetched items
  still proceed through legacy storage/report/notification.
- Read settings through `RuntimeSettings.intelligence_enabled` and
  `intelligence_database_path` (`trendradar/core/settings.py:195-207`). `false` must bypass Story
  processing with the complete legacy path intact.

## Backfill Integration

Extend `trendradar/intelligence/backfill.py`, whose exact public boundary is
`run_backfill(start, end, include, dry_run, settings) -> BackfillSummary` (`:203-230`). Copy
`_persist_batch()` (`:79-95`): convert legacy records, run `Deduplicator(storage).process()`, and
write through the unified store. After each chronological canonical batch, derive/upsert Stories in
the same deterministic order; never refetch legacy sources.

Preserve inclusive dates, source filters, corrupt/missing DB skipping, and dry-run `:memory:`
behavior. Re-running the identical range must produce zero new canonical rows, observations,
memberships, and duplicate Stories. Story migration must be idempotent by stable Story identity and
unique `(story_id, content_item_id)` membership.

## Tests

| Proposed test module | Closest current analog / boundary |
|---|---|
| `tests/intelligence/test_clustering.py` | `test_deduplicate.py:29-74`; call `cluster_items()` with fixed UTC timestamps and assert same-event grouping, entity separation, tag/title signals, and singleton fallback. |
| `tests/intelligence/test_story.py` | `test_models.py:20-94`; assert validation, deterministic identity, serialization, and all evidence/member retention. |
| `tests/intelligence/test_ranking.py` | `test_deduplicate.py:95-102` plus `core/analyzer.py:14-55`; assert component scores, reasons, tie-breakers, and offline determinism. |
| `tests/intelligence/test_storage.py` (extend) | `test_storage.py:28-107`; use `tmp_path`, real SQLite, schema version assertions, one-transaction rollback, and repeated upsert counts. |
| `tests/intelligence/test_story_report.py` | AI Frontier renderer pattern documented in `tests/ai_frontier/test_renderer.py`; assert escaped evidence URLs, Story ordering, fallback text, and additive output. |
| `tests/intelligence/test_integration.py` / `test_backfill.py` (extend) | existing tests at `test_integration.py:125-145` and `test_backfill.py:98-148`; monkeypatch fetch/persist to prove one fetch, best-effort failure, rollback mode, and idempotent repeated backfill. |
| `tests/baseline/test_storage_compatibility.py` (extend) | `:44-78`; assert all three legacy schemas and AI Frontier upsert behavior are unchanged. |

## Compatibility Hazards

- `persist_adapter_results_best_effort()` is the failure boundary. A Story/storage exception must not
  cause a second adapter call, refetch, or loss of legacy projection.
- Do not alter `content_items`, `content_observations` identity rules, `NewsItem`/`RSSItem`/`AIItem`,
  or the three legacy schemas. Story tables belong only in `intelligence.db`.
- Do not let Gemini determine Story identity, membership, fallback title/summary, or rank; optional
  wording failure must leave a deterministic offline result.
- Preserve source observations as evidence even when canonical items are deduplicated; Story
  membership is derived from canonical IDs, while report evidence reads observations.
- SQLite writes need short, explicit transactions and the existing WAL/busy-timeout settings;
  never hold a transaction across network/Gemini work.
- `INTELLIGENCE_ENABLED=false` remains a complete rollback switch. Existing reports, MCP readers,
  notifications, and AI Frontier storage remain unchanged and continue to be authoritative for their
  current consumers.
