---
gsd_state_version: 1.0
milestone: v5.0
milestone_name: milestone
status: in_progress
stopped_at: Phase 7 07-05 authorized local work complete; G1 PASS; G2 blocked by clean candidate; G3 target pending
last_updated: "2026-10-22T08:30:00Z"
last_activity: 2026-10-22 -- v6 Windows 683 passed/342 skipped; Linux 1019 passed/6 skipped; dirty install passed; matrix 27 PASS/1 BLOCKED
progress:
  total_phases: 9
  completed_phases: 7
  total_plans: 32
  completed_plans: 28
  percent: 88
---

# Project State

## Project Reference

See: `.planning/PROJECT.md` (status reconciled 2026-10-22)

**Core value:** 把多个来源关于同一事件的内容聚合成可解释、可排序、可追问的 Story，并通过飞书持续交付真正重要的个人情报。
**Current focus:** Phase 7 actual-gap remediation 07-05; resume from `docs/phase7-actual-gap-evidence/HANDOFF.md`. VPS acceptance and Phase 5 live gaps remain open; B6 non-whitelisted testing is an accepted skip, not a pass.

## Current Position

Phase: 7 (Deployment), in the Phase 0-8 roadmap
Plan: 07-01..04 delivered; 07-05 actual-gap remediation in progress (4 of 5)
Status: Authorized local work complete; H1-A..D and final 28-case audit complete; 27 PASS/1 BLOCKED (RG-04 clean candidate). G1 PASS; G2 BLOCKED; G3/VPS and GitHub evidence remain open
Last activity: 2026-10-22 -- v6 freezes 301 unchanged source/resource inputs; Windows 683 passed/342 skipped/2 warnings, Linux 1019 passed/6 skipped/2 warnings, actual dirty install 1 passed; all exit 0 and all sessions terminated

