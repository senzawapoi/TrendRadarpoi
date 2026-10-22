# Phase 7 Actual-gap Handoff

## Active Handoff: 2026-10-22

**Authorized local work is complete.** No test session is running. Do not poll
historical handles or repeat completed regression without new changes.
[Final report](verification-20261022.md), [run record](final-run-v6-20261022.json),
[28-case matrix](case-matrix.md) and [per-case JSON](case-results-20261022.json)
are the current authority; everything below is retained historical context.

Candidate: dirty `main`, HEAD
`5a427aba5ded0c9c9c9e050413dcb41f17fa0e23`.
[v6 manifest](final-inputs-v6-20261022.json) binds 301 source/resource files,
plus 12 separately recorded constraints. Manifest SHA256:
`236de09722e23237d99aee0b1680ec020709ce61066e57ca85779e57d47ca4cf`.
All 301 source hashes were unchanged after both full runs and installation,
and all corresponding archive members match. Narrative status documents were
reconciled afterwards.

| Direct final execution | Result | Exit |
| --- | --- | --- |
| Isolated Windows full tests | 683 passed, 342 skipped, 2 warnings, 46.20s | 0 |
| Linux WSL full tests | 1019 passed, 6 skipped, 2 warnings, 1060.42s | 0 |
| Separate dirty empty-venv installation | 1 passed, 41.23s | 0 |
| Real systemd quiesce within Linux full | 11 passed | 0 |
| Real systemd backup units within Linux full | 2 passed | 0 |

Windows Python3.10.11/SQLite3.40.1; Linux Python3.10.22/SQLite3.53.1,
root/systemd, actual service UID65534 and retained `PrivateTmp`.
[Skip audit](skip-audit-v6-20261022.json) explains every platform/opt-in skip.
Authlib jose/httpx warnings are retained. These scopes overlap, never add counts.

H1-A..D are complete and mapped to final JUnit. Production repairs declare
Windows tzdata and use a same-boot CLOCK_BOOTTIME controller lease while
retaining the 15-second bound and identity checks. Legacy UTC and invalid,
future, expired lease cases remain. Modern positive fixtures now use current
installer records; [91-test focus](positive-lease-fixture-20261022.json) passed.
Historical v3 telemetry, v4 generic health and v5 legacy-fixture failures remain
retained; failure-time UTC age was not captured for v4/v5.

[Actual artifact](artifact-install-evidence-v6-20261022.json):
`480430d8976ac499c7cd1e9dc35c0a37cab4ed4acf1fcdf7801c0f954a13c255`,
11,880,521 bytes, `git_dirty=true`, `clean_candidate=false`.
Real build/runtime/project installation, pip check, outside-checkout imports
and smoke passed. The archive remains in the isolated Linux fixture.
Installer control-flow pip/venv/systemctl mocks are distinct from this install.

**27 PASS, 1 BLOCKED (RG-04 clean candidate). G1 PASS; G2 BLOCKED; G3 and
V-01..06 NOT_RUN/BLOCKED.** No commit/push or target operation is authorized.
Next requires an authorized committed candidate, real GitHub run/artifact
binding, and explicit VPS/SSH/config/backup/isolated-restore authorization.
Keep DEPL-01..05 open. V-06 still needs at least 48 hours, two actual daily
delivery windows and one controlled recovery. Phase 5 B6 non-whitelisted
branch remains an accepted skip; C3/C4 remain open.

Preserve all user changes, runtime DB/WAL/SHM, audit/failed fixtures, caches and
both Linux toolchains. Do not retry blocked cache deletion. Do not call real
providers, remote restic or credentials. No second Bot was started.
Local verification confidence: high; production behavior: unknown.

## Historical Resume Sections (Superseded)

## Current Resume: 2026-10-15

The dated [Codex operation guide](../../TrendRadarpoi-Phase7-Codex交接操作指南-2026-10-15.md)
supersedes the resume instructions in the historical checkpoint below. ENV-03
is fixed: [48-pass evidence](env03-readability-fix-20261014.json). Historical
session 9378 completed: **466 passed, 6 skipped, exit 0, 1083.62s** for
`tests/deployment`; this is not a full-project run. No active pytest process
was found on Windows or WSL at resume. Ubuntu still has root/systemd and the
retained Python 3.10.22 / SQLite 3.53.1 interpreter outside temporary paths.

