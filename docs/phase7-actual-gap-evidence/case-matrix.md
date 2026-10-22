# Phase 7 Actual-gap Case Matrix

Audit date: 2026-10-22, Asia/Shanghai. Final local candidate:
[dirty v6 manifest](final-inputs-v6-20261022.json).
The original 28 requirement rows, reviewed assertions and matching executed
JUnit nodes are bound in [case results](case-results-20261022.json).
[Assertion review](reviewed-assertions-20261022.json) remains a pre-execution
snapshot; its pending label is historical. The superseded
[draft matrix](case-matrix-pre-final-20261022.md) is retained.

**27 PASS, 1 BLOCKED (RG-04 clean candidate).** These are scenario statuses,
not a percentage of product or production acceptance. PASS is restricted to
the listed W/L/S environment and reviewed assertions.

## Final Execution

| Scope | Actual result | Exit |
| --- | --- | --- |
| Isolated Windows full tests | 683 passed, 342 skipped, 2 warnings, 46.20s | 0 |
| Ubuntu WSL full tests | 1019 passed, 6 skipped, 2 warnings, 1060.42s | 0 |
| Separate Linux empty-venv dirty installation | 1 passed, 41.23s | 0 |
| Real systemd quiesce within Linux full | 11 passed | 0 |
| Real systemd backup unit within Linux full | 2 passed | 0 |

Overlapping scopes must not be added. Exact commands, interpreter identities,
fixture directories and logs: [final run](final-run-v6-20261022.json).
All 301 frozen source/resource hashes remain unchanged and match archive
members. Narrative evidence and status documents were reconciled afterwards.

## Reviewed Scenarios

