# TrendRadar Deployment Runbook

This runbook describes the Linux VPS reference layout. The repository changes
and offline tests do not prove that a VPS is installed, reachable, or stable.
Fill the host-specific values from `python scripts/deploy/preflight.py --json`
before enabling any service.

The active implementation plan is [07-06](../.planning/phases/07-deployment/07-06-PLAN.md).
It supersedes the older model, notification, resource and offsite requirements.
Use Python 3.12 on the VPS. This release uses instant Lark delivery and local
backups only; offsite recovery and 48-hour observation remain separate open gates.

Historical acceptance status and remaining external gates are in the
[actual-gap handoff](phase7-actual-gap-evidence/HANDOFF.md). The current worktree
is not an accepted production candidate. The guarded
`backup activate --deployment-rollback` API and Bash installer tests now pass,
and the historical real-systemd rollback failure has a confirmed permission
cause and passing final regression. Authorized local work is complete:
27 reviewed scenarios PASS; RG-04 clean candidate remains BLOCKED. G1 PASS;
G2 clean-candidate and G3 target gates remain open before production use.

## Layout and secrets

Use `/opt/trendradar/releases/<release-id>` for immutable code and its virtual
environment, `/opt/trendradar/current` for the selected release,
`/etc/trendradar` for non-secret YAML and role environment files, and
`/var/lib/trendradar` for runtime databases and reports. Keep restore guards
under `/var/lib/trendradar/control`, locks and heartbeats under
`/run/trendradar`, and local snapshots under
`/var/backups/trendradar`, and run the services as an unprivileged
`trendradar` user.

Copy the files in `deploy/config/` as templates. Put real `LARK_*`,
`GEMINI_API_KEY`, source credentials, and backup credentials into the relevant
systemd `EnvironmentFile`; never place them in YAML, a unit, a release archive,
health JSON, or logs. Set the same explicit
`INTELLIGENCE_DB_PATH=/var/lib/trendradar/output/intelligence.db` for Bot,
Worker, Scheduler, main collection, and AI Frontier.

Production templates set `INTELLIGENCE_REQUIRE_EXISTING=true` and
`INTELLIGENCE_SQLITE_SYNCHRONOUS=FULL`. Prepare both compatibility stores before
starting a role; role constructors only open an existing current-schema
`intelligence.db` and schema-v1 `ai_frontier.db` in this mode:

Run database preparation and snapshots as the service user with the same trusted
environment as the services. Restore preserves existing UID/GID/mode; new files
inherit the guarded database's metadata. Verify service-user access after
recovery rather than relying on a successful root-only integrity check.

```bash
python -m trendradar.ops database migrate \
  --database /var/lib/trendradar/output/intelligence.db --synchronous FULL
python -m trendradar.ops database check \
  --database /var/lib/trendradar/output/intelligence.db
python -m trendradar.ops database migrate \
  --database /var/lib/trendradar/output/ai_frontier.db \
  --kind ai_frontier --synchronous FULL
python -m trendradar.ops database check \
  --database /var/lib/trendradar/output/ai_frontier.db \
  --kind ai_frontier
```

## Preflight and installation

```bash
python scripts/deploy/preflight.py --json
systemd-analyze verify deploy/systemd/*.service deploy/systemd/*.timer
install -d -o trendradar -g trendradar /run/trendradar /var/lib/trendradar \
  /var/lib/trendradar/control
python -m trendradar.integrations.lark --role bot --check --config /etc/trendradar/config.yaml
python -m trendradar.integrations.lark --role worker --check --config /etc/trendradar/config.yaml
python -m trendradar.integrations.lark --role scheduler-once --check --config /etc/trendradar/config.yaml
```

Install the units only after checking their absolute interpreter and writable
paths. Enable `trendradar-bot.service`, `trendradar-worker.service`, the
Scheduler/collector timers, and the read-only health timer one at a time.
Stop old Actions, cron, Docker, or combined Bot schedules before enabling the
same production scope on VPS. The templates do not perform that cutover.

## Roles and operations

Bot owns the Lark WebSocket and durably records authorized events. Worker polls
the existing `EventLedger`, claims work, sends replies, and reuses
saved replies after failures. Scheduler runs one `DeliveryScheduler.tick()` and
exits. The no-role command remains combined mode for local compatibility.

