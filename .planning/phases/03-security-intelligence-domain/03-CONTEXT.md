# Phase 3 Context: Security Intelligence Domain

## Boundary

Phase 3 adds a dedicated security domain beside the existing collectors:

`CISA KEV / NVD / security RSS -> SourceAdapter -> ContentItem(security) ->
Deduplicate -> Cluster -> Story -> Security Importance -> additive security report`

The implementation lives under `trendradar/domains/security/`, while transport adapters remain
under `trendradar/sources/`. It extends `intelligence.db` through existing content, observation,
source-run, cluster, and Story contracts; it does not introduce a separate security database.

## Locked Decisions

- D-01: Provide separate collector, analyzer, and report modules under
  `trendradar/domains/security/` as required by the v5 execution documents.
- D-02: CISA KEV, NVD CVE API 2.0, and configurable RSS/Atom feeds are the Phase 3 sources.
- D-03: Every security record becomes a UTC-aware `ContentItem` with `domain="security"`; CVE,
  CVSS, severity, KEV, due-date, action, vendor/product, reference, and raw-source evidence stays
  in tags/metadata and observations.
- D-04: Exact CVE identifiers are strong, cross-source Story anchors. They may associate official
  and news evidence across ordinary headline/time similarity limits, while unrelated CVEs remain
  separate.
- D-05: Security Importance is deterministic and prioritizes severity, known exploitation, and
  required action. Gemini analysis remains Phase 4 work.
- D-06: The security HTML report is additive under `output/security/`, includes all evidence and
  per-source freshness, and does not replace `output/index.html`, Story output, MCP, or existing
  notifications.
- D-07: Security collection runs only when both unified intelligence and security are enabled.
  `INTELLIGENCE_ENABLED=false` keeps the complete old path; a security source/report failure does
  not interrupt NewsNow, RSS, AI Frontier, legacy SQLite, reports, or notifications.
- D-08: NVD credentials are optional and environment-only (`NVD_API_KEY`). Network concurrency,
  pages, item counts, lookback windows, timeouts, and report size are bounded for the target VPS.

## Out of Scope

Shared Gemini restructuring, conversational analysis, Feishu delivery, Agent-Reach, a new
database, S3 synchronization of `intelligence.db`, replacement of legacy reports/notifications,
and importing another cybersecurity project wholesale remain outside Phase 3.

