# Deferred Lark Reply and Tool Repair

Status: **ported and repaired locally after the owner's PR 8 repair instruction;
not committed or deployed**. Updated 2026-10-24. See the
[current repair record](PR8-REPAIR-20261024.md) for target-tree validation and remaining gates.
The earlier preservation-only decision is historical. The retained
[deferred-lark-repair.patch](deferred-lark-repair.patch) remains unchanged as provenance.

## Provenance and Target

The reference diff was regenerated from the old task's retained `before/` copies
and its current source, including the G2/G3 review follow-up. It contains seven
changed files and five added source/test files, not credentials, logs or databases.
It is **not** a diff against current `28e7283` and must not be applied wholesale.
Its before/after labels refer to the old dirty task baseline, whose Git HEAD was
`5a427aba5ded0c9c9c9e050413dcb41f17fa0e23`; HEAD alone cannot recreate that baseline.

| Paths | Intended behavior |
| --- | --- |
| `trendradar/ai/{tools,assistant,models}.py` | Joint time-range contract, safe error taxonomy, evidence-backed recovery, separate untrusted quote input. |
| `trendradar/integrations/feishu/{client,handler,models}.py` | Durable direct-parent pointer, authorized same-chat lookup, backward-compatible event payload. |
| `trendradar/integrations/feishu/reply_context.py` | Bounded text/post parsing; no parent-media download or history traversal. |
| `tests/integrations/feishu/test_client.py` | SDK response/error and identity verification. |
| `tests/ai/{test_quoted_context,test_tool_recovery}.py` | Validation, retry budget, grounded recovery and combined input bounds. |
| `tests/integrations/feishu/{test_quoted_replies,test_reply_context}.py` | Quote parsing, authorization, injection resistance, saved-reply recovery. |

## Confirmed Local Defects and Contract

The old schema allowed a single `start` or `end`, but its handler required both.
`ToolValidationError` inherited `ToolDeniedError`, turning invalid dates into
`handler_denied`; reversed bounds instead became `handler_failed`. These were
reproduced locally. The historical live event's unique trigger remains unknown.

The proposed schema exposes optional `time_range` with required `start` and `end`.
Accept a legacy top-level pair, reject mixed or single endpoints, require explicit
timezone offsets, normalize to UTC, and enforce start < end, range <= 3650 days,
timestamp <= 80 characters and result limit <= 20. Omission uses the server range.
Return `invalid_arguments` separately from denial, disabled/unavailable tools,
unknown tools and execution errors. Log fixed tool/error/argument-shape codes,
not queries, IDs, arguments or raw exceptions.

Keep the existing three-call budget. Permit at most one correction for the same
tool/query/domain, preserving valid original bounds. Only visible results backed
by server citations can resolve a prior argument failure. Complete empty searches
are ordinary no-match outcomes, but cannot clear an earlier failure; truncated,
malformed or inconsistent empty results are not complete. Preserve failed audit
entries and show unresolved `Degraded` notices. Never loosen citation validation.

## Quote Safety and Current Architecture

Keep intake authorization and a genuine bot mention before current-content parsing.
Persist only the direct `parent_id` pointer in the v1 payload; old payloads without
it remain readable. Worker reauthorization, maintenance checks, claim and lease
must precede the single GetMessage operation. Validate the returned message ID and
chat ID. Never follow `root_id`, ancestors, arbitrary supplied IDs or group history.

Keep the current question separate from untrusted quoted text. Quotes cannot
authorize tools, override instructions or establish verified Story citations.
Give the current question priority within `max_input_chars`; quote allowance is
at most 4000 characters. No allowance means no lookup. Preserve visible HTTP(S)
links as text without fetching their pages. Disclose unavailable/truncated quotes
and omitted images; continue to support current-message images. If the Assistant
is unavailable, return before lookup/download. Retry saved replies without new
lookup/model execution, and suppress completed events.

The local port preserves the current multi-model tool loop, Bot/Worker roles,
instant Story posts, maintenance/restore guards and durable delivery. Additional
regressions cover quote preservation during model failover and complete structured
input under provider limits. The parser's hard cap is now 4000 characters, matching
the core DTO. Neither `ledger.py` nor the role runner changes. No schema migration
is required; mixed-version Workers are not valid quote-acceptance targets.

## Evidence and Real Acceptance

The old report records 408 focused tests passing in WSL2 Python 3.10.22, plus
historical native Windows results. Those are **historical old-tree evidence**;
the PR 8 baseline's 1212-test full run does not include the deferred tests. The current
port first reproduced 220 failures / 26 passes on the baseline, then added current
model-routing regressions. See the current repair record for new validation. Do not count
the old provider-quota-blocked subagent review as a successful review.

After a separately authorized exact-build test rollout, identify the sole Bot and
Worker and inspect approved GetMessage permissions. The old runbook references
`im:message:readonly` or `im:message`; recheck official Lark documentation and tenant
approval at that time. Do not request full-history access to implement direct reply.

1. Reply directly to `Quote A: QUOTE-A-6427, budget 37 units`, using a real bot @,
   and ask for both values. Verify one same-chat parent lookup.
2. Use another parent with distinct values and a public link; then reply to an
   intermediate reply. Verify direct-parent selection and no claimed page fetch.
3. Omit the real @, ask an ordinary non-reply question, and quote unsupported or
   unavailable content. Verify zero unauthorized lookup and explicit limitations.
4. Repeat the original search need. Check safe tool failure/recovery evidence,
   rather than treating absence of `Degraded` as proof.
5. In an authorized idle window, exercise Worker recovery with the same database;
   saved replies must not regenerate and completed events must not resend.

Preserve the accepted B6 skip, current database/WAL/SHM and saved messages. Real
tenant permissions, current model behavior and Phase 7 acceptance remain open.
