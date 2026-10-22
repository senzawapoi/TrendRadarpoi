# Phase 5: Feishu Assistant - Research

**Researched:** 2026-09-12  
**Domain:** Feishu WebSocket transport, Assistant routing, durable idempotency, Story delivery  
**Confidence:** MEDIUM

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Allowed identities are configured through identity fields rather than a hard-coded Feishu identifier type. The configuration must be able to express the field name and accepted values, with deny-by-default behavior when no identity matches.
- **D-02:** Both private chats and group chats are supported. In a group, a message must mention the bot before it can enter the Assistant path.
- **D-03:** The transport must pass a stable, sanitized principal and chat/session scope into the existing Assistant session model. Group context must not accidentally merge unrelated users or conversations.
- **D-04:** Text messages are supported immediately. The configured Gemini capability may also receive image content, so the adapter must preserve text-plus-image and image-only message intent instead of rejecting images at the transport boundary.
- **D-05:** The implementation should preserve the existing Assistant and Gemini failure behavior: bounded deterministic replies remain available when provider processing fails.
- **D-06:** Unsupported Feishu event types must not invoke Assistant tools or Gemini and should be handled as a bounded, non-fatal transport outcome.
- **D-07:** `event_id` is the primary deduplication key because it is compact and supplied by Feishu. A completed duplicate is suppressed without another Lark send or Assistant/Gemini turn; a failed provider delivery may retry the previously generated response.
- **D-08:** Event processing must survive process restarts through the existing local SQLite operational boundary or an additive table in it; an in-memory-only cache is insufficient for the required restart behavior.
- **D-09:** WebSocket reconnection is bounded. After the configured number of connection attempts or failures is reached, the client enters a cooldown period before attempting again. The threshold and cooldown are configuration values, with sensible repository defaults.
- **D-10:** Daily Feishu delivery initially follows the repository's existing report, notification, and scheduling defaults. New delivery-specific polishing is deferred until the baseline path is working.
- **D-11:** Delivery uses `Asia/Shanghai` and must be idempotent across restarts, so a successful daily delivery cannot be sent repeatedly for the same configured delivery window.

### The Agent's Discretion

- Exact Feishu SDK module and event callback decomposition, provided the official SDK WebSocket path and `integrations/feishu/` separation are preserved.
- The concrete identity mapping schema, default reconnect threshold/cooldown, and bounded retry backoff, provided they are configurable and tested.
- Whether the Feishu event ledger is an additive `intelligence.db` table or a narrowly scoped companion table, provided it does not alter existing legacy schemas or Assistant contracts.
- The exact media fetch/normalization DTO needed to pass image input through the existing Gemini boundary without leaking SDK types.

### Deferred Ideas (OUT OF SCOPE)

- Daily report presentation and prioritization refinements beyond the existing repository baseline.
- Agent-Reach and external research tools remain Phase 6.
- VPS/systemd deployment and long-running service operations remain Phase 7.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FEIS-01 | Separate Feishu client, handler, session responsibilities | `integrations/feishu/` adapter boundary below |
| FEIS-02 | Official SDK WebSocket long connection | SDK verification gate and client pattern |
| FEIS-03 | Allowed users receive Assistant replies | deny-by-default routing and existing Assistant contract |
| FEIS-04 | Daily Story delivery in configured Asia/Shanghai window | existing Story/report/notification defaults and delivery ledger |
| FEIS-05 | Unauthorized users cannot invoke Gemini/tools | authorize before parsing/dispatch |
| FEIS-06 | Duplicate/restarted events do not duplicate turns/replies | durable `event_id` ledger plus Assistant request idempotency |
| FEIS-07 | Reconnect is bounded and cooled down | explicit state machine and config |
</phase_requirements>

## Summary

The repository already provides the important inward contracts. `AssistantService` accepts provider-neutral `AssistantRequest` values, scopes sessions by principal, and makes a turn idempotent by `request_id`; `AssistantSessionStore` stores complete turns in SQLite. Feishu should therefore remain an adapter under `integrations/feishu/`, with SDK objects ending at the transport boundary. `[VERIFIED: codebase grep]` `[HIGH]`

The main missing durability is transport-level deduplication by Feishu `event_id`, because one Feishu event may be retried before or after the Assistant turn. Add an additive ledger in the existing intelligence database using a transaction and unique event key. Persist normalized response data before acknowledging successful processing; on a duplicate, return the persisted response without calling Assistant. If a prior event is marked processing but has no response, reclaim it with a lease or retry policy. `[VERIFIED: codebase grep]` `[HIGH]`

