# Phase 1 Context: Unified Intelligence Data Layer

## Boundary

Phase 1 introduces a compatibility-first unified pipeline:

`SourceAdapter -> Normalize -> ContentItem -> Deduplicate -> intelligence.db`

The date-partitioned news/RSS databases and `ai_frontier.db` remain unchanged and continue
to drive reports, notifications, and MCP. Unified persistence is local-only and best effort.

## Locked Decisions

- `ContentItem` timestamps are aware UTC datetimes and IDs are deterministic UUIDv5 values.
- Sources use `newsnow:<platform>`, `rss:<feed>`, and `ai_frontier:<source-key>` namespaces.
- NewsNow is serial; RSS has bounded concurrency 5; AI adapters wrap existing `AISource` classes.
- Empty or partially normalized sources are degraded; terminal fetch failures are unhealthy.
- URL duplicates can cross sources. Exact and fuzzy title duplicates cannot cross logical sources.
- `INTELLIGENCE_ENABLED=false` restores the previous acquisition path completely.
- Unified database failures are logged and never trigger another upstream request.
- Historical data is imported only through the explicit backfill command.

## Out of Scope

Story, clustering, ranking, security sources, vector storage, S3 persistence, and Gemini
restructuring remain outside this phase.
