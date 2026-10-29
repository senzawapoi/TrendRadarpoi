# Phase 7 Acceptance Record

Historical checkpoint through 2026-10-22. Later deployment and title-translation
repair status are in the [current handoff](phase7-release-20261023/HANDOFF.md).
The unfilled gates below preserve this earlier evidence boundary.

This is an evidence form, not a claim that deployment has happened. Updated
2026-10-22: H1-A..D, timezone and controller-lease repairs have focused passing
evidence. Frozen v6 Windows and Linux full regression and dirty installation pass.
Matrix: 27 PASS/1 BLOCKED (RG-04 clean candidate). G1 PASS; G2 blocked; G3 open.
Confidence is high for executed scope and unknown for VPS operation.

## 2026-10-22 Actual-Gap Checkpoint

Use the [dated report](phase7-actual-gap-evidence/verification-20261022.md),
[run record](phase7-actual-gap-evidence/final-run-v6-20261022.json) and
[handoff](phase7-actual-gap-evidence/HANDOFF.md). The candidate is dirty, frozen
by 301 source/resource hashes. H1 passed 22 Linux tests; lease/rollback/complete
real-systemd focus passed 118; post-diagnostic-removal UID/timer scope passed 2.
Windows full: 683 passed/342 skipped/2 upstream warnings, 46.20s. Linux full:
1019 passed/6 skipped/2 warnings, 1060.42s. Separate real dirty empty-venv install:
1 passed, 41.23s. All exit 0; no active test session. Linux full includes 11
real systemd quiesce and 2 backup-unit cases. All 301 source/resource hashes
and archive members match. Do not add overlapping counts. See
[per-case mapping](phase7-actual-gap-evidence/case-results-20261022.json) and
[every skip](phase7-actual-gap-evidence/skip-audit-v6-20261022.json).

Historical ENV-03, root-owned-guard and `203/EXEC` failures remain in the
[evidence index](phase7-actual-gap-evidence/README.md). ENV-03 was fixed before
this continuation; its 48-test follow-up and the 466-pass/6-skip deployment-only
run are not current full-project results. Real GitHub execution, clean candidate,
V-01..06 and Phase 5 C3/C4 remain unverified; B6 retains its accepted exception.

## Historical offline evidence (2026-10-13)

| Area | Command | Result |
|---|---|---|
| Existing Lark/Feishu compatibility | `python -B -m pytest tests/integrations/feishu -q -p no:cacheprovider` | 78 passed, 1 existing warning |
| Phase 7 role boundaries | `python -B -m pytest tests/integrations/feishu/test_phase7_roles.py -q -p no:cacheprovider` | 5 passed |
| Health, backup, and restore guard | `python -B -m pytest tests/deployment -q -p no:cacheprovider` | 23 passed |
| Full regression | `python -B -m pytest tests -q -p no:cacheprovider` | 531 passed, 1 existing warning |
| Focused Ruff | `python -m ruff check trendradar/ai_frontier trendradar/ops scripts/deploy tests/deployment tests/integrations/feishu` | passed |
| Source artifact | `python -B scripts/deploy/build_release.py ...` | passed on Windows |
| Host preflight | `python -B scripts/deploy/preflight.py --json` | Windows evidence only; systemd unavailable |

The role tests prove offline isolation, durable polling, duplicate behavior,
and no-I/O `--check`. The deployment tests also cover `FULL` SQLite policy,
strict AI Frontier database opening, complete multi-database restore/activation,
backup discovery for news/rss date partitions, and the persistent restore guard.
These historical tests do not prove SDK connection acceptance, systemd restart behavior, Linux
file locking across hosts, restic repository access, or a live Lark tenant.

The installer writes the active `deploy-in-progress.json` marker before the
archived transaction record at every stage and removes it only after readiness
passes. A failed or interrupted release therefore keeps the latest active
stage as the recovery authority.

## VPS preflight to fill

```text
Host/authorization:
OS and architecture:
Python/pip:
SQLite library and WAL patch evidence:
systemd/cgroup version:
MemTotal/swap/disk/inodes:
Service/deployment users:
Existing cron/Docker/Actions schedules:
Outbound DNS/TLS/WSS result:
Backup destination and restore access:
Release ID and artifact SHA256:
```

## Acceptance matrix

| Gate | Status | Required evidence |
|---|---|---|
| DEPL-01 Bot/Worker systemd lifecycle | Not executed | `systemctl`, role logs, stop/start/restart, single-instance proof |
| DEPL-02 scheduler/health/data flow | Local matrix passes; target open | VPS source/queue/scheduler evidence |
| DEPL-03 CI/build/backup/release | Local checks pass; external gate open | Clean candidate, real CI/release and remote backup evidence |
| DEPL-04 runbook | Updated, operator drill pending | Operator follows `docs/deployment.md` on a disposable target |
| DEPL-05 resource stability | Not executed | cgroup peak samples under combined workload |
| Phase 5 C3/C4 live gates | Open from prior record | real interruption/recovery and recipient confirmation |

## Evidence format

For every executed scenario record the command, host/release, redacted config
scope, database/schema, exit code, observed result, log path, external calls,
and remaining limits. Do not attach secrets, full message bodies, images,
provider payloads, or UAT databases to CI artifacts.

## Remediation evidence

On 2026-10-13 (Asia/Shanghai), the remediation changes were exercised locally
with temporary SQLite databases and a fake restic process:

| Check | Result |
| --- | --- |
| Deployment-focused pytest, including backup, health, fake restic and restore interruption | 23 passed |
| Scoped Ruff for operations, deployment scripts, Feishu roles and deployment tests | passed |
| Bash syntax checks for installer, Linux smoke and release smoke scripts | passed |
| Source artifact and manifest build | passed; dirty local worktree is marked dirty and is not a production candidate |
| Real VPS, systemd lifecycle, GitHub Actions run, remote restic, provider or Lark call | not executed |

The historical remediation evidence is offline only and predates the current
actual-gap repairs. The production readiness command is
an explicit gate and must have a prepared database, configured expected roles,
valid source/backup policy and an active release ID. The ordinary health
command retains its compatibility behavior for disabled and maintenance
profiles.