Set `LARK_DELIVERY_MODE=instant` with the authorized target. The scheduler timer
checks every 60 seconds without changing collector frequency. At most 20 new
Stories are registered per batch; overflow remains eligible for subsequent ticks.
Delivery uses persisted payloads and chunk checkpoints. Do not run daily delivery
as a second sender. Configure the ordered `GEMINI_MODELS` list from `.env.example`;
translation always uses a separate fixed `gemma-4-31b-it` profile and the same key.

```bash
systemctl status trendradar-bot trendradar-worker
journalctl -u trendradar-bot -u trendradar-worker -n 200 --no-pager
python -m trendradar.ops health --config /etc/trendradar/config.yaml --json
systemctl restart trendradar-worker
```

`--check` is offline and does not create the database. Health is read-only and
returns exit code 0 for healthy/disabled, 1 for degraded, and 2 for unhealthy.
It must report a missing or incompatible database; it must not silently create
an empty one. The `collector` lock serializes main collection and AI Frontier.

## Release and rollback

Build and inspect one artifact before installation:

```bash
python scripts/deploy/build_release.py --output-dir dist --release-id RELEASE_ID
python scripts/deploy/create_manifest.py \
  --artifact dist/trendradar-RELEASE_ID.tar.gz \
  --output dist/RELEASE-MANIFEST.json --release-id RELEASE_ID
```

Install into a new release directory, run offline checks, and keep the old
`current` target. Before any schema or configuration change, stop all writers
and create a complete snapshot:

```bash
python -m trendradar.ops backup create \
  --root /var/lib/trendradar/output \
  --destination /var/backups/trendradar/local \
  --release-id RELEASE_ID
```

With `--root`, the backup includes `intelligence.db`, `ai_frontier.db`, and
all existing date-partitioned `output/news/*.db` and `output/rss/*.db` files.
Each database is copied through SQLite Online Backup API and validated before
the manifest becomes complete. If `TRENDRADAR_OFFSITE_ENABLED=true`, the
backup unit runs `scripts/deploy/offsite_backup.py` after the local snapshot;
configure `RESTIC_REPOSITORY` and `RESTIC_PASSWORD_FILE` in `backup.env`.

For this deployment set `TRENDRADAR_OFFSITE_ENABLED=false` in `common.env` and
`backup.env`. Readiness still requires a fresh local snapshot, but does not
require an offsite receipt. The hourly backup unit applies managed retention:
24 hourly, 7 daily and 4 weekly snapshots in Asia/Shanghai. Only snapshots
explicitly marked retention-managed are pruned; manual snapshots and historical
recovery evidence are preserved. Local backups do not protect against host loss.

The backup tool uses SQLite Online Backup API, validates each snapshot, and
writes a manifest only after every requested database succeeds. It does not
copy an active `.db`/WAL pair directly. Restore into a new directory first:

```bash
python -m trendradar.ops backup restore \
  --snapshot /var/backups/trendradar/local/BACKUP_ID \
  --destination /var/lib/trendradar-restore/BACKUP_ID \
  --guard-database /var/lib/trendradar/output/intelligence.db \
  --max-age-hours 26
```

Restore automatically creates a persistent guard after the snapshot has passed
checksum validation. It does not overwrite the live database. A complete
switch is an explicit, guarded operation and preserves the pre-restore copy:

```bash
python -m trendradar.ops backup activate \
  --restored /var/lib/trendradar-restore/BACKUP_ID \
  --database /var/lib/trendradar/output/intelligence.db \
  --root /var/lib/trendradar/output
```

Activation records a UTC recovery cutover. Events with a provider creation
time before that point, or with no provider creation time, remain as retained
evidence and are quarantined instead of invoking Gemini or sending a reply.
The same cutover blocks a not-yet-confirmed old delivery window. Clear the
maintenance guard only after review; clear the cutover separately when the
replay boundary is deliberately closed:

```bash
python -m trendradar.ops maintenance clear \
  --database /var/lib/trendradar/output/intelligence.db
python -m trendradar.ops maintenance clear \
  --database /var/lib/trendradar/output/intelligence.db \
  --clear-recovery-cutover
```

Inspect schema, stories, sessions, event states, delivery checkpoints and
configuration before accepting new work. A restore is guarded operational
work: do not mark uncertain external sends as pending automatically, and do
not reconnect the Bot until the duplicate/replay boundary is reviewed. The
guard is persistent and survives process/release restarts:

