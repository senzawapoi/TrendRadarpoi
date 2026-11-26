# systemd templates

These units are deployment templates for the reference Linux layout. They are
not proof that a target host has been installed or that its resource limits
are correct.

Before installation, replace the release symlink and verify the target
interpreter, user, writable paths, environment files, SQLite version, and
existing schedules. Keep only one production scheduler for each collection
and notification scope. Validate syntax with `systemd-analyze verify` on a
Linux host, then run the role `--check` commands before enabling services.

`overrides/` holds project-owned drop-ins; copy each to the matching
`/etc/systemd/system/<unit>.d/` path, run `systemctl daemon-reload`, restart the
timer, and confirm `systemctl show <timer> --property=TimersMonotonic` lists the
expected triggers with a finite `NextElapseUSecMonotonic`. An empty
`OnUnitActiveSec=` resets every base timer expression, including `OnBootSec=`;
without `OnActiveSec=` the timer stays `active (elapsed)` with no next trigger
after a boot or fresh unit load. Review any other local drop-in for that pattern.

The health unit opens databases with `mode=ro`, but it may write the database
directory: SQLite removes `-wal`/`-shm` when the last writer closes, and a reader
must then create `-shm`. Without that path, `ai_frontier.db` fails with
`database_read_failed:OperationalError`. Keep the control directory read-only.
Exit code 1 is a degraded snapshot, not a crash, so `SuccessExitStatus=1` keeps it
out of `systemctl --failed`; unhealthy (exit 2) still marks the unit failed.

The Bot and Worker share the same explicit `INTELLIGENCE_DB_PATH`. All service
units join `trendradar.slice`; review its initial resource limits against the
target VPS before enabling them. Bot and Worker set `MemoryLow=200M` so reclaim
under the slice's `MemoryHigh` takes collector page cache before swapping out the
interactive roles; the contract test keeps at least 100 MiB unprotected. Bot owns the
WebSocket; Worker polls the durable EventLedger; Scheduler is a one-shot timer.
`TRENDRADAR_LOCK_DIR` points at `/run/trendradar`, and
`TRENDRADAR_CONTROL_DIR` points at `/var/lib/trendradar/control`; both must be
created for the service user before start. `PrivateTmp` therefore does not hide
the role locks or restore guard.

Install the root-owned controlled deployment entry before using the GitHub
workflow: copy `deploy/bin/trendradar-install-release` to
`/usr/local/sbin/trendradar-install-release` with mode `0750`, and install the
trusted `scripts/deploy/install_release.sh` at
`/usr/local/libexec/trendradar/install_release.sh` with mode `0750`, plus
`scripts/deploy/load_environment.py` at
`/usr/local/libexec/trendradar/load_environment.py` with mode `0644`. All three
files must be root-owned. The loader reads trusted `/etc/trendradar/common.env`;
caller exports cannot replace it. Keep interpreters outside the private
`/tmp` and `/var/tmp` namespaces. The
workflow uploads only the archive and manifest; it never uploads or executes a
release-provided installer through `sudo`.

## 本地候选的等待开关

`deploy/config/collector.env.example` 中 `TRENDRADAR_COLLECTOR_WAIT_SECONDS=0` 保持关闭；
有限范围为 0..1800，正值锁等待超时非零。默认 AI 遇忙退出 0 仍表示跳过。
helper 不提供 FIFO、持久待办或吞吐保证，D5 BLOCKED 时不得激活生产等待。
共享 512M/768M/50% CPU 与 `PrivateTmp` 保持原值；内存 `may_trial=false`。
验证范围与未闭合门槛见[资源修复验证](../../docs/evidence/resource-remediation-20261111/verification.md)。

## 分域采集范围与独立安全情报定时器

- `trendradar-collect-main.service` 内置默认 `Environment=TRENDRADAR_MAIN_SCOPE=general`（可由 `collector.env` 覆盖），每小时仅抓取热榜与 RSS 并在同一轮内合流为单次 `general` Story 聚类。
- 独立受管单元 `trendradar-collect-security.{service,timer}`（`01/4:45:00`）每 4 小时以 `--scope security` 运行慢速安全源，配合 `common.env` 中 `INTELLIGENCE_HEALTH_SECURITY_SOURCE_MAX_AGE_HOURS=8` 对齐源新鲜度门禁。
