---
phase: 00-project-baseline-stabilization
plan: "02"
subsystem: configuration
tags: [yaml, environment, settings, secrets, compatibility]
requires:
  - phase: 00-01
    provides: Runtime and SQLite characterization baseline
provides:
  - Unified RuntimeSettings boundary for the crawler, AI Frontier, and MCP
  - Environment-only Gemini and Feishu secrets with redacted representation
  - Backward-compatible configuration loading and database path overrides
affects: [phase-1-content-layer, phase-4-gemini, phase-5-feishu, deployment]
tech-stack:
  added: []
  patterns: [environment-over-yaml-settings, immutable-runtime-config, compatibility-facade]
key-files:
  created:
    - trendradar/core/settings.py
    - config/settings.py
    - .env.example
    - tests/test_settings.py
  modified:
    - trendradar/core/loader.py
    - trendradar/__main__.py
    - trendradar/ai_frontier/__main__.py
    - mcp_server/services/parser_service.py
    - mcp_server/tools/storage_sync.py
    - mcp_server/tools/system.py
    - mcp_server/utils/validators.py
key-decisions:
  - "Keep the packaged implementation in trendradar.core.settings and expose config.settings as a facade."
  - "Resolve config paths as explicit argument, CONFIG_PATH, then config/config.yaml."
  - "Resolve values as non-empty environment, YAML, then default; secrets remain environment-only."
patterns-established:
  - "All runtime YAML parsing flows through trendradar.core.settings."
  - "Legacy load_config consumers keep their uppercase dictionary contract."
requirements-completed: [CONF-01, CONF-02, CONF-03]
duration: not-recorded
completed: 2026-08-21
---

# Phase 0 Plan 02: Unified Runtime Settings Summary

**One immutable settings boundary now serves the crawler, AI Frontier, and MCP while preserving legacy configuration and SQLite behavior.**

## Performance

- **Duration:** Not recorded; implementation was resumed at closeout
- **Completed:** 2026-08-21
- **Tasks:** 3
- **Files modified:** 12

## Accomplishments

- Added typed YAML, environment, and default-value resolution with deterministic precedence.
- Kept Gemini and Feishu credentials environment-only and redacted from settings representations.
- Migrated all three runtime surfaces away from direct YAML parsing while preserving their existing error and fallback contracts.
- Added compatibility tests for legacy dictionaries, AI Frontier paths, MCP parsing, and storage sync behavior.

## Task Commits

1. **Task 1: Implement RuntimeSettings and the safe environment example** - `a692032`
2. **Task 2: Route the main and AI Frontier pipelines through settings** - `cecedff`
3. **Task 3: Unify MCP configuration loading** - `e558796`

## Files Created/Modified

- `trendradar/core/settings.py` - Canonical immutable settings implementation and YAML loader.
- `config/settings.py` - Stable repository-level re-export facade.
- `.env.example` - Empty-value variable contract for local, CI, and VPS use.
- `tests/test_settings.py` - Precedence, secret, compatibility, and MCP regression coverage.
- Runtime entrypoints and MCP readers - Shared settings integration without schema changes.

## Decisions Made

- Core owns configuration behavior; interface layers may import core, but core never imports MCP.
- Invalid or missing configuration retains each runtime's previous fail-fast or fallback behavior.
- Default data locations remain unchanged and can be overridden through the same environment names everywhere.

## Deviations from Plan

### Auto-fixed Issues

**1. Changed-scope Ruff cleanup in MCP modules**
- **Found during:** Task 3
- **Issue:** Touched MCP modules contained lint findings that blocked the required changed-scope gate.
- **Fix:** Cleaned those findings without changing their exception or fallback behavior.
- **Verification:** Changed-scope Ruff and the full pytest suite pass.
- **Committed in:** `e558796`

**Total deviations:** 1 auto-fixed quality issue. No feature scope was added.

## Issues Encountered

- FastMCP import emits an upstream OpenTelemetry deprecation warning; it does not fail tests or start a transport.

## User Setup Required

None. Runtime credentials remain externally injected and `.env.example` contains no values.

## Next Phase Readiness

- Phase 1 can introduce `ContentItem`, adapters, normalization, and deduplication on a shared configuration boundary.
- The full closeout suite passes with `111 passed, 1 warning`; no SQLite schema or default path changed.

## Self-Check: PASSED

- All plan artifacts and public exports exist.
- `python -m pytest tests -q`: 111 passed, 1 warning.
- Changed-scope Ruff, entrypoint imports, ignore rules, and source assertions passed.

---
*Phase: 00-project-baseline-stabilization*
*Completed: 2026-08-21*