The official Python SDK package is `lark-oapi`; it is not installed in the current environment, so implementation tests must inject or mock the SDK boundary. The official repository's current WebSocket sample uses `lark.ws.Client(app_id, app_secret, event_handler=...)`, an `EventDispatcherHandler` registered for `p2_im_message_receive_v1`, and `client.im.v1.message.reply` for replies. Exact installed-version signatures still need to be pinned and checked during implementation. `[VERIFIED: official SDK repository]` `[MEDIUM]`

**Primary recommendation:** implement a thin, provider-neutral Feishu adapter with an explicit event ledger, authorize before Assistant dispatch, preserve text/image intent in a local DTO, and use a small reconnect state machine with cooldown.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Feishu WebSocket connection | Frontend Server | — | Long-lived transport owns SDK lifecycle and reconnect state. |
| Identity and chat routing | Frontend Server | API / Backend | Transport knows event/chat/mention fields; Assistant owns principal-scoped sessions. |
| Assistant turn and tools | API / Backend | Database / Storage | Existing AssistantService owns retrieval, tools, Gemini, fallback, and session contract. |
| Event/daily idempotency | Database / Storage | Frontend Server | Restart safety requires transactional durable state. |
| Story daily content | API / Backend | Frontend Server | Reuse existing Story report/notification rendering, then send through Feishu. |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `lark-oapi` | Pin after implementation-time verification | Official Python Feishu/Lark SDK for WebSocket event delivery and IM replies | Official repository and samples confirm the package and current API shape; package is not installed locally yet. `[VERIFIED: official SDK repository]` |
| Existing `sqlite3` / `IntelligenceStorage` | Repository version | Durable event and daily-delivery ledger | Existing WAL, migration, transaction, and failure-isolation patterns. `[VERIFIED: codebase grep]` |
| Existing `pytz` time helpers | Repository version | `Asia/Shanghai` daily window calculations | Existing repository default and time utilities. `[VERIFIED: codebase grep]` |

### Supporting

Use the existing notification renderer/sender path where its content contract matches Story reports. Do not add a webhook dependency: the phase transport is WebSocket inbound plus SDK send API. `[VERIFIED: codebase grep]`

**Installation:** add the pinned `lark-oapi` dependency only after checking the supported Python/runtime version and the exact release API used by the implementation.

**Required verification:** check official Feishu Open Platform Python SDK docs, package registry metadata, supported long-connection API, event envelope types, message send API, and image resource API before locking versions.

## Architecture Patterns

### Event Flow

```text
Feishu WebSocket -> SDK envelope -> normalize event
                                  -> event_id ledger claim
                                  -> authorize identity + private/group mention
                                  -> text/image DTO
                                  -> AssistantRequest(principal, session, event_id)
                                  -> AssistantService -> bounded reply
                                  -> persist response atomically -> Feishu reply
                                  -> mark delivered
```

### Component Responsibilities

| Component | Owns | Must not own |
|-----------|------|--------------|
| `client` | SDK construction, WebSocket lifecycle, send/reply calls | identity policy or Assistant logic |
| `handler` | event normalization, authorization, routing, event ledger orchestration | raw SDK types leaking inward |
| `session` | stable principal/chat scope and request mapping | a second conversation store |
| delivery worker | daily window, Story rendering reuse, delivery ledger | chat command handling |

### Routing Pattern

Authorize before parsing message content beyond the minimum identity/chat metadata. Private messages route when the configured identity field matches. Group messages route only when the bot mention is present. Rejected and unsupported events must return a bounded transport outcome and must not construct an Assistant/Gemini turn. `[CITED: https://open.feishu.cn/document/server-docs/event-subscription/event-subscription-guide]` `[MEDIUM; URL requires implementation-time confirmation]`

Use a sanitized principal such as `feishu:<configured-field>:<stable-value>` and a session scope containing the chat identity plus principal. Never use display names, raw message text, or an entire group as the principal. `[ASSUMED]` `[MEDIUM]`

### Idempotency Pattern

Use a unique `event_id` ledger with states such as `processing`, `completed`, and `failed`, timestamps, normalized response payload, and a lease/attempt field. Claim in a transaction. A completed duplicate returns a suppression result without sending; a failed delivery record is retried only after its bounded lease/backoff. The Assistant `request_id` should equal a deterministic event-derived value, while the Feishu ledger remains authoritative for delivery retry and duplicate suppression. `[VERIFIED: codebase grep]` for existing Assistant idempotency; `[ASSUMED]` for ledger schema.

