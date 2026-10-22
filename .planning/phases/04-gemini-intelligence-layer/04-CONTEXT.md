# Phase 4: Gemini Intelligence Layer - Context

**Gathered:** 2026-09-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 4 turns Gemini into one bounded core reasoning service and adds a local intelligence
Assistant. Translation, Story wording, digest summarization, optional security interpretation, and
chat must share this service. The Assistant queries local `Story`/`ContentItem` evidence, stores a
bounded multi-turn session in SQLite, and may call only explicitly registered local tools.

Feishu transport belongs to Phase 5. Agent-Reach and all external research tools belong to Phase 6.

</domain>

<decisions>
## Implementation Decisions

### Gemini Service Boundary

- **D-01:** Create `trendradar/ai/` with a provider-facing `GeminiClient` exposing `chat()`,
  `summary()`, and `analyze()`. SDK request/response types never escape this package, and core code
  never imports `mcp_server`.
- **D-02:** Return a typed, immutable result and raise sanitized structured errors for missing
  configuration, timeout/rate limit/request failure, and invalid response. Model, timeout, retry,
  rate limit, and output bounds are centralized and injectable for offline tests.
- **D-03:** Keep existing translation tuple/list APIs, Story `enhance()` contract, MCP translation
  dictionaries, deterministic Story generation, and old reports. Compatibility facades delegate
  inward to `GeminiClient`.
- **D-04:** Remove all hard-coded/default Gemini credentials and AI Frontier key introspection.
  `GEMINI_API_KEY` remains environment-only. The already-revoked repository key requires no
  operational action in this phase beyond removing it from executable defaults.
- **D-05:** Preserve the existing no-key translation behavior: Gemini is skipped, while the MCP
  translation facade may still try its existing anonymous Google Translate/MyMemory fallbacks.
  Collection and reports must never fail because translation or Gemini is unavailable.
- **D-06:** Gemini may enhance wording, digest text, and security explanation only. It cannot
  mutate canonical identity, Story membership, deterministic Importance, CVE facts, provenance, or
  source freshness.

### Assistant And Retrieval

- **D-07:** Use provider-neutral request/reply/citation/tool DTOs. `AssistantService` owns
  conversation handling, context loading, bounded tool selection, and final citation validation;
  Feishu and MCP are adapters, not owners.
- **D-08:** Extend versioned `intelligence.db` storage for assistant sessions/messages rather than
  introduce another operational database. Migration is forward-only and preserves every Phase 1-3
  table and legacy database.
- **D-09:** Local retrieval uses UTC-aware half-open ranges `[start, end)`, defaults to the previous
  seven days, and preserves deterministic ordering: Importance descending, event time descending,
  then ID. Results include the effective time range and truncation state.
- **D-10:** Citations are server-built immutable snapshots from retrieved Story members and
  observations. Model-supplied citation references are accepted only when they were present in the
  current turn's retrieved bundle.

### Sessions And Tools

- **D-11:** Sessions are isolated by `principal_id`, use a 30-day sliding expiry, retain at most 100
  messages, and load at most 12 messages/24,000 characters while preserving complete turns. Input
  and output are capped at 8,000 and 12,000 characters.
- **D-12:** Requests are idempotent by `(session_id, request_id)` and all timestamps are UTC-aware.
  Expired, missing, or cross-principal sessions fail closed.
- **D-13:** A static registry maps names to typed argument schemas and handlers. Unknown, disabled,
  unauthorized, malformed, filesystem, shell, dynamic-import, and unregistered-network requests
  are denied before handler invocation. Limit each turn to three tool calls.
- **D-14:** Phase 4 registers only bounded local intelligence lookup tools. There is no generic file
  reader, shell, crawler trigger, URL fetcher, or Agent-Reach placeholder.

### Claude's Discretion

Exact class/file decomposition, SQLite index details, prompt wording, deterministic fallback reply,
and retry/rate-limiter implementation may follow existing repository patterns, provided the bounds
and public compatibility contracts above remain testable.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Product And Phase Scope

- `.planning/ROADMAP.md` - Phase 4 goal, four plans, and success criteria.
- `.planning/REQUIREMENTS.md` - `GEMI-01..04` and `ASST-01..04` contracts.
- `.planning/PROJECT.md` - personal-use, SQLite, compatibility, secret, and resource constraints.
- `TrendRadarpoi_v5_CODEX_CONTEXT.md` - Story-first architecture and Gemini reasoning role.
- `TrendRadarpoi_v5_Codex_Task_List.md` - required `GeminiClient` and `AssistantService` deliverables.
- `TrendRadarpoi_v5_Implementation_Plan_Codex_Execution_Edition.md` - Phase 4 module and interface
  direction.
- `TrendRadarpoi_Feishu_Project_Task_Document.txt` - Gemini/Assistant responsibilities and the
  explicit no-shell boundary.

### Existing Contracts

- `.planning/phases/02-story-intelligence/VERIFICATION.md` - deterministic Story and Gemini
  fallback contracts that must remain green.
- `.planning/phases/03-security-intelligence-domain/VERIFICATION.md` - security evidence,
  ranking, and isolation contracts.
- `docs/code-review.md` - documents the current core-to-MCP translation ownership defect.
- `docs/intelligence.md` - canonical storage, Story, Security, and rollback operation.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `RuntimeSettings`: environment-only secrets and environment/YAML/default precedence.
- `GeminiStoryWordingClient`: lazy SDK injection, fenced JSON parsing, and bounded wording output.
- `TranslationService`: legacy title/batch translation surface that callers already depend on.
- `IntelligenceStorage`: schema migration, transactions, Story/member/evidence queries, and stable
  ordering.
- `Story`, `ContentItem`, and security evidence projections: provider-neutral context and citations.

### Established Patterns

- Optional AI changes wording only and falls back deterministically on every provider failure.
- SQLite migrations are forward-only, transactional, WAL-enabled, and tested from prior versions.
- Configuration values are bounded; secret-looking YAML values are ignored.
- Legacy paths remain authoritative and unified failures must not refetch upstream.

### Integration Points

- Replace Gemini ownership in `trendradar/services/translation_service.py` and
  `trendradar/intelligence/gemini_wording.py` while preserving their callers.
- Remove `trendradar/ai_frontier/translator.py` introspection of MCP defaults.
- Keep `mcp_server/tools/translation.py` as an outward compatibility adapter to core services.
- Extend `IntelligenceStorage` with local retrieval plus assistant session/message methods.
- Phase 5 will call `AssistantService`; Phase 6 may later register bounded ResearchGateway tools.

</code_context>

<specifics>
## Specific Ideas

- Default local question window: previous seven days, always echoed in the reply.
- Default query caps: 20 Stories, 8 items per Story, 16 observations per Story, and 12 citations.
- The Assistant should answer from deterministic local evidence even when Gemini is unavailable,
  clearly indicating that synthesis was degraded rather than returning an empty response.

</specifics>

<deferred>
## Deferred Ideas

- Feishu message transport, whitelist enforcement, and scheduled push: Phase 5.
- Web/GitHub/Reddit/YouTube research through Agent-Reach: Phase 6.
- Semantic vector search and personal knowledge graph: deferred until measured need.

</deferred>

---

*Phase: 04-gemini-intelligence-layer*
*Context gathered: 2026-09-04*