```bash
python -m trendradar.ops maintenance enter \
  --database /var/lib/trendradar/output/intelligence.db \
  --reason "restore verification"
python -m trendradar.ops maintenance status \
  --database /var/lib/trendradar/output/intelligence.db
# inspect and validate the isolated restore, then explicitly clear the guard
python -m trendradar.ops maintenance clear \
  --database /var/lib/trendradar/output/intelligence.db
```

While the guard exists, new Bot intake, Worker consumption, Scheduler sends,
and collection roles are blocked. Clear it only after the restored database,
authorization, target and uncertain-delivery window have been reviewed.

## Release and deployment workflow

`phase7-release.yml` builds the artifact and manifest; tag runs also publish a
GitHub Release. `phase7-deploy.yml` is a separate manual workflow with a
GitHub Environment approval gate. It packages the selected ref, verifies the
artifact SHA on the host, runs the explicit migration, keeps the old release,
and rolls the symlink back if service restart fails. Configure
`TRENDRADAR_DEPLOY_HOST`, `TRENDRADAR_DEPLOY_USER`,
`TRENDRADAR_DEPLOY_PATH`, and `TRENDRADAR_DEPLOY_SSH_KEY` as Environment
secrets. No deploy is implicit on push.

The target must pre-install the root-owned controlled entry
`/usr/local/sbin/trendradar-install-release`, backed by the reviewed
`/usr/local/libexec/trendradar/install_release.sh` and
`/usr/local/libexec/trendradar/load_environment.py`, before the workflow is
enabled. The workflow transfers only the release archive and manifest and
invokes that fixed entry through `sudo`; a release archive cannot replace the
installer used to change the host.

Provision all three reviewed files as root:

```bash
install -d -o root -g root -m 0755 /usr/local/libexec/trendradar
install -o root -g root -m 0750 deploy/bin/trendradar-install-release /usr/local/sbin/trendradar-install-release
install -o root -g root -m 0750 scripts/deploy/install_release.sh /usr/local/libexec/trendradar/install_release.sh
install -o root -g root -m 0644 scripts/deploy/load_environment.py /usr/local/libexec/trendradar/load_environment.py
```

The entry parses root-owned `/etc/trendradar/common.env` as data and sanitizes
the installer environment; caller exports are not the production configuration.
Its file and ancestors must not be writable by group/others. Use the template's
single-line assignments, absolute paths and `FULL` SQLite policy. Missing or
invalid configuration fails before deployment. The loader intentionally supports
a constrained subset of EnvironmentFile syntax, without shell expansion.

## Phase 7 remediation controls

The release artifact contains pyproject.toml, the complete trendradar and
mcp_server packages, deployment scripts and dependency declarations. The
installer creates the release virtual environment, installs
`build-requirements.lock` and the exact `requirements.lock` set, then installs
the application with `pip install --no-build-isolation --no-deps .`.
The build lock pins pip, Hatchling and its resolved build dependencies; the
backend is also pinned in `pyproject.toml`. The opt-in Linux empty-venv artifact
installation passed, including `pip check` and outside-checkout smoke, using a
dirty fixture. A clean candidate and privileged GitHub CI execution remain open.
Installation must not depend on the checkout remaining on
`PYTHONPATH`. Run
scripts/deploy/release_smoke.sh <release-venv-python> <release-root> from a
temporary working directory before accepting a Linux artifact.

scripts/deploy/install_release.sh records prepare, acquire, quiesce, snapshot,
migrate, switch, pre_resume, resume, verify and finalize in
/var/lib/trendradar/control. It takes a host lock, refuses an existing restore
guard or unfinished deployment transaction, snapshots all discovered databases,
explicitly migrates the unified and AI stores, and only starts units that were
active before the release or are supplied through TRENDRADAR_RESTART_UNITS /
TRENDRADAR_INITIAL_UNITS. A failure before the business boundary may restore
the complete pre-release snapshot. After resume, the installer retains
maintenance protection and reports manual rollback; a symlink change alone is
never reported as a successful recovery.

The deploy workflow tests and packages one immutable checkout, then deploys
that artifact without a second checkout. It requires the protected
TRENDRADAR_DEPLOY_KNOWN_HOSTS secret and strict host-key checking. The
installer writes /etc/trendradar/release.env, which every service reads so
heartbeats and health identify the active release.

