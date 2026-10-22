# Phase 7 Verification

## Current checkpoint (2026-10-22)

07-05 follows the dated Codex handoff. ENV-03 is fixed; H1-A..D passed 22 Linux
tests. Windows tzdata is declared/pinned; new controller records use same-boot
CLOCK_BOOTTIME to avoid false rejection after wall-clock steps, with the original
15-second limit and identity fences. Lease/rollback/complete real-systemd focus
passed 118. Temporary diagnostic telemetry caused a v3 service-UID write failure;
it was removed and both UID-upgrade/original-timer nodes pass.

Frozen v6 has 301 unchanged source/resource hashes and dirty HEAD. Windows full:
683 passed/342 skipped/2 upstream warnings; Linux full: 1019 passed/6 skipped/
2 warnings. Separate real dirty installation: 1 passed. All exit 0. Archive
members match all 301 inputs; final 28-case mapping is 27 PASS/1 BLOCKED (RG-04
clean candidate). Linux full includes 11 real systemd quiesce and 2 backup-unit
passes. No test session is active. See the
[report](../../../docs/phase7-actual-gap-evidence/verification-20261022.md) and
[handoff](../../../docs/phase7-actual-gap-evidence/HANDOFF.md). Historical failures
and their original scopes remain in the evidence index. G1 PASS; G2 blocked by
clean candidate. Real GitHub and G3/V-01..06 remain unverified.

## Historical offline verification (2026-10-13)

```text
python -B -m pytest tests -q -p no:cacheprovider
531 passed, 1 warning

python -m ruff check trendradar/ai_frontier trendradar/core/locking.py trendradar/core/heartbeat.py trendradar/ops trendradar/integrations/feishu/__main__.py trendradar/__main__.py scripts/deploy tests/deployment tests/integrations/feishu
passed

git diff --check
passed (Git reported only existing line-ending warnings for unrelated files)
```

The focused Phase 7 suite covers role checks, Bot/Worker/Scheduler isolation,
durable polling, OS lock contention, read-only health, missing database,
heartbeat, `FULL` SQLite policy, strict AI Frontier opening, complete
multi-database backup/restore activation, artifact boundaries, and the
persistent restore guard. A Windows source artifact audit found no `output/`,
`test/runtime/`, database, or `.env` files.

## Gate status

| Gate | Status | Boundary |
|---|---|---|
| 07-01 implementation | Offline passed | Frozen full regression and isolated systemd pass; VPS lifecycle open |
| 07-02 implementation | Offline passed | Resource/hardening values need VPS measurement |
| 07-03 implementation | Offline passed | Current dirty Linux installation passed; clean candidate, GitHub execution and remote restic open |
| 07-04 implementation | Offline ready | Disposable-target restore and runbook execution not run |
| 07-05 actual-gap remediation | Authorized local work complete | 27 PASS/1 BLOCKED; G1 PASS; G2 clean candidate and G3 target open |
| DEPL-01 | Pending target evidence | No VPS supplied |
| DEPL-02 | Pending target evidence | No VPS/provider run |
| DEPL-03 | Local checks pass; external gate open | Clean artifact, real CI/release and remote backup evidence missing |
| DEPL-04 | Runbook updated, drill pending | No operator drill |
| DEPL-05 | Pending target evidence | No 1-core VPS load sample |

The earlier 07-01..04 counts remain historical. Current local verification is
in final-run-v6-20261022.json, case-results-20261022.json and the skip audit.
Phase 7 target acceptance remains unfinished.

## Follow-up remediation

The 2026-10-13 follow-up added release-local package installation, a persistent
installer state machine, schema-aware pre-resume rollback, fixed-revision
workflow packaging, bounded and redacted restic receipts, explicit readiness
health, and multi-database restore journals. The focused follow-up suite passed
23 tests; the active deployment marker now tracks each transaction stage before
the archival record. Bash syntax, scoped Ruff, compileall and source artifact
construction also passed on Windows.

Frozen Linux full now closes the isolated UID/guard/crash/role/timer scope and
27 of 28 reviewed scenarios. GitHub execution, remote backup/recovery, VPS
resource measurement, Lark provider acceptance and continuous operation remain
pending. The dirty local worktree artifact was used only for offline inspection
and is not deployable without an explicit clean committed revision.

