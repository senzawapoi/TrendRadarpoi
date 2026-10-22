---
phase: 04-gemini-intelligence-layer
plan: "04-02"
subsystem: shared-gemini-consumers
tags: [gemini, translation, story, digest, security, compatibility]
requires: [04-01]
provides:
  - Core-owned translation with the established anonymous-provider fallback
  - Shared Gemini Story wording, daily digest, and security narrative adapters
  - Best-effort consumer injection at the main and AI Frontier entry points
affects: [04-03, 04-04, Phase 5 Feishu Assistant]
tech-stack: [Python, requests, pytest]
key-files:
  created:
    - trendradar/ai/translator.py
    - trendradar/ai/analyzer.py
    - tests/ai/test_translation.py
    - tests/ai/test_analyzers.py
  modified:
    - trendradar/services/translation_service.py
    - trendradar/ai_frontier/translator.py
    - mcp_server/tools/translation.py
    - trendradar/intelligence/gemini_wording.py
    - trendradar/intelligence/pipeline.py
    - trendradar/intelligence/story_report.py
    - trendradar/domains/security/analyzer.py
    - trendradar/domains/security/report.py
    - trendradar/__main__.py
    - trendradar/ai_frontier/__main__.py
requirements-completed: [GEMI-03, GEMI-04]
completed: 2026-09-04
---

# Phase 4 Plan 02 Summary

Moved translation orchestration into `trendradar.ai` while retaining the public
`TranslationService`, AI Frontier mutation/count behavior, MCP result dictionaries, and fixed
anonymous-provider order. The MCP facade now defaults its Gemini key to `None`; AI Frontier no
longer inspects callable signatures or attempts to recover an embedded/default credential.

Story wording now delegates to an injected shared `GeminiClient`. Bounded daily digest and security
narrative adapters receive only ranked projections and may add escaped text, but cannot change
canonical identity, Story membership, Importance, CVE facts, freshness, or deterministic reasons.
Both runtime entry points reuse a configured client and contain all optional construction and call
failures without refetching or interrupting legacy output.

## Verification

- Plan-focused translation, analyzer, Story, Security, and integration suite: `60 passed`.
- Full repository suite after Phase 4 implementation: `340 passed, 1 warning`.
- Core AI/services/intelligence/domain modules contain no `mcp_server` dependency.
- No commit, provider request, database, or report artifact was created.

