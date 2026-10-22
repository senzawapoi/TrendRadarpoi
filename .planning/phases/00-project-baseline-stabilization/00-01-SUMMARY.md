---
phase: 00-project-baseline-stabilization
plan: "01"
subsystem: architecture-testing
tags: [pytest, sqlite, characterization-tests, architecture]
requires: []
provides:
  - Current architecture, dependency, coupling, and phased-refactor review
  - Offline characterization tests for three runtime entry points
  - SQLite schema and AI Frontier idempotency compatibility tests
affects: [phase-0-settings, phase-1-content-layer, phase-2-story]
tech-stack:
  added: []
  patterns: [offline-entrypoint-characterization, tmp-path-sqlite-contract-tests]
key-files:
  created:
    - docs/code-review.md
    - docs/baseline.md
    - tests/baseline/test_entrypoints.py
    - tests/baseline/test_storage_compatibility.py
  modified: []
key-decisions:
  - "Treat the main crawler, AI Frontier, and MCP as three compatibility surfaces during migration."
  - "Verify current SQLite schemas with real temporary databases and never touch production output in tests."
patterns-established:
  - "Entrypoint tests import and inspect callables without starting network or long-running transports."
  - "Storage compatibility tests use tmp_path, real schemas, and explicit connection cleanup."
requirements-completed: [BASE-01, BASE-02]
duration: 13min
completed: 2026-08-21
---

# Phase 0 Plan 01: Architecture and Runtime Baseline Summary

**Documented all three runtime surfaces and locked the existing SQLite contracts with five offline characterization tests.**

## Performance

- **Duration:** 13 min
- **Started:** 2026-08-21T19:32:00+08:00
- **Completed:** 2026-08-21T19:45:00+08:00
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Published a Mermaid architecture map, dependency direction, high-coupling inventory, and the exact Phase 0-8 incremental refactor order.
- Added offline import checks for the main crawler, AI Frontier, and FastMCP entry points.
- Added real temporary SQLite checks for news/RSS tables, unique indexes, and AI Frontier idempotent upsert behavior.
- Raised the full test baseline from 91 to 96 passing tests without changing production code or schemas.

## Task Commits

1. **Task 1: Publish architecture review and refactor boundaries** - `3abe465`
2. **Task 2: Establish entrypoint and SQLite characterization tests** - `d4eefdd`

## Files Created/Modified

- `docs/code-review.md` - Current architecture, dependency, coupling, and phased migration review.
- `docs/baseline.md` - Production entry points, offline commands, compatibility contract, and recorded results.
- `tests/baseline/test_entrypoints.py` - Import-only checks for all supported runtime surfaces.
- `tests/baseline/test_storage_compatibility.py` - Core and AI Frontier SQLite contract checks.

## Decisions Made

- Kept production modules and SQLite schemas untouched; this plan is a pure documentation and characterization baseline.
- Used private storage connection helpers only inside characterization tests because the current backend exposes no public schema-inspection API.

## Deviations from Plan

None - plan executed as written. A Ruff `SIM300` finding in a new set containment assertion was corrected before commit.

## Issues Encountered

- Importing FastMCP emits one upstream OpenTelemetry deprecation warning. It does not fail tests or start a transport.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 00-02 can migrate configuration reads against five new compatibility tests and the 96-test full baseline.
- No blockers. Existing unrelated AI Frontier source edits remain untouched.

## Self-Check: PASSED

- All four key files exist.
- `python -m pytest tests -q`: 96 passed, 1 warning.
- `python -m ruff check tests/baseline`: passed.
- Production and schema files were not modified by this plan.

---
*Phase: 00-project-baseline-stabilization*
*Completed: 2026-08-21*