Next: H1-A..D (all-role completion acceptance, crash-generated pending fences,
public maintenance clear, dual-database/release identity), focused verification,
frozen full Windows/Linux regression, dirty installation and the 28-case audit.
[Resume checkpoint](resume-checkpoint-20261015.md) and
[290 input hashes](resume-inputs-20261015.json) identify this dirty baseline.
No commit, push, provider call, production deployment or cache deletion is
authorized. Clean candidate, GitHub, V-01..06 and the retained Phase 5 live gaps
remain open.

## Historical Checkpoint (Superseded Resume Instructions)

Checkpoint: 2026-10-14 (Asia/Shanghai). Work is uncommitted on `main`, ahead of
`origin/main` by 42 commits; HEAD is `5a427aba5ded0c9c9c9e050413dcb41f17fa0e23`.
HEAD alone does not identify this dirty worktree. This is an unfinished repair
checkpoint, not release acceptance. Scope remains the
[actual-gap test plan](../../TrendRadarpoi-Phase7-实际缺口测试计划.md) and
[07-05 plan](../../.planning/phases/07-deployment/07-05-PLAN.md).

## Current Repair Checkpoint

The guarded `backup activate --deployment-rollback` CLI/API now exists.
`test_deployment_rollback.py` covers controller authority, explicit pre-business
boundary, complete snapshot mapping, absent targets and previous cutover
preservation. The Bash installer suite passed 57 tests, using actual migrations,
health and service UID while simulating pip/venv/systemctl.

The real-systemd RG-03 module returned **9 passed, 1 failed**. In
`test_snapshot_backed_rollback_keeps_real_writers_stopped_and_restores_active_units`,
databases were restored, but none of the four formerly active units restarted.
The guard and failed transaction remained. Evidence is retained under
`/var/lib/p7-quiesce-awgdsbgc`; exact test units were stopped and removed.
Subsequent diagnosis confirmed service-UID `Permission denied` on the root-owned
0600 `restore-guard.json`. Automatic restore/activation now run as the same
service identity as confirmation; the formerly failing node passed. The new
expired-restore-lease scenario also passed after explicit rollback-stage
renewal. [Repair evidence](rg03-rollback-fix-20261014.json) retains the failed
diagnostic, successful isolated directories and exact commands. The earlier
9/1 full-module result remains historical until final regression runs.

Both agents completed and were closed during cleanup, then resumed for remaining
assertion mapping and CI wiring. Both are now frozen and closed again. The
privileged CI scope includes the new rollback/readiness/quiesce/assertion modules;
the parent reran all 18 wiring tests, including target-file existence, with
18 passed in 2.69s. This is separate from actual GitHub execution.

The remaining-assertion module exposed **ENV-03**: the trusted loader checks
`CONFIG_PATH.is_file()` without reading the file. Under root with DAC bypass
capabilities removed, a mode-000 YAML file fails an independent read, yet the
fixed entry reaches its isolated real-migration helper and creates schema v6.
The Linux agent run returned 26 passed/1 failed in 30.90s. The complete installer
has a separate service-readability check; this failure specifically concerns
fixed-entry preflight and must not be generalized to a proven VPS failure.
The failing regression remains enabled. Parent Windows verification of the
frozen module passed 16 tests with 11 Linux-root skips in 9.14s.
[Assertion evidence](remaining-assertions-20261014.json) records provenance and
remaining mapping work. RG-04 dirty installation passed; clean-candidate and
GitHub CI gates remain open. No full regression was run by this cleanup.

## Evidence And Its Limits

All executed database/service tests used isolated fixtures. Lark, Gemini,
collectors and remote restic were not called. The latest
[workspace cleanup record](workspace-cleanup-20261014-post-rollback.md) distinguishes direct
checks, retained logs and agent-reported results. The following scopes overlap;
never add their counts or describe them as final regression.

