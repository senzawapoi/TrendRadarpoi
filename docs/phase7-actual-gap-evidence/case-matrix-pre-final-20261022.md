# Phase 7 Actual-gap Case Matrix

Audit date: 2026-10-14, Asia/Shanghai. This is a draft assertion map for the
28 W/L/S scenarios in `TrendRadarpoi-Phase7-实际缺口测试计划.md`, not a completed
acceptance audit. Test counts are not coverage evidence. Result statuses use
`PASS`, `FAIL`, `NOT_RUN`, `BLOCKED`, or `WAIVED`; retention is described separately.
`PASS` is limited to the listed environment and reviewed assertions. `BLOCKED`
means supporting tests ran but complete scenario mapping or a required candidate
remains unresolved. The groups identified below still need assertion review.

## This audit

Windows focused command:

```text
python -B -m pytest -p no:cacheprovider tests/deployment/test_actual_gap_health.py tests/deployment/test_health.py tests/deployment/test_environment_loading.py tests/deployment/test_runtime_guards.py -q --tb=short
```

Result: **81 passed, 25 skipped**. The skips are Linux/POSIX controller,
installer, UID, or systemd scopes and do not count as passing assertions.

Combined policy command:

```text
python -B -m pytest -p no:cacheprovider tests/deployment/test_combined_readiness.py -q --tb=short
```

Result: **19 passed, 1.66s** (agent-reported terminal run). This uses real SQLite, `RoleHeartbeat`, `create_snapshot`,
the local/offsite receipt validator, and the real health CLI without Lark,
Gemini, collectors, or remote restic. Its policy fixture requires `bot` and
`worker`, two fresh successful source runs, and both local and receipt-bound
offsite backups.

Post-repair supplement: the Linux agent reported 26 passed/1 failed in 30.90s
for `test_remaining_gap_assertions.py` (session 63299); ENV-03 unreadable YAML
preflight is the failure. The frozen module has six functions/27 instances.
Parent Windows rerun passed 16 with 11 Linux-root skips in 9.14s. See
[assertion evidence](remaining-assertions-20261014.json) for scope and provenance.
Parent Linux CI wiring rerun passed 18 in 2.69s; this proves selection/argv/path
checks with stubbed sudo, not GitHub execution. The original RG-03 failure is
historical; [focused repair evidence](rg03-rollback-fix-20261014.json) supersedes
its diagnosis while full current-module regression remains open.

## ENV

| ID | Environment | Command / node | Inputs exercised | Proof boundary | Status |
|---|---|---|---|---|---|
| ENV-01 | L | `test_installer_behavior.py::test_fixed_entry_loads_common_and_clears_caller_environment`; `test_environment_entry_linux.py` fixed-entry scope | Trusted common.env, sanitized caller, independent health path, real readiness | Linux fixed-entry and 57-test installer results retained; not Windows | PASS |
| ENV-02 | W + L | Windows parser nodes; Linux `test_remaining_gap_assertions.py::test_fixed_entry_uses_all_configured_paths_for_actual_operations` | Six configured paths, actual migrations/checks, role heartbeat/locks, readiness, snapshot and restore preflight | Reviewed Linux supplement passed; parser behavior retained on Windows; helper is isolated, not target deployment | PASS |
| ENV-03 | L; W parser only | Fixed-entry invalid-input nodes; new `test_fixed_entry_quoted_values_and_missing_required_keys` and `test_fixed_entry_rejects_actually_unreadable_config_before_migration` | Legal quoted values and seven missing keys pass assertions; actual mode-000 YAML read fails under root without DAC bypass | Agent Linux run: 26 passed/1 failed. Loader checks existence and still invokes migration helper; full installer separately checks service readability | FAIL |
| ENV-04 | L | `test_environment_entry_linux.py::test_entry_maintenance_contends_for_real_role_lock` | Bot, worker, collector, scheduler x migrate/activate; held and released real file locks | Requires POSIX flock and fixed entry; no Windows equivalent was claimed | PASS |

## HEALTH

