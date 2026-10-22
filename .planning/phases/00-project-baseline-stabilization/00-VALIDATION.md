---
phase: 0
slug: project-baseline-stabilization
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-08-21
---

# Phase 0 - Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | none; pytest default discovery |
| **Quick run command** | `python -m pytest tests/baseline tests/test_settings.py -q` |
| **Full suite command** | `python -m pytest tests -q` |
| **Estimated runtime** | under 10 seconds without network |

## Sampling Rate

- **After every task commit:** Run the task's focused pytest or source assertion.
- **After every plan wave:** Run `python -m pytest tests -q`.
- **Before phase verification:** Full suite and changed-scope Ruff must be green.
- **Max feedback latency:** 15 seconds.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Test Type | Automated Command | Status |
|---------|------|------|-------------|------------|-----------|-------------------|--------|
| 00-01-01 | 01 | 1 | BASE-01 | N/A | source | `rg -n "Architecture|Dependencies|High Coupling|Refactoring" docs/code-review.md` | passed |
| 00-01-02 | 01 | 1 | BASE-02 | T-00-01 | integration | `python -m pytest tests/baseline -q` | passed |
| 00-02-01 | 02 | 2 | CONF-01, CONF-03 | T-00-02 | unit | `python -m pytest tests/test_settings.py -q` | passed |
| 00-02-02 | 02 | 2 | CONF-01 | T-00-03 | regression | `python -m pytest tests/baseline -q` | passed |
| 00-02-03 | 02 | 2 | CONF-02 | T-00-02 | source | `git check-ignore .env.example` must return non-zero | passed |

## Wave 0 Requirements

Existing pytest infrastructure is sufficient. Plan 00-01 creates the missing baseline test files before
the settings migration in Plan 00-02.

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Architecture review is useful and accurate | BASE-01 | Documentation quality is not fully machine-verifiable | Compare module paths and arrows with current codebase maps |

## Validation Sign-Off

- [x] Every implementation task has an automated verify command.
- [x] No three consecutive tasks lack automated feedback.
- [x] Wave 0 dependencies are explicit.
- [x] No watch-mode flags are used.
- [x] Expected feedback latency is under 15 seconds.
- [x] `nyquist_compliant: true` is set.

**Approval:** approved 2026-08-21
