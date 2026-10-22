# Phase 7 Research Notes

## Verified locally

- Public Lark entry: `python -m trendradar.integrations.lark`.
- Implementation: `trendradar.integrations.feishu`.
- `EventLedger` and `DeliveryScheduler` use schema v6 in the shared
  `IntelligenceStorage` database.
- The current runner starts WebSocket transport, Worker, and Scheduler in one
  process and uses an in-memory queue as an optimization.
- Main collection and AI Frontier already have independent Python entry
  points and can receive an explicit config path/environment.
- Phase 6 offline checks and the existing full test baseline are historical
  evidence; they do not prove Linux or VPS behavior.

## Open preflight facts

Record these on the target before claiming deployment readiness: host/OS/
architecture, Python and SQLite versions, systemd/cgroup support, service and
deployment users, disk/inodes, clock sync, outbound DNS/TLS/WSS, existing
cron/Docker/Actions schedules, backup destination, and the actual production
configuration. Never fill these with development-machine guesses.

## Design consequence

The first implementation adds role dispatch and durable polling without a
second inbox/outbox schema. Cross-process correctness comes from SQLite claims
and OS file locks; the in-process queue remains only in combined mode.