| ID | Environment | Command / node | Inputs exercised | Proof boundary | Status |
|---|---|---|---|---|---|
| HEALTH-01 | W + L | `test_actual_gap_health.py::test_bot_readiness_requires_connected`; `test_worker_uses_its_own_state_rules`; `test_real_transport_state_written_to_heartbeat_then_health` | Bot connected, connecting, retrying, cooldown, stopped, disabled, unknown, maintenance, disconnected; Worker running/invalid states | Windows real CLI and heartbeat files; fake transport/provider; Linux health results retained, not target lifecycle | PASS |
| HEALTH-02 | W | `test_actual_gap_health.py::test_heartbeat_identity_and_exact_age_boundary`; `test_health.py::test_health_rejects_disconnected_and_old_release_heartbeats` | Matching, old, unknown, missing, future, exact age and over-age heartbeat | Rejection boundaries plus 19 combined-readiness cases assert healthy/fault/repaired transitions | PASS |
| HEALTH-03 | W | `test_actual_gap_health.py::test_required_sources_cannot_be_empty`; `test_explicit_source_without_run_is_rejected`; `test_source_runs_required_and_fresh` | Empty expected/source sets, missing run, healthy, unhealthy, unknown, fresh, stale, require flag on/off | Real SQLite source_runs and readiness CLI; no upstream source call | PASS |
| HEALTH-04 | W | `test_actual_gap_health.py::test_queue_age_survives_recent_retry` | Retryable failed event below/equal/above threshold, completed event, exhausted retries | Real SQLite envelope and original reception time; reviewed against plan section 7. Multiple simultaneous pending events are not a required assertion | PASS |
| HEALTH-05 | W | `test_actual_gap_health.py::test_backup_gate_binds_receipt_and_data_age`; `test_health.py::test_health_ignores_malformed_offsite_array_without_crashing`; new `test_combined_readiness.py::test_actual_release_policy_requires_roles_sources_and_backups` | Fresh/old manifest, missing/array receipt, wrong digest, wrong backup ID, valid local/offsite receipt; all required gates enabled | New combined test proves final local policy composition; fake/local receipt only, no remote restic | PASS |
| HEALTH-06 | W | `test_actual_gap_health.py::test_health_and_readiness_preserve_readonly_exit_contract`; `test_health.py` missing/disabled/guard nodes | Missing DB, schema mismatch, disabled, maintenance, healthy; ordinary vs readiness exit codes | Read-only behavior and no database creation asserted; no production service process | PASS |

## PERM

| ID | Environment | Command / node | Inputs exercised | Proof boundary | Status |
|---|---|---|---|---|---|
| PERM-01 | L | `test_restore_permissions_linux.py::test_restore_keeps_service_metadata_and_real_uid_can_write` | UID/GID 65534, modes 0600/0660, intelligence/AI/legacy DBs, WAL write and denied UID | Actual service UID and POSIX metadata; Linux retained suite and 3-test permission rerun; full assertion audit remains open | BLOCKED |
| PERM-02 | L | Existing first-install/upgrade ownership node; `test_remaining_gap_assertions.py::test_first_install_service_uid_writes_both_databases_in_wal` | First-install parent/lock ownership, service UID/GID 65534, both schemas, committed writes and WAL/SHM | Existing retained permission result plus passing Linux supplement; real installer/SQLite/UID, simulated pip/venv/systemctl | PASS |
| PERM-03 | L/S | `test_restore_permissions_linux.py::test_first_install_and_upgrade_snapshots_use_actual_service_uid`; `test_systemd_contract_linux.py` | Service-created and installer-created snapshots, service UID fake-restic read, release identity | Fake restic is local; systemd unit evidence is separate from full production backup | PASS |
| PERM-04 | L | `test_restore_durability.py::test_target_metadata_failure_preserves_originals_and_protection`; crash/recovery modules | chown/chmod failure, present/missing targets, copy/switch/directory-fsync failures | Real restore journal/database set; review access and unrelated-directory invariants. Extra installer metadata-failure integration is not a plan requirement | BLOCKED |

## GUARD

| ID | Environment | Command / node | Inputs exercised | Proof boundary | Status |
|---|---|---|---|---|---|
| GUARD-01 | W + L | Runtime-guard nodes; `test_remaining_gap_assertions.py::test_uncontrolled_valid_deployment_stages_block_every_business_entry` | 12 valid stages including rollback, plus malformed/list/unknown records; all business entrypoints fenced, records unchanged, no new DB | Negative entry assertions pass on both platforms; controlled resume/completed positive-path mapping remains open | BLOCKED |
| GUARD-02 | W + L | Public-clear nodes; `test_remaining_gap_assertions.py::test_pending_restore_clear_keeps_every_business_entry_protected`; recovery modules | Four pending/malformed journals; clear refused; all entrypoints fenced; guard/journal bytes retained | Parent Windows and agent Linux negative assertions pass; validated completion/rollback-to-clear mapping remains open | BLOCKED |
| GUARD-03 | L | `test_installer_behavior.py::test_installer_interruption_preserves_protection` | Before/after clear, first start, verify, finalize; SIGKILL, SIGTERM, ordinary exception | Real Bash child/process group with fake systemctl; guarded API is connected; full Bash installer module passed 57 tests | PASS |
| GUARD-04 | L | `test_installer_behavior.py::test_installer_post_boundary_failure_stops_roles_and_retains_guard` | One role start failure, readiness failure, health command exception; post-boundary stop and restart protection | Fake systemctl and real health/database operations; guarded rollback API is connected and the full Bash installer module passed | PASS |
| GUARD-05 | L | `test_restore_crash_recovery.py::test_abrupt_restore_death_and_idempotent_complete_rollback`; durability tests | prepared, old moved, new placed, first complete; missing second DB; WAL/SHM | Actual child SIGKILL and restore journal; not installer deployment rollback | BLOCKED |
| GUARD-06 | W + L | `test_restore_crash_recovery.py::test_interrupted_recovery_can_be_repeated_from_consistent_snapshot`; recovery mapping tests | Repeated recovery, corrupt destination/snapshot/metadata/mapping, missing target | Windows/Linux retained restore evidence; operational recovery command documentation is not revalidated here | BLOCKED |
| GUARD-07 | L | `test_installer_behavior.py` finalize interruption and confirmation nodes | Normal finalize, interruption after finalize persistence, marker confirmation/mismatch | Local fake service and health; API connected and Bash installer module passes; scenario assertion audit remains open | BLOCKED |

