# Phase 5: Feishu Assistant - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in `05-CONTEXT.md`; this log preserves the alternatives considered.

**Date:** 2026-09-12
**Phase:** 05-feishu-assistant
**Areas discussed:** identity and chat scope, message and media handling, event idempotency and connection recovery, daily Story delivery

---

## Identity and Chat Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Configurable identity fields | Match configured Feishu identity fields and values, deny by default | Yes |
| Hard-coded single identifier type | Bind the implementation to one Feishu ID format | No |

**User's choice:** Use configurable identity fields; support private chats and group chats.
**Notes:** Group messages are allowed when the bot is mentioned.

## Message and Media Handling

| Option | Description | Selected |
|--------|-------------|----------|
| Text and image capable input | Preserve the user's text/image capability through the Assistant boundary | Yes |
| Text-only transport | Reject or discard image input at the transport boundary | No |

**User's choice:** Gemini credentials support text and image processing; image handling is acceptable.
**Notes:** The adapter must still keep unsupported event types bounded and non-fatal.

## Event Idempotency and Connection Recovery

| Option | Description | Selected |
|--------|-------------|----------|
| `event_id` ledger with deduplication | Use compact event IDs and suppress completed duplicates | Yes |
| In-memory event cache | Lower storage cost but loses idempotency after restart | No |

**Earlier user choice (superseded 2026-10-12):** Deduplicate by `event_id`; duplicates must receive a reply; enter cooldown after a configured connection threshold.
**Notes:** Threshold and cooldown remain configurable implementation details.

**Decision amendment (2026-10-12):** The completed-delivery rule supersedes the earlier
reply requirement. After a reply for an `event_id` is confirmed delivered, a repeated
event is acknowledged locally as `already_delivered` without another Lark send or
Assistant/Gemini call. Saved replies remain retryable only while the original delivery
is failed or incomplete.

## Daily Story Delivery

| Option | Description | Selected |
|--------|-------------|----------|
| Existing repository baseline | Reuse current report, notification, schedule, and timezone defaults first | Yes |
| New delivery design now | Rework report presentation and prioritization in Phase 5 | No |

**User's choice:** Start with the original repository behavior and refine later.
**Notes:** Delivery remains `Asia/Shanghai` and must be restart-safe and idempotent.

## The Agent's Discretion

- Concrete identity mapping schema and default operational bounds.
- Feishu SDK event adapter decomposition and media DTO details.
- Additive SQLite event/delivery ledger location, preserving existing schemas.

## Deferred Ideas

- Daily report polishing.
- Agent-Reach integration and external research.
- VPS deployment and systemd operations.
