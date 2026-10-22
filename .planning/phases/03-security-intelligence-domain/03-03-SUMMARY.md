---
phase: 03-security-intelligence-domain
plan: "03-03"
subsystem: security-integration-reporting
tags: [security, report, settings, rollback, compatibility]
requires: [03-01, 03-02]
provides:
  - Additive escaped Security Story HTML report with all source evidence
  - One-pass best-effort main-entry integration with stage isolation
  - Bounded runtime settings and environment-only NVD credentials
affects: [Phase 4 Gemini service, Phase 5 Feishu delivery]
tech-stack: [SQLite, HTML, Python standard library, pytest]
key-files:
  created:
    - trendradar/domains/security/report.py
    - tests/intelligence/test_security_integration.py
    - tests/intelligence/test_security_report.py
  modified:
    - trendradar/domains/security/collector.py
    - trendradar/core/settings.py
    - trendradar/core/loader.py
    - trendradar/__main__.py
    - config/config.yaml
    - .env.example
    - docs/intelligence.md
    - tests/test_settings.py
requirements-completed: [SECU-01, SECU-02, SECU-03, SECU-04, SECU-05, SECU-06]
completed: 2026-09-04
---

# Phase 3 Plan 03 Summary

Integrated security collection, persistence, Story derivation, analysis, freshness, and report
generation as isolated stages after existing acquisition. The report is written only to
`output/security/YYYY-MM-DD.html`; candidate Stories are bounded before scoring and truncated only
after deterministic security ranking. Disabled or failed security processing cannot interrupt or
refetch NewsNow, RSS, AI Frontier, legacy SQLite, reports, MCP, or notifications.

Runtime settings expose source limits, concurrency, freshness, ranking, and report bounds.
`NVD_API_KEY` is read only from the environment, while `INTELLIGENCE_SECURITY_ENABLED=false`
disables the security domain and `INTELLIGENCE_ENABLED=false` restores the complete legacy path.

## Verification

- Full suite: `247 passed, 1 warning` (upstream OpenTelemetry deprecation warning).
- Compatibility subset: `35 passed` for rollback, integration, settings, and legacy schemas.
- Changed-scope Ruff, `compileall`, YAML loading, and main/AI/MCP offline imports passed.
- No unified database or Security report was generated in the repository.
