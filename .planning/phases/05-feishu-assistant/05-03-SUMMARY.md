---
phase: 05-feishu-assistant
plan: 03
status: complete
completed: 2026-09-12
requirements: [FEIS-03, FEIS-05, FEIS-06, FEIS-07]
---

# 05-03 Summary

Added intelligence schema v4 with an event_id primary-key ledger and fenced owners,
bounded abandoned-claim retries, lease heartbeat, and persisted text replies before send.
Completed duplicates are suppressed after restart; failed provider delivery retries the
saved reply without another send-generation turn. Active duplicates receive a bounded
processing reply. Invalid scopes or unavailable/corrupt storage fail closed
without a second model call. Core session request idempotency is retained.

The single reconnect owner disables SDK auto-reconnect and applies capped backoff/jitter,
configured failure thresholds and cooldown. Only a stable connection resets the failure
streak. Task cancellation closes the connection and stops the loop.

Verification: 142 tests passed across storage, Feishu and core AI; changed-scope Ruff passed.
Tests cover restart, two connections, renewal, fencing, retry exhaustion, corrupt completed
events,
v3 migration, cooldown, stable reset, concurrent run rejection and cancellation.

Distributed limitation: a process crash after Gemini accepted a request but before any
reply was persisted is not exactly-once at the external provider. Lease recovery plus
core completed-turn lookup prevent duplicate completed work, not that unobservable
provider-side crash window. No commit or deployment.

Post-plan decision (2026-10-12): once a reply is confirmed delivered, a repeated
`event_id` must return locally as `already_delivered` and must not send the stored reply
again. This supersedes the earlier replay-to-provider behavior while preserving failed
delivery retry of a saved reply.