Progress: [#########-] 88% (28 of 32 roadmap plans; Phase 7 target deployment is not claimed)

## Performance Metrics

**Velocity:**

- Total plans completed: 28
- Average duration: Not available for Phase 1-4 plans
- Total recorded execution time: 13 min (Phase 0 recorded time)

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 0 | 2 | 13+ min | Not available |
| 1 | 4 | Not recorded | Not available |
| 2 | 4 | Not recorded | Not available |
| 3 | 3 | Not recorded | Not available |
| 4 | 4 | Not recorded | Not available |
| 5 | 4 | Not recorded | Not available |
| 6 | 3 | Not recorded | Not available |
| 7 | 5 | 4 delivered, actual-gap remediation open | VPS pending |

**Recent Trend:**

- Last 5 plans: 06-02, 06-03, 07-01, 07-02, 07-03/07-04
- Trend: Phase 7 actual-gap repairs and verification remain in progress; live Phase 5 gates and VPS acceptance remain open

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in `.planning/PROJECT.md`.

- v5.0 follows the documented Phase 0-8 structure; Phase 6 is implemented locally and remains uncommitted, while Phase 5 live gates stay open.
- Story is the core intelligence deliverable, not an optional enhancement.
- Existing behavior and SQLite data migrate incrementally through adapters.
- Feishu uses WebSocket long connection with a deny-by-default user whitelist.
- Agent-Reach is isolated behind ResearchGateway and never exposes general shell access.
- Runtime config path precedence is explicit argument, `CONFIG_PATH`, then `config/config.yaml`.
- Runtime value precedence is non-empty environment, YAML, then default; Gemini and Feishu secrets are environment-only.
- Unified ingestion is default-on but `INTELLIGENCE_ENABLED=false` restores legacy acquisition.
- `intelligence.db` is local-only, best effort, and never replaces legacy report/MCP authority.
- Cross-source deduplication requires equal canonical URLs; fuzzy title matching stays within one source.
- Historical migration is explicit, date-bounded, source-filterable, dry-run capable, chronological, and idempotent.
- Story wording enhancement is optional and may change only title and summary; Google API credentials remain external and untouched.
- Security sources are bounded CISA KEV, NVD CVE 2.0, and configurable RSS adapters; NVD credentials remain environment-only.
- Exact CVEs anchor domain-scoped Security Stories without changing global canonical URL identity; multi-CVE records cannot bridge unrelated vulnerabilities.
- Security collection, persistence, analysis, freshness, and additive reporting are independently failure-isolated and can be disabled with `INTELLIGENCE_SECURITY_ENABLED=false`.
- One core `GeminiClient` owns chat, summary, analysis, Story wording, digest, security narrative, and translation provider access; credentials remain environment-only.
- Assistant sessions use principal-scoped tables introduced in schema v3 and preserved in v5, UTC half-open retrieval, server-built citations, bounded history, and idempotent complete turns.
- Phase 4 tools were deny-by-default local Story/ContentItem reads; Phase 6 adds a separate opt-in ResearchGateway with no file, shell, crawler, arbitrary executable, or MCP dispatch capability.
- Phase 5 uses lark-oapi 1.7.3, configurable identity fields, private/mentioned-group scope, event_id deduplication, and bounded reconnect cooldown.
- Intelligence schema v4/v5 adds event and daily-delivery ledgers; all legacy schemas remain unchanged.
- Provider acceptance and a crash before local persistence cannot form an atomic exactly-once transaction; saved replies/confirmed windows are durable and tested.

### Pending Todos

- Local 07-05 work is complete: see `docs/phase7-actual-gap-evidence/verification-20261022.md` and final-run-v6. Matrix: 27 PASS/1 BLOCKED; G1 PASS, G2 blocked by clean candidate. No active test session. Next needs authorization for a committed candidate and real GitHub run; V-01..06 need target configuration/authorization. Preserve B6 accepted skip and C3/C4 live gaps. Do not repeat completed tests without relevant changes.
- RG-03 root-owned guard caused service confirmation PermissionError; restore/activate now use the service identity, renew leases and require explicit false boundary. Repaired real-systemd restart passed; combined rollback/confirmation passed 29 and restore/crash scope passed 43. CI wiring passed 18 local checks; no GitHub run is recorded. These scopes overlap, while historical installer/systemd/dirty-install results remain retained. Both agents are frozen and closed. Cleanup and current source inputs are recorded in `docs/phase7-actual-gap-evidence/workspace-cleanup-20261014-post-rollback.md`; earlier hashes/checkpoints are historical.
- Follow `docs/phase5-live-acceptance.md` and record results in `.planning/phases/05-feishu-assistant/05-LIVE-UAT.md`; implementation completion does not complete live acceptance.
- B1/B2, pure-image functionality and B4 mixed-post functionality have user-confirmed evidence. The earlier MIX answer remains evidence-insufficient, but the fresh BOTH-7284 post has correlated metadata: one event token across all six stages, inbound `post`, text length 33, one media item, 17,282 image bytes in Assistant and Gemini, Flash Lite `STOP`, non-degraded reply and `sent` delivery.
- The fresh B4 client reply at 2026-09-13 10:20:02 UTC correctly identified BOTH-7284, 91.35 units and yellow. At that point the ledger had 13 completed events, 1 session and 26 messages, with latest reply degraded=false. This is historical B4 evidence, not proof that the earlier MIX turn was mixed input.
- Historical live snapshot on 2026-10-11: the C4 delivery instance PID 25780 was verified and stopped after the delivery window; `test/runtime/lark-live.json` points to its stopped log and `c4-intelligence.db`. Recheck current processes before any new run; preserve database, WAL/SHM, fixtures and logs.
- B5 group text and isolation evidence: two real mentions at 12:47:47 and 12:48:13 UTC each made one Flash Lite call, STOP, degraded=false, sent. A private message then stored a short test secret, while a group @ question asking for it returned “不知道”. Read-only ledger snapshot after the isolation test: 19 completed events, 2 sessions, 38 messages; private and group sequence ranges remained separate. The secret is absent from logs and documentation. Second-user isolation was not separately run; the time query returned a retrieval interval, so it does not prove accurate current-time answering.
- C2 evidence: controlled Feishu recovery/reconnect/scheduler suite passed 22 tests with one existing warning. In the real sandbox, hidden PID 26012 exited with 19 completed events and no nonterminal work; same database/config restarted as PID 13264, connected, and processed a group @ message. The ledger is now 20 completed events, 2 sessions, 40 messages; latest event attempts=1, Flash Lite STOP, degraded=false, sent. This proves normal post-restart continuity; it does not prove foreground Ctrl+C shutdown or recovery of an interrupted in-flight event.
- C4/C6 evidence: an isolated `test/runtime/c4-intelligence.db` with two same-day Stories (Importance 88/42) delivered one real Asia/Shanghai digest to the UAT group during a 21:25-21:35 window. The delivery ledger is completed with one chunk. Restarting the same target/window/database left the ledger unchanged and created no second delivery row. The dedicated process was then stopped. Lark-off and Intelligence-off checks exited 0 without network/storage access; baseline/schema compatibility suite passed 21 tests with one existing warning. User confirmation of actual receipt is still pending for final C4 status.
- Latest executed offline baseline on 2026-10-13: `python -B -m pytest tests -q -p no:cacheprovider` passed 531 tests with 1 existing warning; Phase 7 deployment focus passed 23 tests, Feishu compatibility passed 78 tests with the same warning, role boundaries passed 5 tests, scoped Ruff, compileall, Bash syntax and `git diff --check` passed. The source artifact boundary audit passed for 2037 members and its manifest SHA. No provider, GitHub release, restic repository, or VPS call was made.
- Phase 7 follow-up closed the remaining AI Frontier SQLite gap: its compatibility database now uses the configured synchronous policy, schema-v1 explicit migrate/check commands, and strict production opening when `INTELLIGENCE_REQUIRE_EXISTING=true`. Restore activation now has multi-database coverage, and the default control directory follows `/var/lib/trendradar/control` for the reference layout.
- The 2026-10-12 repair audit added durable in-process ledger polling, bounded pending work, delivery backoff, explicit research-only GitHub token injection, stricter MCP envelope parsing, and a verified Pydantic range. Details and the R1-R6 evidence boundary are in `docs/phase1-6-fix-audit.md`.
- Follow-up repair coverage added versioned/validated durable Lark payloads, terminal payload cleanup, exhausted-task filtering, delivery lease heartbeats, saved-reply delivery retry, stable reply UUIDs, provider error classification, startup recovery ordering, worker failure propagation, dependency-manifest parity checks, and bounded MCP envelope validation. Completed duplicate event IDs are now suppressed without another send; these are offline regressions, while Linux, Lark timeout-unknown windows, and provider acceptance remain unverified.
- Controlled C1/C5 and the controlled portions of C2/C3/C6 were exercised on 2026-10-11: 22 passed, 1 existing warning, using temporary databases and simulated provider/clock. Matrix details are in `05-LIVE-UAT.md`; do not treat these as live tenant proof.
- Remaining live gates are the non-whitelisted branch of B6, C3 real network interruption, C4 recipient confirmation, and same-`event_id` retransmission if available to confirm suppression. On 2026-10-11 the authorized user sent a group message without mentioning the bot; diagnostics recorded `ignored`, while the ledger remained at 19 completed events, 2 sessions and 38 messages. The user explicitly skipped the non-whitelisted branch, so B6 remains incomplete and is not marked passed. C4 used a separate current-day database and did not rewrite the original historical fixture.
- The user subsequently authorized Phase 6/7 work while remaining Phase 5 live gaps stayed recorded. Commit, push and production deployment remain outside the current task.
- Phase 7 local WSL systemd/UID/restore and dirty packaging now pass frozen full regression. Target systemd behavior, SQLite patch level, resource budget, provider reachability, remote backup, operator restore drill and continuous operation remain unverified. DEPL-01..05 stay open.

### Blockers/Concerns

The earlier `gemini-3.8-flash` free-tier daily request limit is bypassed for this test by the user-requested switch to `gemini-3.5-flash-lite`; the key is unchanged. Flash Lite live probes, correlated B4 success, and the real disabled-provider comparison passed, but full Phase 5 acceptance remains incomplete. Preserve unrelated working-tree changes during all GSD operations.

ENV-03 was fixed on 2026-10-14; its 48-test follow-up and later 466/6 deployment-only run remain historical. On 2026-10-22 H1-A..D and frozen v6 full Windows/Linux regression completed. All 301 source/resource hashes and archive members match. RG-03 history and failure directories remain retained; clean candidate, GitHub execution and VPS gates remain open.

2026-10-14 cleanup reconfirmed 19 ignored Python cache directories and `.ruff_cache/` outside protected state; no root `.pytest_cache/` exists. Prior recursive deletion was rejected by automatic approval review (`blocked by policy`); no deletion was retried or bypassed. Runtime evidence, `test/runtime/`, `output/`, `dist/` audit artifacts and all isolated Linux toolchains were preserved.

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Future | Semantic vector search and personal knowledge graph | Deferred until measured need | Initialization |

## Session Continuity

Last session: 2026-10-22
Stopped at: Authorized local work complete, G1 PASS. No active pytest session. G2 requires clean candidate; GitHub and G3/V-01..06 require external authorization/evidence. Read current HANDOFF; do not poll old handles or repeat tests without changes. B6 skip remains an exception; C3/C4 remain open.
Resume file: docs/phase7-actual-gap-evidence/HANDOFF.md
