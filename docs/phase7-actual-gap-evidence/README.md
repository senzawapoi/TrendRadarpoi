# Phase 7 Actual-gap Evidence

Execution started 2026-10-14 (Asia/Shanghai). Source is an uncommitted main
worktree, ahead of origin/main by 42 commits; HEAD alone does not identify it.

## Pre-fix Reproduction

Windows Python 3.10.11 / SQLite 3.40.1:

`python -B -m pytest tests/deployment/test_actual_gap_health.py tests/deployment/test_runtime_guards.py -q -p no:cacheprovider`

Result: 21 failed, 4 passed. Failures isolate F-02 (five Bot non-connected
states), F-03 (required but empty sources), and F-05 (11 deployment states
without explicit guard plus four incomplete/malformed restore journals).
The connected state and existing stopped/disabled/disconnected checks pass.

[Archived Linux evidence](pre-fix-linux.json) now records F-01/F-04 reproduction
from the retained immutable audit archive. Two assertions passed because the
archived entry failed configured readiness and root restore broke service-UID
access. Its limits are recorded explicitly; repaired-source tests are separate.
Ubuntu WSL runs systemd with root access and an isolated Python 3.10.22 toolchain.
No real business-provider calls were made.

## Current Checkpoint (2026-10-22)

[Final report](verification-20261022.md), [handoff](HANDOFF.md) and
[v6 run record](final-run-v6-20261022.json) close the authorized local work.
Windows: 683 passed/342 skipped/2 warnings, exit0. Linux:
1019 passed/6 skipped/2 warnings, exit0. Separate dirty empty-venv installation:
1 passed, exit0. Linux full includes 11 real systemd quiesce and 2 backup-unit
passes. [Every skip](skip-audit-v6-20261022.json) is explained.

The [v6 manifest](final-inputs-v6-20261022.json) freezes 301 source/resource
files, all unchanged after execution and matching actual archive members.
Twelve constraint files are recorded separately; final narrative updates are
audited after testing. [Artifact identity](artifact-install-evidence-v6-20261022.json)
remains dirty; [source delta](source-delta-20261022.json) separates changes and
expanded inventory.

[28-case results](case-results-20261022.json): 27 PASS, RG-04 clean candidate
BLOCKED. [Matrix](case-matrix.md): G1 PASS, G2 BLOCKED, G3/V-01..06 open.
Real GitHub, clean revision, target operations and Phase5 C3/C4 remain open.

H1-A..D passed 22 focused tests and now have final execution mappings.
Windows tzdata and clock-step-sensitive controller lease repairs retain
[reproduction](tzdata-reproduction-20261022.json) and
[investigation](guard-clear-investigation-20261022.json).
Current positive lease fixtures pass [91 focused tests](positive-lease-fixture-20261022.json).
All v1..v5 manifests, failed logs, telemetry diagnostics and original fault
directories remain historical. No test session is active.

## Historical Evidence

[ENV-03 repair](env03-readability-fix-20261014.json) passed 48 focused tests;
the subsequent deployment-only regression passed 466 with six skips. ENV-03
is fixed, and its earlier 26-pass/1-failure result is historical.
[Rollback repair](rg03-rollback-fix-20261014.json) records the root-owned guard
failure and successful service-identity/expired-lease follow-up.
[Restore follow-up](restore-durability-20261014.json),
[remaining assertions](remaining-assertions-20261014.json),
[verification checkpoint](verification-checkpoint-20261014-0804.json) and
[cleanup](workspace-cleanup-20261014-post-rollback.md) retain their original
scope and failures. Their counts overlap and must not be added.

Older `checkpoint-source-*`, `cleanup-source-*` and `resume-inputs-*` inventories
identify historical worktrees, not the current frozen candidate. Preserve audit
archives, failed fixture directories, toolchains and original logs.
