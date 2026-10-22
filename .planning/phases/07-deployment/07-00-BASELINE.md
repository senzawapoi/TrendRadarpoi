# Phase 7 W0 Baseline

**Captured:** 2026-10-12 Asia/Shanghai

## Repository

- Branch: `main`, ahead of `origin/main` by 42 commits at capture time.
- Working tree: contains substantial uncommitted Phase 1-6 work and user
  documents. No reset, stash, clean, commit, push, or deployment was done.
- Runtime state preserved: `output/`, `test/runtime/`, SQLite WAL/SHM, UAT
  fixtures and logs.

## Runtime facts

- Public Lark entry remains `python -m trendradar.integrations.lark`.
- Phase 7 adds `--role combined|bot|worker|scheduler-once`; the old no-role
  command remains combined compatibility mode.
- Intelligence database schema is v6. `EventLedger` and
  `DeliveryScheduler` remain the only event/daily-delivery ledgers.
- Lark SDK is pinned to `lark-oapi==1.7.3`; project package version remains
  `4.6.0`.
- Local host evidence: Windows, Python 3.10.11, SQLite 3.40.1, no systemd.

## Target unknowns

No VPS identity, OS, architecture, Python/SQLite patch level, cgroup/systemd
version, disk/inode budget, service user, provider reachability, existing
schedules, or backup destination was available. These remain preflight fields,
not guessed values. No real Bot, provider, or VPS call was made in this phase.