Daily delivery needs a unique key `(delivery_name, local_date, configured_window)` or equivalent. Mark success only after the SDK send operation succeeds; repeated scheduler starts then observe the completed key and skip. Compute the local date/window in `Asia/Shanghai`, store timestamps in UTC, and test the midnight/DST-independent boundary explicitly. `[VERIFIED: codebase grep]` for timezone conventions; `[ASSUMED]` for new key shape.

### Reconnect State Machine

Use `connected -> disconnected -> retrying -> cooldown -> retrying`, with a configured maximum consecutive failures/attempts and cooldown seconds. Reset the consecutive failure count only after a stable successful connection or configured healthy interval. Bound exponential backoff with jitter and do not create multiple concurrent connection loops. Defaults must be conservative for the repository's one-CPU VPS; exact values are implementation decisions and need tests. `[ASSUMED]` `[LOW]`

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Feishu authentication/WebSocket protocol | Raw WebSocket protocol and signature handling | Official SDK long-connection API after verification | Protocol and envelope details are vendor-owned. |
| Conversation persistence | Feishu-side or in-memory history | Existing `AssistantSessionStore` and `IntelligenceStorage` | Preserves Phase 4 limits and rollback behavior. |
| Event duplicate protection | Process-local set/cache | SQLite unique ledger and transaction | Required across restart and duplicate delivery. |
| Story formatting | New Feishu-specific report model | Existing Story report/notification renderer | D-10 requires repository baseline first. |

## Common Pitfalls

1. **Wrong SDK contract:** the official package/API may evolve. Verify the pinned installed package and callback names before implementation. `[MEDIUM]`
2. **Deduping only after Assistant:** retries can cause duplicate Gemini calls. Claim `event_id` before dispatch and persist the reply before acknowledging.
3. **Using `message_id` as the primary key:** requirements explicitly make `event_id` authoritative; retain message/chat IDs as diagnostics only.
4. **Group leakage:** a group chat must include bot mention and session scope must include chat plus principal.
5. **Unauthorized side effects:** deny before Assistant construction/tool dispatch; avoid logging raw content or credentials.
6. **Image rejection at transport:** preserve image-only and text-plus-image intent in an SDK-free DTO; verify the existing Gemini boundary can carry the chosen media representation.
7. **Marking delivery before send:** a crash after marking but before send loses the report; mark success only after a confirmed send result.
8. **Infinite reconnect storm:** cap consecutive failures and enter cooldown; ensure only one reconnect owner exists.
9. **Changing legacy schemas:** use an additive migration in the intelligence database and test existing tables/rollback behavior.

## Code Examples

Provider-neutral shape for planning (not an SDK API):

```python
@dataclass(frozen=True, slots=True)
class FeishuInbound:
    event_id: str
    principal_id: str
    chat_scope: str
    text: str | None
    images: tuple[bytes, ...]
```

```python
request = AssistantRequest(
    principal_id=inbound.principal_id,
    session_id=f"feishu:{inbound.chat_scope}:{inbound.principal_id}",
    request_id=f"feishu-event:{inbound.event_id}",
    text=inbound.text or "",
)
```

The exact `AssistantRequest` field names and media extension must follow `trendradar/ai/models.py`; do not pass SDK event objects into it. `[VERIFIED: codebase grep]`

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (repository test suite) |
| Config file | `pyproject.toml` |
| Quick run command | `python -m pytest tests/ai tests/intelligence -q` |
| Full suite command | `python -m pytest tests -q` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FEIS-01 | client/handler/session boundaries | unit | `python -m pytest tests/integrations/feishu/test_boundaries.py -q` | No, Wave 0 |
| FEIS-02 | SDK WebSocket wiring with mocked SDK | integration | `python -m pytest tests/integrations/feishu/test_client.py -q` | No, Wave 0 |
| FEIS-03/05 | private/group mention and deny-by-default | unit | `python -m pytest tests/integrations/feishu/test_handler.py -q` | No, Wave 0 |
| FEIS-04 | local-day delivery once in Asia/Shanghai | unit/integration | `python -m pytest tests/integrations/feishu/test_delivery.py -q` | No, Wave 0 |
| FEIS-06 | duplicate, restart, crash and delivery-retry behavior | integration | `python -m pytest tests/integrations/feishu/test_idempotency.py -q` | No, Wave 0 |
| FEIS-07 | threshold, cooldown, bounded backoff | unit | `python -m pytest tests/integrations/feishu/test_reconnect.py -q` | No, Wave 0 |

