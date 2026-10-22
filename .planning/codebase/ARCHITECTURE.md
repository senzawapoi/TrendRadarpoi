<!-- refreshed: 2026-09-12 -->
# Architecture

**Analysis Date:** 2026-10-14 (runtime-boundary reconciliation)

## System Overview

```text
Main crawler / AI Frontier -> existing collectors -> SourceAdapter
  -> Normalize / Deduplicate -> intelligence.db -> Story / Security / Importance
  -> compatibility projections -> legacy SQLite / reports / notifications

FastMCP -> core services / legacy history / selected crawl operations

Feishu SDK runner (opt-in) -> identity / chat / event gate -> local Assistant
  -> bounded SQLite retrieval / static read tools -> optional core GeminiClient
  -> persisted response -> SDK reply
Feishu daily scheduler -> ranked Stories -> digest -> durable delivery checkpoints
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| Main orchestrator | Runs hot-list and RSS crawl, translation, storage, analysis, report, and push in one process | `trendradar/__main__.py` |
| App context | Wraps loaded configuration and constructs storage, report, and notification collaborators | `trendradar/context.py` |
| Core | Configuration, keyword matching, ranking/frequency analysis, and shared exceptions | `trendradar/core/` |
| Unified source boundary | Wraps NewsNow, RSS, and enabled AI Frontier sources without replacing their parsers | `trendradar/sources/` |
| Intelligence data layer | Runs adapters, normalizes, deduplicates, builds Stories, stores provenance/Assistant sessions, and backfills history | `trendradar/intelligence/` |
| AI and Assistant | Owns Gemini, translation/analysis, bounded sessions, retrieval, citations, and static local tools | `trendradar/ai/` |
| Security domain | Collects, analyzes, ranks, and reports CISA/NVD/RSS security evidence | `trendradar/domains/security/` |
| Storage | Date-partitioned SQLite/local output and optional S3-compatible backend | `trendradar/storage/` |
| AI Frontier | Independent seven-source async aggregation, deduplication, translation, SQLite state, rendering, and Bark push | `trendradar/ai_frontier/` |
| MCP server | Exposes historical query, analytics, crawl, config, translation, and storage tools | `mcp_server/server.py` |
| Feishu integration | Authorizes SDK events, bounds media/workers, suppresses completed duplicates, retries failed delivery and schedules daily delivery | `trendradar/integrations/feishu/` |
| External research | Opt-in allowlisted evidence through isolated Agent-Reach routes; no ingestion or arbitrary shell dispatch | `trendradar/research/` |
| Operations | Strict database checks/migration, read-only health, durable maintenance/deployment guards and multi-database recovery | `trendradar/ops/` |

## Pattern Overview

**Overall:** Modular monolith with four independently orchestrated runtime surfaces.

**Key Characteristics:**
- The main crawler is a procedural pipeline coordinated by one large `main()` function.
- Storage uses a backend/manager abstraction; unified acquisition wraps existing fetchers with a common adapter contract.
- AI Frontier retains its own `AIItem` and SQLite output while also writing canonical content best effort.
- MCP wraps storage and analysis capabilities as an interface; its translation facade delegates to
  the core-owned `trendradar.ai` package.
- Feishu is a separate opt-in transport; legacy entrypoints never start its SDK connection.

## Layers

**Acquisition:**
- Purpose: fetch hot lists, RSS, and specialized AI sources.
- Location: `trendradar/crawler/`, `trendradar/ai_frontier/sources/`, and wrappers in `trendradar/sources/`.
- Depends on: requests, aiohttp, feedparser, BeautifulSoup, and public services.
- Used by: main crawler, AI Frontier CLI, and MCP crawl tool.

**Domain and analysis:**
- Purpose: represent content, build/rank Stories, analyze security evidence, and provide bounded local answers.
- Location: `trendradar/core/models/`, `trendradar/intelligence/`, `trendradar/ai/`,
  `trendradar/domains/security/`, `trendradar/storage/base.py`, and `trendradar/ai_frontier/sources/base.py`.
- Constraint: `ContentItem` is canonical input, while `NewsItem`, `RSSItem`, and `AIItem` remain required compatibility contracts.

**Application orchestration:**
- Purpose: order pipeline stages and choose mode-specific behavior.
- Location: main/AI Frontier entrypoints, `mcp_server/server.py`, and
  `trendradar/integrations/feishu/__main__.py`.
- Depends on: acquisition, services, storage, reports, and notifications.

**Persistence and output:**
- Purpose: retain crawl/Story/Assistant history, detect new items, render reports, and push messages.
- Location: `trendradar/intelligence/storage.py`, `trendradar/storage/`, `trendradar/report/`, `trendradar/notification/`, and `trendradar/ai_frontier/storage.py`.

## Data Flow

### Main Crawl Path

1. `load_config()` builds normalized configuration and `AppContext` (`trendradar/__main__.py`).
2. Per-platform/per-feed adapters reuse `DataFetcher` and `RSSFetcher`, then normalize to `ContentItem`.
3. Deduplication writes canonical items plus observations to `intelligence.db` and projects the raw records back to legacy groupings.
4. Canonical representatives are translated once and translation fields propagate to compatible duplicates; `StorageManager` persists legacy history.
5. Existing analyzers, reports, and `NotificationDispatcher` continue unchanged.

### AI Frontier Path

1. `build_sources()` still constructs seven enabled `AISource` implementations.
2. With intelligence enabled, one wrapper adapter runs per enabled top-level source; existing classes retain internal fan-out.
3. Canonical output is deduplicated and written best effort, then projected back to `AIItem` for freshness, legacy deduplication, and `AIFrontierStorage`.
4. Source thresholds, optional translation, HTML, and Bark behavior remain compatible.

### MCP Request Path

1. FastMCP receives a stdio or HTTP tool call in `mcp_server/server.py`.
2. The registered service/tool object validates parameters and reads SQLite/config data or triggers a crawl.
3. The tool returns structured dictionaries or formatted text to the MCP client.

### Local Assistant Path

1. `AssistantService` validates principal, request, optional owned Session, UTC range, and limits.
2. `LocalRetriever` reads bounded Story/ContentItem evidence from the caller-owned unified storage.
3. The optional shared `GeminiClient` may synthesize text or request one of three registered local
   read tools; citations are accepted only from server-built evidence in the current turn.
4. Missing or failed Gemini returns deterministic local evidence and persists one complete,
   idempotent user/assistant turn.

### Feishu Path

1. The official SDK callback validates the envelope, configured identities and chat/mention scope
   before parsing content.
2. Authorized prepared messages are persisted before entering a bounded worker queue;
   startup recovery and ongoing polling recover eligible durable work. The worker rechecks authorization.
3. The event ledger claims `event_id`; completed duplicates are suppressed without another Lark
   send or Assistant turn, while failed delivery retries a saved reply. Media downloads are
   bounded and image bytes stay in memory.
4. Chat-scoped hashed principals/sessions call the existing Assistant and static tools.
5. Replies and daily digests use persisted leases/checkpoints; reconnect attempts have cooldown.
   These local guarantees cannot make provider acceptance and SQLite commits atomic. See
   [Lark limits](../../docs/intelligence.md#lark-assistant).

### Research And Operations

Assistant can use the optional `research_external` tool only through the named
ResearchGateway capabilities. External results are bounded, untrusted evidence
and do not enter the ingestion database. Production operations separate Bot,
Worker and one-shot Scheduler roles. A fixed root-owned installer loads trusted
configuration; durable deployment/restore transactions gate acceptance of work.
See [deployment contracts](../../docs/deployment.md) and
[current acceptance gaps](../../docs/phase7-actual-gap-evidence/HANDOFF.md).

**State Management:**
- SQLite files are the persistent state; date folders partition core news/RSS data while AI Frontier uses one database.
- `output/intelligence.db` schema v6 stores canonical content, observations, source runs, Stories,
  memberships, Assistant sessions/messages, and additive Feishu event/delivery ledgers;
  legacy stores remain current read authority.
- `AppContext` caches collaborators per process, and MCP uses an in-process cache singleton.
- GitHub Actions cache is relied on to preserve state between ephemeral jobs.

## Key Abstractions

**StorageBackend / StorageManager:**
- Purpose: select local or remote persistence without changing orchestration.
- Examples: `trendradar/storage/base.py`, `trendradar/storage/local.py`, `trendradar/storage/remote.py`.
- Pattern: strategy plus facade.

**AISource / AIItem:**
- Purpose: normalize specialized AI sources for the AI Frontier pipeline.
- Examples: `trendradar/ai_frontier/sources/base.py` and sibling source modules.
- Pattern: async adapter interface plus dataclass DTO.

**SourceAdapter / ContentItem:**
- Purpose: provide one failure-isolated normalization boundary across existing source implementations.
- Examples: `trendradar/sources/base.py`, `trendradar/core/models/`, and `trendradar/intelligence/runner.py`.
- Pattern: generic adapter plus canonical DTO and compatibility projections.

**IntelligenceStorage / Deduplicator:**
- Purpose: preserve canonical identity, source evidence, run health, and idempotent historical import.
- Examples: `trendradar/intelligence/storage.py` and `trendradar/intelligence/deduplicate.py`.
- Pattern: transactional local SQLite repository plus deterministic matching policy.

**GeminiClient / AssistantService / ToolRegistry:**
- Purpose: isolate provider behavior and expose bounded, grounded local intelligence conversation.
- Examples: `trendradar/ai/client.py`, `trendradar/ai/assistant.py`, and `trendradar/ai/tools.py`.
- Pattern: provider boundary plus principal-scoped application service and deny-by-default registry.

**AppContext:**
- Purpose: centralize configuration-dependent collaborators and utility calls.
- Example: `trendradar/context.py`.
- Pattern: application context/service locator.

## Entry Points

**Main crawler:**
- Location: `trendradar/__main__.py`.
- Triggers: `python -m trendradar`, console script, GitHub Actions, or Docker cron.
- Responsibilities: complete scheduled collection-to-notification batch.

**AI Frontier:**
- Location: `trendradar/ai_frontier/__main__.py`.
- Triggers: `python -m trendradar.ai_frontier` or its scheduled workflow.
- Responsibilities: focused AI-source collection and Bark report.

**MCP:**
- Location: `mcp_server/server.py`.
- Triggers: `trendradar-mcp`, stdio client, or HTTP server.
- Responsibilities: query and management tools over stored data.

**Feishu:**
- Location: `trendradar/integrations/feishu/__main__.py`.
- Triggers: `python -m trendradar.integrations.feishu`; disabled unless explicitly configured.
- Responsibilities: SDK lifecycle, bounded event handling, Assistant replies and daily scheduling.
- `--check` validates settings without network access or opening SQLite, not live tenant readiness.

## Architectural Constraints

- **Concurrency:** the main hot-list crawl is synchronous; core RSS and AI Frontier use asyncio/aiohttp, and blocking parsing is selectively sent to threads.
- **Resource model:** batch jobs load collections in memory; Feishu adds a bounded in-process
  worker queue, not an external queue service. Keep SQLite transactions and provider calls bounded.
- **Relative paths:** several entry points assume the repository/application root contains `config/` and `output/`.
- **Global state:** logging and MCP cache are module-level singletons in `trendradar/utils/logging.py` and `mcp_server/services/cache_service.py`.
- **Compatibility:** SQLite and low-maintenance single-user deployment are explicit constraints; do not introduce PostgreSQL, vector DB, or Kubernetes in the current milestone.
- **Rollback:** `INTELLIGENCE_ENABLED=false` must bypass adapters; a unified-store failure must preserve already-fetched legacy output without an upstream refetch.

## Anti-Patterns

### Interface Backflow Into Core

**What happens:** a transport or MCP tool imports its policy into a core service, making the core
depend on an optional interface.
**Why it's wrong:** core runtime availability and security boundaries would depend on transport code.
**Do this instead:** keep Gemini/Assistant ownership in `trendradar/ai/`; Feishu and MCP may call
core services but never become their dependencies.

### Transitional Dual Persistence

**What happens:** canonical writes run beside three legacy schemas and some downstream normalization/deduplication remains subsystem-specific.
**Why it's risky:** mismatched stage ordering or identity rules can make canonical and rendered results diverge.
**Do this instead:** keep parity and rollback tests, migrate one consumer at a time, and retain legacy readers until each replacement is verified.

### Monolithic Orchestrators

**What happens:** `trendradar/__main__.py` and multiple MCP tool modules combine policy, data transformation, I/O, and presentation.
**Why it's wrong:** changes have broad blast radius and are difficult to unit test.
**Do this instead:** extract application services by pipeline stage and keep entry points as composition roots.

## Error Handling

**Strategy:** best-effort batch processing with retries and partial-failure logging.

**Patterns:**
- Typed exceptions and `BatchResult` exist in `trendradar/core/exceptions.py`.
- Source failures are isolated with `asyncio.gather(..., return_exceptions=True)` in AI Frontier.
- Legacy modules frequently catch broad `Exception`, log/print, and return sentinel values.

## Cross-Cutting Concerns

**Logging:** structlog is standard in newer `trendradar` code; MCP and legacy paths mix direct prints.
**Validation:** MCP uses explicit validators; YAML configuration is mostly defaulted and normalized rather than schema-validated.
**Authentication:** Assistant sessions enforce principal ownership. The opt-in Phase 5 Feishu
transport denies unmatched configured identities before content parsing, media, Assistant or
Gemini. Group messages require the configured bot mention. MCP HTTP still relies on deployment
isolation. See `docs/intelligence.md` and Phase 5 `VERIFICATION.md` for the offline-tested boundary.

---

*Architecture analysis: 2026-10-14; acceptance gaps are tracked separately.*
