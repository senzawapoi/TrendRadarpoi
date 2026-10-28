# Controlled Deployment Recovery Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Resume the exact installed `p7-20261027-a20f2d8` candidate without deleting a failed deployment fence, restoring a database, changing resource limits, or claiming readiness prematurely.

**Architecture:** Add a root-owned, explicit forward-recovery controller. It validates the failed transaction, immutable archive, installed code, current symlink and release identity under the existing deployment lock. It retains the old record, creates a separately identified recovery transaction with a live lease, snapshots current databases, starts roles serially, and uses the existing maintenance/finalize APIs. Failure stops managed units and retains maintenance protection.

**Tech Stack:** Python standard library, systemd, existing trusted EnvironmentFile loader and candidate Python 3.12 operations CLI.

---

This is a repair of the interrupted 07-06 deployment, not Phase 7 closeout. Owner authorization for commit/deployment and subsequent continuation remains applicable. Original failure: run 40493521142, transaction `p7-20261027-a20f2d8-20261027T111026Z-16094`, state `failed:readiness`, business boundary crossed. The source candidate remains a20f2d8191c66fce858049dd1462406a9f7797fc. No automatic database rollback is permitted.

## Task 1: Preserve the failed scene and reproduce startup boundaries

Files: existing `output/pr8-repair-20261024/` evidence and `docs/handoff/` deployment checkpoint.

1. Read active transaction, systemd states and baseline fingerprints; save terminal output before changing current-state documentation.
2. Confirm the 428 completed batches, 6698 registrations and 8 completed events match their pre-deployment fingerprints.
3. Stop maintenance restart loops; leave guards and transaction records intact.
4. Retain offline import and bounded concurrent SDK probe results. Distinguish observed resource pressure from an established root cause.

## Task 2: Add a fail-closed recovery controller

Files: create `scripts/deploy/recover_release.py`; create `tests/deployment/test_release_recovery.py`.

1. Write failing tests for wrong release/transaction/commit/archive, a live prior controller, unsafe paths, mismatched current link, a missing guard, and rollback/cutover records. Assert no fence or runtime mutation on rejection.
2. Run `python -m pytest tests/deployment/test_release_recovery.py -q`; verify the initial missing implementation failure.
3. Implement explicit arguments for expected release, failed transaction, commit and archive SHA. Archive contents must match both release files and installed Python package files.
4. Implement atomic, fsynced journal writes and a distinct recovery transaction referencing the original failure hash. Renew the actual controller identity/lease independently of slow subprocesses. Never pretend the previous controller remains alive.
5. Use existing candidate CLI for a consistent new backup, guarded release authorization, and finalization. Start Bot and Worker one at a time, checking matching release/PID/heartbeat before proceeding. Refresh collectors serially if required; preserve timer cadence and resource limits.
6. On any failure, record the failing stage, restore maintenance protection and stop units. Do not unlink failed records or perform automatic database rollback.
7. Cover success/failure ordering, lease loss, interruption, identity checks and journal retention with meaningful tests. Run scoped Ruff and existing deployment/maintenance regressions on native WSL Linux.

## Task 3: Publish, bootstrap and execute exact recovery tooling

1. Commit the reviewed recovery tool and evidence contract in the isolated worktree; push for CI and bind its SHA.
2. Install the tested script through a root-owned fixed entry using the existing trusted environment loader. Keep the failed application candidate and its archive unchanged.
3. Run recovery under systemd with a bounded lifetime so chat disconnection cannot strand an unmanaged process. Record unit name, transaction ID and evidence paths.
4. Require strict readiness and the existing finalization API before declaring recovery successful; read back live heartbeats, service state, backup and immutable-message fingerprints.

## Task 4: Reconcile active project views

Files: `.planning/STATE.md`, `.planning/phases/07-deployment/07-06-PLAN.md`, `docs/phase7-release-20261023/HANDOFF.md`, `docs/repository-handoff-20261023.md` and the existing repair record.

Record merged, packaged, installed, recovered and accepted states separately. Preserve historical pass/fail results. Keep long-running collection starvation, true tenant quote/tool UAT, 48-hour healthy observation and offsite recovery open. Only documentation checks are needed after prose-only synchronization; never sum overlapping test scopes.