Required scenarios include unauthorized requests making zero Assistant/provider calls, completed duplicate events causing no second send or model call, image-only and text-plus-image normalization, group mention filtering, process restart using `tmp_path` SQLite, failed send retrying the saved response without a new model call, and reconnect cooldown preventing a tight loop. Mock SDK/network/provider/time; preserve existing Phase 4 and legacy tests.

## Security Domain

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | SDK app credentials from environment only; verify event identity fields |
| V3 Session Management | yes | principal plus chat-scoped Assistant session; bounded TTL/history |
| V4 Access Control | yes | deny-by-default allowlist and group mention gate before dispatch |
| V5 Input Validation | yes | validate event type, identity field, text/media sizes, and configured limits |
| V6 Cryptography | yes | rely on official SDK/signature handling; do not implement protocol crypto |

## Project Constraints (from AGENTS.md)

- Preserve user changes; keep edits scoped; do not commit or deploy unless explicitly requested.
- Target Python 3.10+, type hints, four-space indentation, and the 100-column guideline.
- Separate network fetching from parsing/normalization; core services must not depend on `mcp_server`.
- Every behavior change needs focused tests and a full test run; use `tmp_path` for SQLite.
- Preserve legacy schemas and test migrations against temporary copies.
- Never commit keys, tokens, cookies, webhook URLs, `.env` files, or generated databases.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The official Python package is `lark-oapi`. | Standard Stack | The pinned release/API must still be checked in the implementation environment. |
| A2 | The official SDK sample's event callback shape applies to the pinned release. | Routing | Wrong envelope assumptions could reject or misroute events. |
| A3 | A new event ledger should use the proposed states/lease fields. | Idempotency | Recovery behavior and migration shape could differ. |
| A4 | The proposed principal string format is suitable. | Routing | Session merging or identity matching could be incorrect. |
| A5 | Conservative bounded reconnect defaults are acceptable. | Reconnect | Too aggressive or slow recovery affects availability. |

## Open Questions

1. Verify the pinned SDK version's WebSocket client constructor, callback/event type, acknowledgment semantics, and send-message API against the official sample.
2. Verify how private sender identity and group mention metadata are represented, including bot mention removal.
3. Verify the official image message/resource download flow and whether the current Gemini DTO needs an additive media field.
4. Decide whether delivery targets are configured user IDs, chat IDs, or both; keep the existing webhook notification configuration untouched.
5. Define exact reconnect defaults and lease duration from operational constraints, then test them deterministically.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | implementation/tests | yes | local interpreter reported by command | — |
| pytest | validation | yes | local `python -m pytest --version` | — |
| Feishu SDK | WebSocket transport | not confirmed | — | implementation-time official docs/registry verification required |
| Feishu credentials/service | live integration | not checked | — | mocked SDK tests; live test later |

## Sources

### Primary (HIGH confidence)

- Repository source files requested by the phase and `docs/intelligence.md` - existing Assistant, SQLite, timezone, and notification contracts. `[VERIFIED: codebase grep]`
- https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/server-side-sdk/python--sdk/handle-events - official Python SDK event handling documentation. `[CITED]`
- https://github.com/larksuite/oapi-sdk-python/blob/v2_main/samples/ws/sample.py - official WebSocket sample using `lark.ws.Client` and `p2_im_message_receive_v1`. `[VERIFIED]`
- https://github.com/larksuite/oapi-sdk-python/blob/v2_main/samples/api/im/v1/reply_message_sample.py - official typed IM reply sample. `[VERIFIED]`
- https://github.com/larksuite/oapi-sdk-python/blob/v2_main/README.md - official package name and installation/API overview. `[VERIFIED]`

### Secondary (MEDIUM confidence)

- None.

## Metadata

**Confidence breakdown:**
- Standard stack: LOW - SDK package and API intentionally not verified locally.
- Architecture: HIGH - directly grounded in Phase 4 source and project constraints.
- Pitfalls: MEDIUM - durable/idempotent behavior follows existing contracts; vendor envelope details remain open.

**Research date:** 2026-09-12  
**Valid until:** 2026-09-19 for SDK details; 2026-10-12 for repository contracts.

## RESEARCH COMPLETE