## RG

| ID | Environment | Command / node | Inputs exercised | Proof boundary | Status |
|---|---|---|---|---|---|
| RG-01 | L | `test_release_inputs.py` workflow validator, host-key ordering and fixed-entry nodes | Path/release/user/host/port whitespace, quotes, slashes, traversal, shell text, host-key mismatch | Linux-only workflow/fixed-entry behavior; no Windows execution in this audit | PASS |
| RG-02 | L | `test_release_inputs.py::test_real_installer_rejects_bad_manifests_before_migration_or_switch`; unsafe tar nodes | SHA/release/dirty/missing JSON, traversal/absolute/wrong-root/symlink/hardlink/FIFO | Installer archive handling is real but pip/systemctl are simulated; current Linux release-input module passed in retained 147-pass/1-permission-fixture-failure scope | PASS |
| RG-03 | L + S | Systemd quiesce module; repaired snapshot-backed rollback node with expired-lease variant | Active/inactive writers/timers; service-identity confirmation; controlled expired lease | Historical 9-pass/1-failure retained. Original node now passes; expired-lease/rollback/confirmation scope 29 passed. Full current-module rerun and mapping remain open | BLOCKED |
| RG-04 | L | `test_release_install_linux.py::test_locked_artifact_installs_into_empty_venv_and_runs_without_checkout` | Real empty Python 3.10 venv, build lock, runtime lock, no-build-isolation install, pip check, smoke | Real empty-venv installation passed 1 test, 42.01s; dirty=true, clean_candidate=false; clean candidate remains blocked | BLOCKED |
| RG-05 | W + L | `test_offsite_backup.py`; `test_offsite_processes.py` | Fake success/failure/timeout, inherited/detached child, secret sentinel, Windows Job attachment cases | Local fake restic only; Windows Job cases are skipped on Linux and require Windows execution | PASS |
| RG-06 | W + L | Final parent command; current focused health/guard/env command above | Cross-module regression including Intelligence-off, Lark-off, role isolation and existing Feishu guarantees | No final full run in this audit; overlapping historical counts are not closure evidence | NOT_RUN |
| RG-07 | S | `test_systemd_contract_linux.py::test_real_backup_unit_environment_defaults_overrides_and_release` | Real systemd, unprivileged UID, default 900/10 and override 123/7, release identity | Proves backup unit only; does not prove all role/timer quiesce ordering | PASS |

## Explicit Open Items

1. Fix ENV-03 actual YAML readability in `scripts/deploy/load_environment.py`
   before invoking maintenance; retain sanitized errors and the failing test.
2. Finish assertion mapping for PERM-01/04 and GUARD-01/02/05/06/07. Review
   controlled positive paths, interrupted journal sets, per-database schema/FK,
   and data identity after confirmation. Supporting module totals do not close
   draft rows. Do not add non-plan multiple-pending or installer-metadata gates.
3. RG-04 dirty installation mechanics passed; an authorized clean candidate
   remains BLOCKED. RG-06 final full regression is NOT_RUN.
4. Privileged CI includes rollback/readiness/quiesce/assertion modules and passed
   18 local wiring checks; retain a real GitHub run. No workflow execution is claimed.
5. Retained commands, sessions and artifact metadata are in
   [verification checkpoint](verification-checkpoint-20261014-0804.json);
   [handoff](HANDOFF.md) gives the resume order. G1/G2 remain incomplete.

Cleanup reran only the frozen assertion module on Windows and CI wiring on
Linux. No full regression or live Lark/Gemini/source/restic calls were made;
agent-reported Linux results remain identified as such. The original RG-03
failure directory and earlier checkpoints remain unchanged.