| ID | Required environment | Executed assertions and boundary | Status |
| --- | --- | --- | --- |
| ENV-01 | L | Trusted common.env under sanitized caller; independent heartbeat directory; actual health CLI reaches finalize; no manual caller export.  | PASS |
| ENV-02 | W+L | All six paths used by migrations, health, real locks, snapshot and restore preflight; no default path created.  | PASS |
| ENV-03 | L | Missing keys, malformed quoting, directory/unreadable config, substitution and untrusted modes rejected before writes; quoted valid values succeed; errors sanitized.  | PASS |
| ENV-04 | L | Four roles times migrate/activate contend for same actual flock; DB unchanged on conflict; operations succeed after release.  | PASS |
| HEALTH-01 | W+L | Nine Bot states and five Worker states; only accepting state ready; real transport state writes heartbeat and actual health CLI reads it.  | PASS |
| HEALTH-02 | W | Fresh matching release accepted; missing/unknown/old release, absent role, future/stale heartbeat rejected; exact boundary accepted; healthy/fault/repaired transitions.  | PASS |
| HEALTH-03 | W | Required empty/missing/unhealthy/unknown/stale sources rejected; valid fresh runs pass; disabled requirement preserves compatibility.  | PASS |
| HEALTH-04 | W | Original received_at ages below/equal/above wait bound; recent retry does not reset age; completed/exhausted events excluded.  | PASS |
| HEALTH-05 | W | Fresh local/offsite proof passes; stale data despite fresh upload, wrong digest/ID, missing/array receipt reject without crash; disabled requirement compatible.  | PASS |
| HEALTH-06 | W+L | Missing/schema/disabled/maintenance/healthy across ordinary and readiness exit contracts; read-only checks never create missing DB.  | PASS |
| PERM-01 | L | Root restore/activate preserves UID/GID65534 and 0600/0660 on three databases; actual service SELECT/WAL write/commit succeeds; UID65533 denied.  | PASS |
| PERM-02 | L | First install creates both schemas and owned parent/DB/locks; service UID commits both databases and checks WAL/SHM.  | PASS |
| PERM-03 | L | Installer and daily service-created complete snapshots readable by actual UID, no world-readable snapshot files, next snapshot/upload works; release identity readable.  | PASS |
| PERM-04 | L | chown/chmod/copy/switch x present/absent targets; failure retains guard, rolled_back journal/no pending, old data and UID WAL access; unrelated owner/group/mode/sentinel unchanged.  | PASS |
| GUARD-01 | W+L | Uncontrolled valid stages and invalid records fence six main entrypoints without business/client I/O; live exact controller permits resume/verify/finalize; actual public completion/rollback reaches six sentinels.  | PASS |
| GUARD-02 | W+L | Public clear rejects prepared/installing/malformed/list journals and preserves guard/journal bytes plus six-entry fences; successful activation terminal journal/no pending allows public clear.  | PASS |
| GUARD-03 | L | Actual Bash exception/SIGTERM/SIGKILL before clear, after clear, first-start, verify and finalize; boundary/snapshot/release persisted; six-entry restart protection.  | PASS |
| GUARD-04 | L | Worker-start/readiness/health-exception failures stop resumed roles and retain guard; post-boundary candidate data not overwritten; pre-boundary code/data/release/unit state restored.  | PASS |
| GUARD-05 | L | Five real interruption points x present/absent second target; actual WAL/SHM, pending/journal/original/retained/installed locations; six-entry fences before recovery; no finally-dependent cleanup.  | PASS |
| GUARD-06 | W+L | Actual interrupted journal recovery restores complete three-DB schemas/content/FKs/integrity; absent DB/WAL/SHM remains absent; repeated interrupted recovery safe; corrupt mapping/snapshot/metadata refused before mutation.  | PASS |
| GUARD-07 | L | Actual success and public finalize confirmation preserve both original DB probes/schema/integrity/FKs; current link/release.env stable; mismatched release/current/heartbeat/pending states refuse confirmation.  | PASS |
| RG-01 | L | Execute actual workflow validators/fixed entry with path/release/host/user/port attack inputs; bad host key rejects before scp/remote mutation; fixed root-controlled installer cannot be replaced by archive.  | PASS |
| RG-02 | L | Real archive/manifest SHA/release/dirty/missing/malformed/traversal/absolute/wrong-root/link/FIFO reject before migration/switch; valid synthetic archive proceeds.  | PASS |
| RG-03 | L+S | Real writers/timers stop before snapshots/migrations; timer race suppressed; only active/configured initial units resume; inactive upgrade stays inactive; pre/post-boundary failures and expired rollback lease validated as service UID.  | PASS |
| RG-04 | L | Actual empty Python3.10 venv, both dependency locks and project installation, pip check, outside-checkout imports/smoke; no DB/.env/cache in archive; missing DB not created. Dirty mechanism passes; authorized clean revision absent. | BLOCKED |
| RG-05 | W+L | Fake success/nonzero/timeout; inherited/detached child death and no leaked success receipt; manifest-bound redacted receipt; actual Windows Job attachment failures reap suspended processes.  | PASS |
| RG-06 | W+L | Complete tests, rollback compatibility, disabled switches, completed-event suppression, saved-reply retry, role isolation, reconnect bounds; scoped Ruff/AST/Bash/diff and dependency checks.  | PASS |
| RG-07 | S | Actual systemd unit under UID65534 and PrivateTmp; default timeout900/grace10 and overrides123/7; release.env group readability and service success.  | PASS |

Per-case node references, parameter counts, original required input/assertion
text, each environment's PASS/SKIP results and limits are in the JSON.
No row was closed from module totals alone. Actual service UID is 65534;
permission tests also reject UID 65533. SIGKILL is not power-loss evidence.

## Skips, Warnings And Gates

The [skip audit](skip-audit-v6-20261022.json) lists every skipped node. Windows
Linux/POSIX/root/systemd skips have Linux execution; the three Linux Windows
Job Object skips have Windows execution. Two archived pre-fix cases retain
[historical reproduction](pre-fix-linux.json), not current-source acceptance.
The opt-in install skip is covered by the separate actual archive installation.
Two Authlib jose/httpx deprecation warnings per full run are retained, not suppressed.

- G1: PASS for reviewed logic regression and ENV/HEALTH/GUARD assertions.
- G2: BLOCKED by RG-04's clean production candidate.
- G3/V-01..06: NOT_RUN/BLOCKED; target, 48-hour/two-delivery-window and recovery evidence absent.
- Actual GitHub CI, remote backup and DEPL-01..05 target/operations evidence remain open.
- Phase 5 B6 non-whitelisted branch is an accepted skip; C3/C4 remain open.

No commit, push, GitHub execution, provider, remote restic or VPS action.
Retain all historical failures, runtime state, audit archives and toolchains.
