# Phase 5: Feishu Assistant - Context

**Gathered:** 2026-09-12
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 5 adds a Feishu inbound transport and daily Story delivery around the completed
`AssistantService`. It must support private chats and group chats where the bot is mentioned,
enforce a configurable deny-by-default identity allowlist, persist event idempotency, and keep
WebSocket reconnects bounded. Feishu remains a thin adapter: session ownership, local retrieval,
Gemini use, tools, citations, and degraded replies stay inside the Phase 4 Assistant boundary.

</domain>

<decisions>
## Implementation Decisions

### Identity and Chat Scope

- **D-01:** Allowed identities are configured through identity fields rather than a hard-coded
  Feishu identifier type. The configuration must be able to express the field name and accepted
  values, with deny-by-default behavior when no identity matches.
- **D-02:** Both private chats and group chats are supported. In a group, a message must mention
  the bot before it can enter the Assistant path.
- **D-03:** The transport must pass a stable, sanitized principal and chat/session scope into the
  existing Assistant session model. Group context must not accidentally merge unrelated users or
  conversations.

### Message and Media Handling

- **D-04:** Text messages are supported immediately. The configured Gemini capability may also
  receive image content, so the adapter must preserve text-plus-image and image-only message
  intent instead of rejecting images at the transport boundary.
- **D-05:** The implementation should preserve the existing Assistant and Gemini failure
  behavior: bounded deterministic replies remain available when provider processing fails.
- **D-06:** Unsupported Feishu event types must not invoke Assistant tools or Gemini and should be
  handled as a bounded, non-fatal transport outcome.

### Event Idempotency and Connection Recovery

- **D-07:** `event_id` is the primary deduplication key because it is compact and supplied by
  Feishu. Duplicate events must receive a reply, using the previously generated response when a
  response was persisted, rather than triggering a second Assistant/Gemini turn.
- **D-08:** Event processing must survive process restarts through the existing local SQLite
  operational boundary or an additive table in it; an in-memory-only cache is insufficient for
  the required restart behavior.
- **D-09:** WebSocket reconnection is bounded. After the configured number of connection attempts
  or failures is reached, the client enters a cooldown period before attempting again. The
  threshold and cooldown are configuration values, with sensible repository defaults.

### Daily Story Delivery

- **D-10:** Daily Feishu delivery initially follows the repository's existing report, notification,
  and scheduling defaults. New delivery-specific polishing is deferred until the baseline path is
  working.
- **D-11:** Delivery uses `Asia/Shanghai` and must be idempotent across restarts, so a successful
  daily delivery cannot be sent repeatedly for the same configured delivery window.

### The Agent's Discretion

- Exact Feishu SDK module and event callback decomposition, provided the official SDK WebSocket
  path and `integrations/feishu/` separation are preserved.
- The concrete identity mapping schema, default reconnect threshold/cooldown, and bounded retry
  backoff, provided they are configurable and tested.
- Whether the Feishu event ledger is an additive `intelligence.db` table or a narrowly scoped
  companion table, provided it does not alter existing legacy schemas or Assistant contracts.
- The exact media fetch/normalization DTO needed to pass image input through the existing Gemini
  boundary without leaking SDK types.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase and Product Scope

- `.planning/ROADMAP.md` - Phase 5 goal, success criteria, and four-plan execution order.
- `.planning/REQUIREMENTS.md` - FEIS-01 through FEIS-07 contracts.
- `.planning/PROJECT.md` - compatibility, personal-use, Feishu, timezone, and permission decisions.
- `TrendRadarpoi_v5_CODEX_CONTEXT.md` - v5 architecture and intended assistant boundary.
- `TrendRadarpoi_v5_Codex_Task_List.md` - Feishu task requirements and sequencing.
- `TrendRadarpoi_v5_Implementation_Plan_Codex_Execution_Edition.md` - implementation constraints and
  rollback expectations.
- `TrendRadarpoi_Feishu_Project_Task_Document.txt` - Feishu/Gemini responsibilities and no-shell
  boundary.

### Existing Assistant and Runtime Contracts

- `.planning/phases/04-gemini-intelligence-layer/04-CONTEXT.md` - locked Assistant, session,
  citation, tool, and Gemini boundaries.
- `.planning/phases/04-gemini-intelligence-layer/VERIFICATION.md` - verified Phase 4 behavior that
  the Feishu adapter must preserve.
- `trendradar/ai/assistant.py` - provider-neutral Assistant service entry point.
- `trendradar/ai/session.py` - principal-scoped sessions, complete turns, and idempotency model.
- `trendradar/ai/client.py` - bounded Gemini provider boundary.
- `trendradar/ai/models.py` - Assistant request/reply and provider-neutral DTOs.
- `trendradar/intelligence/storage.py` - versioned SQLite storage and migration patterns.
- `trendradar/core/settings.py` - environment-first settings and secret handling.
- `config/config.yaml` - existing timezone, report, notification, and Feishu webhook defaults.
- `.env.example` - environment-only Feishu and Gemini secret names.
- `README.md` - existing report modes and Feishu notification behavior.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `AssistantService` and `AssistantSessionStore`: keep conversation, tools, citations, bounded
  history, and deterministic fallback inside the existing service.
- `GeminiClient`: reuse the provider-neutral chat boundary and extend its media DTO only if the
  planner confirms that image input is required by the SDK contract.
- `IntelligenceStorage`: reuse WAL, transactions, and migration conventions for durable event and
  daily-delivery idempotency.
- Existing Feishu notification renderers and senders: reuse output formatting where it matches the
  Story report baseline; do not replace the legacy webhook channel.

### Established Patterns

- Environment values override YAML only when non-empty; secrets are environment-only.
- Optional provider failures degrade deterministically and do not interrupt collection or legacy
  notification paths.
- SQLite migrations are forward-only and preserve existing tables and data.
- Core services do not depend on `mcp_server`; transport modules adapt inward to core services.

### Integration Points

- New `integrations/feishu/` modules connect Feishu events to `AssistantService`.
- `trendradar/ai/session.py` receives a stable principal/session mapping, while the transport owns
  Feishu chat identity and event IDs.
- `trendradar/intelligence/story_report.py` and existing notification formatting provide the daily
  Story content source.
- `.env.example`, `core/settings.py`, and `config/config.yaml` provide configuration boundaries.

</code_context>

<specifics>
## Specific Ideas

- Use the existing project baseline first for daily delivery; refine the report experience later.
- The user's Gemini credential supports both text and image processing; do not impose an artificial
  text-only transport restriction.
- Duplicate events should still receive a reply, but must not cause duplicate model calls or turns.
- Connection storms should cool down after a configured threshold instead of reconnecting forever.

</specifics>

<deferred>
## Deferred Ideas

- Daily report presentation and prioritization refinements beyond the existing repository baseline.
- Agent-Reach and external research tools remain Phase 6.
- VPS/systemd deployment and long-running service operations remain Phase 7.

</deferred>

---

*Phase: 05-feishu-assistant*
*Context gathered: 2026-09-12*