Readiness requires an accepting state for every expected role (`connected` for
Bot, `running` for Worker), matching release identity and fresh timestamps.
Required source runs cannot be empty. Queue waiting age comes from durable
original reception time, not a lease/retry timestamp. Ordinary health and the
production readiness gate retain different disabled/maintenance semantics.

Offsite restic uploads have a bounded process-tree timeout and write only a
redacted receipt bound to the local backup ID, manifest digest, snapshot data
time and remote snapshot ID. Health uses data_age_seconds for RPO and
upload_age_seconds for transfer freshness. Use
python -m trendradar.ops health --readiness --json for the production gate;
ordinary health retains the legacy disabled/maintenance exit semantics.

Interrupted multi-database restore activation leaves a recovery journal under
the stable control directory. Inspect it with
python -m trendradar.ops backup recovery-status --database ...; do not retry
or clear the guard until the source, destination, retained WAL/SHM files and
installed set have been reviewed.

Ordinary `maintenance clear` refuses an unfinished restore or unauthorized
deployment, including malformed records. After inspecting the journal and
pre-restore mapping, the recovery command rolls the interrupted activation back
and retains maintenance protection. Recovery validates target paths, snapshot
mapping/checksums and recorded file metadata before replacement, removes targets
that were originally absent, and supports repeated rollback:

```bash
python -m trendradar.ops backup recover --database /var/lib/trendradar/output/intelligence.db
```

Do not manually remove transaction files to unblock work. A durably finalized
deployment can be confirmed with `maintenance finalize-deployment --database ...`
only for the matching release/current symlink and passing health checks;
`confirm-deployment-rollback` requires a persisted pre-business-boundary rollback.
These paths pass the reviewed local assertion matrix; clean-candidate and
production-target gates remain open. Database movements now fsync affected directories on
POSIX; journal directory-fsync error propagation and metadata failure paths
now have repair and focused fault-test evidence in the
[restore follow-up](phase7-actual-gap-evidence/restore-durability-20261014.json).
Nested runtime roots, malformed destinations/cutovers and repeated interrupted
rollback are covered there and in frozen v6 final regression. The
Bash installer suite previously passed 57 tests. Historical real-systemd RG-03
returned 9 passed/1 failed because service-UID rollback confirmation could not
read a root-owned 0600 restore guard. Automatic restore and activation now use
the service identity, and the rollback controller lease is renewed before
activation. Confirmation requires an explicit false business-boundary flag;
missing, null and numeric-false values fail closed. The repaired restart node
and expired-lease scenario pass focused regression. See the
[repair evidence](phase7-actual-gap-evidence/rg03-rollback-fix-20261014.json) for
exact scopes. Full v6 Linux regression includes all 11 current quiesce cases.
Abrupt-process tests
do not establish power-loss durability.

New installer records retain UTC `updated_at` for audit and use
`controller_lease_boottime_ns` for the 15-second controller lease. Linux
`CLOCK_BOOTTIME` includes suspension and is unaffected by wall-clock correction;
the boot ID, exact process start identity and permitted transaction stage still
have to match. Invalid, expired or future boottime values fail closed. Older
records without this field retain strict UTC-age validation. Do not edit either
timestamp or remove records to manufacture authorization.

## Limits and open evidence

`deploy/systemd/trendradar.slice` puts Bot, Worker, Scheduler, collectors,
health and backup in one cgroup with initial `MemoryHigh=512M`,
`MemoryMax=768M`, `CPUQuota=50%`, and `TasksMax=128`. Measure CPU, memory, tasks, file
descriptors, disk and inode peaks on the target and adjust through a reviewed
release. If these limits cannot support the measured workload, pause activation.
Do not automatically expand the budget or alter unrelated services. The `.example` file remains a reference for hosts that need different
limits. Keep release interpreters outside `/tmp` and `/var/tmp`: `PrivateTmp=yes`
can hide them from service execution. Research and Lark are disabled in the
example configuration. Isolated systemd backup-unit defaults/overrides and
service-UID checks pass. Isolated role/timer lifecycle also passes final v6
regression; target resource limits remain unmeasured. Phase 5 live gaps,
RG-04 clean candidate and
VPS/provider acceptance remain recorded in
`docs/phase7-acceptance.md`.