| Environment | Executed scope | Result |
| --- | --- | --- |
| Earlier Windows checkpoint | Health, guards, parser, fake restic and restore | 101 passed, 25 skipped |
| Earlier Linux checkpoint | Health, guards, fixed entry, real locks and fake restic | 120 passed, 1 skipped |
| Earlier Linux/systemd checkpoint | Restore, service UID and backup-unit defaults/overrides | 24 passed |
| Linux archived pre-fix F-01/F-04 | Actual archived CLI and root/service-UID restore | 2 reproduction assertions passed; archived behavior failed the intended contracts |
| Restore follow-up | Linux durability module; Windows combined restore scope | 20 passed; 38 passed, 5 POSIX skips |
| Earlier RG-01/RG-02 agent checkpoint | Workflow literal validation, host-key ordering, real archive rejection | Agent reported 122 passed before later installer changes |
| Linux full Bash installer | Actual installer, simulated pip/venv/systemctl | 57 passed, 583.88s |
| Linux restore/rollback, five modules | Real SQLite and controlled restore faults | 58 passed, 10.13s; predates two new rollback cases |
| Linux expanded deployment rollback | Controller/snapshot/absent-target/cutover behavior | 17 passed, 1.21s |
| Linux environment/permission/archive/backup-unit scope | 147 passed, 1 fixture failure, 57.96s | Ops-log UID fixture corrected; affected permission module then 3 passed, 23.65s |
| Linux RG-03 systemd quiesce | Real services/timers, UID 65534, SQLite and PrivateTmp; dependency setup simulated | 9 passed, 1 failed, 292.55s |
| Linux RG-03 repaired restart node | Service-identity confirmation and old active units restored | 1 passed, 26.96s |
| Linux expired lease plus rollback/confirmation | Real systemd lease fault, 18 rollback cases and 10 confirmation cases | 29 passed, 29.17s |
| Linux restore/crash follow-up | Durability, abrupt death, repeated rollback and complete snapshots | 43 passed, 9.62s |
| Linux remaining assertion module | Agent-reported actual fixed entry, UID/WAL and role fences | 26 passed, 1 failed, 30.90s; ENV-03 unreadable-config preflight |
| Parent Windows frozen assertion module | Role entrypoints and pending-clear refusal; Linux-only cases skipped | 16 passed, 11 skipped, 9.14s |
| Parent Linux CI wiring | Actual YAML/Bash argv with stubbed sudo and target-file existence | 18 passed, 2.69s; no GitHub run |
| Linux RG-04 empty-venv installation | Locked build/runtime/project install, pip check, outside-checkout smoke | 1 passed, 42.01s; dirty artifact only |
| Windows parent focus | Health/guards/environment/fake offsite processes/rollback | 95 passed, 40 platform skips, 9.65s |
| Windows agent combined readiness | Bot/Worker, two required sources, both backups; healthy/fault/repaired transitions | 19 passed, 1.66s |
| Windows agent fake-restic/process/role focus | Fake external boundaries | 17 passed, 13.22s |

The [earlier cleanup log](cleanup-verification-20261014.txt) and
[source hashes](checkpoint-source-sha256.json) remain historical: the latter was
captured at 06:37:16 UTC, and 11 of its 49 source paths had changed by this cleanup.
It is neither a current-tree digest nor a final manifest. The
[earlier cleanup](workspace-cleanup-20261014.md) remains historical; this handoff
supersedes its resume status. The historical 531-test full run also predates
these edits. Earlier `203/EXEC` backup-unit failures were
resolved by moving the interpreter outside `PrivateTmp`; both cases passed.

## Current Implementation And Proven Behavior

| Area | Code and executed assertions | Remaining work |
| --- | --- | --- |
| F-01 configuration | Trusted `common.env`; sanitized entry; six paths used by real operations; actual lock contention; archived Linux failure reproduced | Fix ENV-03 unreadable-config preflight, then rerun affected Linux tests |
| F-02 role readiness | Bot requires `connected`, Worker `running`; wrong-release, stale/future and absent heartbeats reject readiness | Per-case assertion audit and target lifecycle |
| F-03 source proof | Required empty/missing source runs reject readiness; freshness boundary and durable queue age tests | Final combined-policy matrix |
| F-04 permissions | Actual service UID/WAL access; archived ownership regression reproduced; metadata-failure tests added | Per-case PERM audit and final integrated regression |
| F-05 protection | Invalid transactions block all roles; controller/lease checks; installer exception/signal tests; repaired real-systemd rollback node passes | Audit remaining positive paths and complete final regression |
| Restore recovery | Journal fsync errors propagate; tracked renames; absent targets and previous cutover preserved; interrupted rollback recovery tested | Final regression and per-case audit |
| Offsite backup | Actual fake-process timeout/descendant cleanup on both platforms; Windows suspended-process/Job attachment failure tests | Real remote acceptance and final regression |
| systemd backup | Actual unprivileged unit retains `PrivateTmp`; defaults 900/10 and overrides 123/7; service reads release identity and creates snapshot | Full RG-03 lifecycle rerun after focused repair remains open |

