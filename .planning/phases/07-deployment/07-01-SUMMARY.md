# 07-01 Summary

Implemented the runtime split while preserving the combined entry point:

- `--role bot` owns Lark WebSocket intake and persists authorized events before
  returning to the SDK.
- `--role worker` polls schema-v6 `EventLedger`, claims durable work, and does
  not initialize WebSocket transport or Scheduler.
- `--role scheduler-once` runs exactly one existing delivery tick without
  Assistant/Gemini chat initialization.
- OS file locks protect bot, worker, scheduler and shared collector scopes.
- Main collection and AI Frontier share the `collector` lock.
- systemd service/timer templates use explicit paths and `/run/trendradar`.

Evidence: role/runner tests passed; full test run passed 521 tests with one
existing warning. Linux systemd syntax and lifecycle remain unverified on the
Windows development host.

