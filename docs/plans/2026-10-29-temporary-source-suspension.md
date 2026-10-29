# Temporary Reddit And X Source Suspension Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Apply the owner's 2026-10-29 decision to suspend Reddit and X/Nitter, then resume the installed application through the validated recovery controller.

**Architecture:** Change only the two source enabled flags in the tracked YAML and the external production YAML. Remove exactly their two entries from the explicit production required-source list, retaining the other requirements and all source history. Keep application release bytes unchanged; the existing controlled recovery tool snapshots, refreshes enabled pipelines, verifies sources, drains durable delivery, restores timers, and finalizes.

**Tech Stack:** YAML, Python 3.12, existing settings/health CLI, systemd, trusted EnvironmentFile loader.

---

Owner has authorized implementation, commit/push and deployment. PR 10 is merged as 31ce870; PR 7 remains open. Execute in the current isolated deployment worktree on a new branch from 31ce870. Do not auto-merge. Detailed operational evidence remains in ignored local output and on VPS.

## Task 1: Record the scope and reconcile inputs

Files: this plan; existing output/DEPLOY-CONTINUATION-20261028.md.

1. Confirm clean Git state, merged base, current application identity, failed recovery record, maintenance guard and stopped units.
2. Record owner amendment: Reddit and X/Nitter temporarily disabled; restoring access is deferred, not declared fixed.
3. Retain production configuration backups and exact hashes without publishing credentials.
4. Keep original common.env backup immutable. Derive a separate post-recovery configuration that restores only the temporary restart intent while retaining the newly authorized source scope.

## Task 2: Change tracked source defaults

File: config/config.yaml.

Change only these values, preserving all account/subreddit definitions:
```yaml
ai_frontier:
  sources:
    reddit:
      enabled: false
    x_nitter:
      enabled: false
```

Add short comments identifying temporary suspension and the need to restore production required-source entries together with a validated feed.

Validation: parse before/after YAML and assert the only semantic differences are those two booleans. Run existing AI source, settings and health checks on native Linux; follow repository full-test requirements. No implementation-mirroring test is needed for this reversible configuration edit.

## Task 3: Apply production source scope under maintenance

Files: external CONFIG_PATH and trusted common.env; local ignored output receipts.

1. Hold the existing deployment lock; assert the inspected failed transaction/guard and stopped roles.
2. Preserve root-owned backups. Atomically change the same two YAML booleans while retaining owner/group/mode and all unrelated values.
3. Remove exactly ai_frontier:reddit and ai_frontier:x_nitter from TRENDRADAR_HEALTH_EXPECTED_SOURCES if it is the active override, otherwise from the explicit YAML expectation list. Require the other 31 entries to be unchanged.
4. Require source runs and backup checks to remain true; preserve all freshness thresholds, roles, resources, delivery configuration, data and immutable release files.
5. Reload settings and local health as the service UID. Validate effective flags, the exact expectation set and unchanged guard/active record.
6. Run the installed fixed recovery entry with --check-only. A passing preflight does not establish production readiness.

## Task 4: Publish and resume controlled recovery

1. Commit only reviewed YAML, plan and active handoff changes; push a new branch/PR against Phase 7. Do not publish detailed runtime receipts.
2. Reuse the already validated controller 5a46399 and the same installed application artifact.
3. Launch a new uniquely named systemd recovery unit with bounded role/readiness/collector budgets. Never reuse previous unit/PID/lease or bypass the fence.
4. Monitor actual journal, unit, fresh source and role evidence through completion. Failed recovery must remain fenced, with its evidence retained.
5. On success, restore the prepared post-recovery common.env bytes after checking exact hashes; retain the new source scope and original backup.

## Task 5: Verify and checkpoint

Files: existing local operational continuation and affected tracked handoff entries.

1. Require healthy strict readiness, matching fresh Bot/Worker identity, active intended timers, backlog zero and no failed/expired delivery batches.
2. Compare original completed-message, delivery-registration and event fingerprints; permit legitimate new deliveries, require zero historical changes and zero duplicate registration groups.
3. Check both databases, backups, memory events and guard/transaction finalization.
4. Record code/CI/configuration/recovery acceptance separately. Preserve original failures and unverified gates.
5. Keep source reintroduction, Podcast/Blog stability, long-collector lock behavior, live quote/tool UAT, 48 healthy hours and offsite backup recovery open.
