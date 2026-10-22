---
phase: 04-gemini-intelligence-layer
plan: "04-03"
subsystem: local-intelligence-assistant
tags: [assistant, sqlite, sessions, retrieval, citations, fallback]
requires: [04-01, 04-02]
provides:
  - Principal-scoped bounded Assistant sessions and complete-turn persistence
  - UTC half-open Story and ContentItem retrieval with immutable evidence snapshots
  - Grounded replies with deterministic no-Gemini degradation
affects: [04-04, Phase 5 Feishu Assistant]
tech-stack: [Python, SQLite, pytest]
key-files:
  created:
    - trendradar/ai/models.py
    - trendradar/ai/session.py
    - trendradar/ai/retrieval.py
    - trendradar/ai/assistant.py
    - tests/ai/test_session.py
    - tests/ai/test_retrieval.py
    - tests/ai/test_assistant.py
  modified:
    - trendradar/intelligence/storage.py
    - tests/intelligence/test_storage.py
requirements-completed: [ASST-01, ASST-02, ASST-03]
completed: 2026-09-04
---

# Phase 4 Plan 03 Summary

Advanced `intelligence.db` to schema v3 with forward-only `assistant_sessions` and
`assistant_messages` tables. `IntelligenceStorage.from_connection()` supports borrowed connection
ownership, while `SessionStore` enforces principal ownership, aware UTC timestamps, sliding expiry,
bounded complete-turn history, character limits, transactional pruning, and request idempotency.

Local retrieval uses explicit UTC `[start, end)` windows, parameterized escaped searches,
deterministic ranking, and limits at Story, member, observation, item, and citation layers. Citation
refs and bounded evidence snapshots are built from persisted records; model-supplied references not
present in the current evidence set are discarded.

`AssistantService` composes bounded history and local evidence through the provider-neutral client.
Missing or failed Gemini produces a useful deterministic reply from the same evidence, reports
degradation/truncation, and atomically persists one coherent user/assistant turn. Duplicate request
IDs return the stored reply without another provider call.

## Verification

- Session, retrieval, Assistant, and v1/v2/v3 storage suite: `40 passed`.
- Full repository suite after Phase 4 implementation: `340 passed, 1 warning`.
- Concurrency, rollback, interval edges, ownership, forged citations, and no-provider paths passed.
- No commit or runtime SQLite artifact was created.

