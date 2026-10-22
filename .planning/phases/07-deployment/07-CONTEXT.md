# Phase 7 Context

## Scope

Phase 7 packages the Phase 1-6 implementation for a Linux VPS. The first
delivery is a reversible, offline-verifiable runtime split. It must preserve
the public `python -m trendradar.integrations.lark` entry point, schema v6,
`EventLedger`, legacy collectors, AI Frontier, MCP, reports, and notifications.

## Fixed decisions

- Lark uses the official WebSocket SDK; no public callback endpoint is added.
- `event_id` remains the inbound idempotency key. A completed duplicate is
  acknowledged locally and never sends or calls Gemini again.
- Bot persists authorized, normalized events; Worker claims and processes them;
  Scheduler performs one bounded daily-delivery tick and exits.
- `intelligence.db` is the shared explicit path on VPS. Legacy databases stay
  available for compatibility.
- Research remains opt-in and disabled by default.
- The old no-role command remains combined mode for local/UAT compatibility.
- No VPS deployment, Git commit, push, reset, clean, or runtime-data cleanup is
  part of offline implementation.

## Environment boundary

The repository is being changed on Windows. Isolated Ubuntu WSL systemd/UID,
full regression and dirty archive installation pass; see the 2026-10-22 final
report. Target systemd behavior, SQLite patch level, resource limits,
credentials, provider reachability and real tenant delivery remain unverified
until VPS preflight and authorization. Local passes do not close target gates.