The first-install/upgrade harness performs real migrations, health and service
UID operations, but simulates pip, venv setup and systemctl. Its success does
not establish a release archive installation or production upgrade.

## Resume Order

1. Fix ENV-03 in `scripts/deploy/load_environment.py`: verify actual YAML
   readability before executing the maintenance helper; preserve sanitized
   errors and data-only parsing. Rerun the unreadable-config regression and
   affected parser/fixed-entry tests. Do not skip or weaken the failing test.
2. Finish the remaining assertion mapping and bounded tests, then freeze the
   implementation for final full Windows/Linux regression. The RG-03 permission
   failure, restore lease refresh and strict-false rollback confirmation have
   focused passing evidence; do not restart their diagnosis.
3. Retain the original RG-03 failure and the follow-up fault directories; do
   not modify their transaction/guard records to manufacture completion.
4. Finish the [28-case draft](case-matrix.md), especially PERM-01/04 and
   GUARD-01/05/06/07. Negative entry fences now have evidence; review controlled
   resume/completion and journal/schema/FK invariants. HEALTH-04 does not require
   an invented multiple-pending condition. Module counts alone do not close
   unreviewed requirements. CI path/wiring checks passed; retain a real GitHub run.
5. After repairs stabilize, run final full Windows regression and required
   Linux/systemd/UID scopes, scoped Ruff, syntax, workflow and artifact checks.
   Freeze final hashes and update acceptance/state records. The dirty RG-04
   installation need not be repeated without a relevant code change.

RG-04 used Python 3.10.22 / SQLite 3.53.1. Its artifact SHA256 was
`1c61f44fdc665888c06f0c5cde335e748fca1b171f72c128965736180e9e641c`
(11,256,939 bytes), `git_dirty=true`, `clean_candidate=false`. This is retained
run metadata, not a newly built archive. The clean production candidate stays
BLOCKED without an authorized committed revision; never alter `git_dirty`.
Earlier commands, sessions and lock hashes are in the
[historical checkpoint](verification-checkpoint-20261014-0804.json); the
[post-repair source inventory](cleanup-source-sha256-20261014-post-rollback.json)
identifies cleanup inputs and is not a final release manifest.

Pre-fix F-02/F-03/F-05 evidence remains in `pre-fix-windows.txt` (21 failed,
4 passed). [Archived Linux evidence](pre-fix-linux.json) now supplies F-01/F-04.
[Restore follow-up evidence](restore-durability-20261014.json) records its actual
before/after results. Do not describe repaired source as pre-fix evidence.

## Retained Environment And Workspace

Use the service-test interpreter outside temporary namespaces:

```text
/var/lib/trendradar-p7-gap-20261014/venv310/bin/python
/var/lib/trendradar-p7-gap-20261014/python/cpython-3.10.22-linux-x86_64-gnu/
```

The original `/var/tmp/trendradar-p7-gap-20261014/` toolchain (`python`,
`venv310`, `uv`, `wheels310`) remains retained for reproduction. Do not use it
with `PrivateTmp=yes`. `/var/lib/trendradar-p7-build-lock-20261014` retains the
separate build-lock resolution venv. Keep deployment helper imports relative, e.g.
`from .installer_harness import make_installer`, for collection on both platforms.

Read-only cleanup checks found no Windows Python/pytest/Ruff process or WSL
test process, and no `trendradar-p7-test-*` unit or unit file. The WSL Python
inspection process excluded itself. Recheck before future restart or cleanup.

There are still 19 ignored `__pycache__` directories outside protected state
and an ignored `.ruff_cache/`; no root `.pytest_cache/` was found.
Their prior recursive deletion was rejected by automatic approval review with
`blocked by policy`; no retry or alternative deletion tool was used.

Preserve all source changes, requirement documents, GSD history, `dist/` audit
archives, this evidence directory, both Linux toolchains, `output/` and
`test/runtime/` including WAL/SHM, fixtures and logs. This cleanup only updates
documentation; it does not commit, push, restart the Bot, deploy or read credentials.

## Gates

G1/G2 remain incomplete: the 28-case audit, final regression,
clean candidate and CI evidence remain open. G3/V-01..06 remain NOT_RUN/BLOCKED
pending authorized VPS/SSH, runtime configuration, backup access and an
isolated restore target. The Phase 5 B6 non-whitelisted branch remains an
accepted skip; C3 real interruption and C4 receipt confirmation remain open.

Confidence: high for the executed scoped results; unknown for production operation.
