# Phase 4 Research

**Scope:** Centralize Gemini and add a bounded local Assistant without weakening Phases 0-3.

## Research Outcome

Two initial broad research-agent pairs failed to return through bounded waits and were closed. A
third, tightly scoped pair completed: one reviewed Gemini migration, and one reviewed Assistant,
session, retrieval, citation, and tool contracts. Their recommendations converged on typed core
boundaries with compatibility facades and deny-by-default capabilities.

## Current Gemini Call Paths

| Current owner/caller | Problem | Phase 4 direction |
|---|---|---|
| `services/translation_service.py` | Core imports `mcp_server.tools.translation` and reaches into SDK fields | Preserve tuple/batch APIs, inject/delegate to core `GeminiClient` |
| `intelligence/gemini_wording.py` | Owns a second direct Google SDK client | Keep `enhance()` and JSON validation; delegate generation to `analyze()` |
| `ai_frontier/translator.py` | Introspects MCP constructor to recover a default key | Remove introspection; accept settings/injected core translation service |
| `mcp_server/tools/translation.py` | Owns Gemini, embeds a revoked default key, and also owns free fallbacks | Default key to `None`; delegate Gemini inward while preserving result dictionaries and free fallbacks |
| main and AI entry points | Build separate wording/translation clients | Build one configured core client and pass compatibility facades |

The installed dependency is `google-genai 1.73.1`; `requirements.txt` permits `>=1,<2`. Tests must
inject an SDK-like client or transport so no live credential or network is required. `tenacity` is
already available, but rate limiting should use a small local monotonic-time guard rather than add
another dependency.

## Recommended Gemini Contracts

- `GeminiConfig`: model, timeout, retry attempts/backoff, minimum request interval, and maximum
  input/output sizes; every numeric value bounded at settings load.
- `GeminiClient.chat()`, `.summary()`, and `.analyze()` share one internal generation path but keep
  capability-specific prompts/configuration.
- `GeminiResult`: bounded text, effective model, and optional finish/usage metadata represented by
  provider-neutral primitives.
- Structured exception family distinguishes missing configuration, timeout, rate limit/request,
  and invalid/empty response. Messages are bounded and never include prompts, credentials, or raw
  provider payloads.
- Compatibility services catch these errors at optional call sites and retain deterministic or
  original-text fallback.

## Assistant Storage And Retrieval

Extend `IntelligenceStorage` with a v3 migration containing `assistant_sessions` and
`assistant_messages`. Sessions are principal-scoped, UTC-aware, expiring, and bounded. Messages
have stable sequence numbers and unique request/role keys so retries cannot duplicate a turn.
Pruning happens inside the same short transaction as message insertion.

Local retrieval must use `stories`, `story_members`, `content_items`, and
`content_observations`, not `mcp_server.services.DataService`. Search is bounded title/summary/tag/
entity matching over a UTC half-open interval, with the existing Story ordering as the deterministic
tie-break. Each returned bundle contains its effective interval, truncation flags, members, and
observation evidence.

## Assistant And Tool Contracts

- `AssistantRequest`: request ID, principal ID, optional session ID, text, and aware UTC time.
- `AssistantReply`: session/request IDs, bounded text, effective time range, citations, tool call
  summaries, degraded flag/reason, and truncation state.
- Model context contains only bounded session turns and server-selected local bundles.
- Citation refs are generated before the model call and validated against that exact bundle after
  the call; the model cannot invent evidence URLs or IDs.
- The static registry holds `ToolSpec` values with exact argument validation and handlers. Unknown
  or unauthorized names never reach dynamic import, filesystem, shell, network, MCP, or crawler
  code. Phase 4 initially exposes only local search/detail tools and caps calls at three per turn.

## Compatibility And Failure Matrix

- Missing key: no Gemini client is created; existing pipelines continue and original translation /
  deterministic Story wording remains usable.
- Timeout, rate limit, SDK error, malformed structured output, or empty text: map to typed errors;
  optional callers fall back without affecting acquisition, persistence, ranking, reports, MCP, or
  notification.
- MCP translation keeps its current success/error dictionary fields and anonymous provider order.
- Existing `intelligence.db` v1/v2 migrations and Phase 1-3 tables remain readable; v3 assistant
  writes are transactional and idempotent.
- `INTELLIGENCE_ENABLED=false` remains the complete unified rollback. Assistant cannot operate
  without an available local intelligence store and returns a structured unavailable response.

## Test Priorities

1. No embedded/default key, environment-only credentials, redacted `repr`/errors/logs.
2. Retry classification, timeout/rate limit mapping, local rate spacing, and no retries for invalid
   configuration/response.
3. Translation ordering/fallback and Story wording compatibility under missing/malformed Gemini.
4. v2-to-v3 migration, session ownership/expiry/idempotency/concurrency, and complete-turn pruning.
5. UTC interval boundaries, deterministic Story ordering, result caps, evidence snapshots, and
   forged citation rejection.
6. Unknown/malformed/disabled tools invoke no handler; no file/shell/network escape path exists.
7. End-to-end local Assistant answer with fake Gemini plus deterministic degraded answer without
   Gemini.
8. Full Phase 0-3 regression, old schemas, all entry-point imports, and no runtime artifacts.

## Risks

- `mcp_server/tools/translation.py` mixes Gemini with free providers; migration must preserve the
  outward dictionary contract while reversing ownership.
- SQLite session migration changes `intelligence.db` schema and therefore needs explicit v1/v2
  migration tests plus future-version rejection.
- Naive `%LIKE%` retrieval is acceptable only with strict time/result bounds on the target VPS;
  semantic/vector search remains out of scope.
- Native provider tool calls must never become dynamic Python dispatch. Registry validation stays
  authoritative even if Gemini returns a tool name.
