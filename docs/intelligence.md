# Unified Intelligence And Story Layer

Phase 1 adds a compatibility-first canonical ingestion path. Phase 2 derives stable, ranked Stories
from that canonical data. Phase 3 adds a bounded security domain. Existing reports, notifications,
MCP readers, and legacy SQLite schemas remain unchanged; Story and security reports are additive
views. Phase 4 centralizes Gemini and adds a bounded local Assistant with schema-v3 sessions,
server-built citations, and static local-read tools. Phase 5 adds opt-in Lark transport,
bounded image input, event deduplication, saved-reply delivery retry and daily delivery with
additive ledgers, now at schema v7 with durable prepared events and instant Story delivery. Phase 6 adds
optional bounded external research; Phase 7 operations are documented separately
in [deployment.md](deployment.md), with current acceptance still unfinished.

## Data Flow

```text
existing collector -> SourceAdapter -> Normalize -> ContentItem -> Deduplicate
                                                            |-> intelligence.db
                                                            `-> legacy projection/output
                                                                    |
canonical ContentItem -> Cluster -> Story -> Importance -> output/stories/YYYY-MM-DD.html

CISA KEV / NVD / security RSS -> ContentItem(security) -> Security Story
                                                        -> output/security/YYYY-MM-DD.html

local question -> AssistantService -> bounded Story/ContentItem retrieval
                                  |-> optional shared Gemini synthesis
                                  `-> assistant_sessions/messages in intelligence.db
```

`NewsNowAdapter` runs one platform at a time and preserves the configured request delay. RSS uses
one adapter per feed with a default concurrency limit of five. AI Frontier wraps each enabled
top-level source while its existing source classes retain their internal account, keyword, feed,
or site fan-out.

`AdapterRunner` isolates fetch and per-item normalization failures. Its passive health state is
`unknown`, `healthy`, `degraded`, or `unhealthy`; `health_check()` never performs another request.

## Content Contract

`ContentItem` is defined in `trendradar/core/models/`. It contains `id`, `title`, `content`, `url`,
`source`, `domain`, `published_time`, `collected_at`, `tags`, and `metadata`.

- Timestamps are UTC-aware; `published_time` may be absent and `collected_at` is required.
- Sources use `newsnow:<platform>`, `rss:<feed>`, or `ai_frontier:<source-key>`.
- Supported domains are `general`, `ai`, and `security`.
- URLs are canonicalized before deterministic UUIDv5 identity is generated. URL-less identity uses
  source, normalized title, and event date.
- Metadata retains legacy fields, raw URLs, source IDs and names, ranking, author, score, and
  translations so `NewsItem`, `RSSItem`, and `AIItem` can round-trip without field loss.

## Story Intelligence

Clustering is deterministic and offline. It combines a bounded time window, normalized title
tokens, configured entity keywords, and tags. Conflicting non-empty entities do not merge, a
cluster cannot span beyond its configured time window, and every unmatched item becomes a
singleton Story.

Story IDs remain stable when later sources extend an existing event. Membership and source
observations are retained as evidence. The default generator creates bounded title and summary
wording without a provider; an injected wording client may change only those two fields. It cannot
change identity, membership, evidence, or ranking, and invalid/provider-failure output falls back
to deterministic wording.

Importance is an explainable 0-100 score composed from source diversity, source reliability,
observation activity, recency, and configured user interests. The ordering tie-breaker is score
descending, event time descending, then Story ID ascending.

## Security Intelligence

Security collection reuses the canonical storage and Story pipeline; it does not create another
database. Enabled sources use these logical IDs:

| Source | Adapter ID | Default bound |
|--------|------------|---------------|
| CISA Known Exploited Vulnerabilities | `security:cisa-kev` | newest 500 records |
| NVD CVE API 2.0 | `security:nvd` | 48-hour lookback, 2 pages, 200 records |
| Configured RSS/Atom feed | `security:rss:<feed-id>` | 50 items for the default CISA feed |

Every record keeps CVE IDs, severity, CVSS version/vector, KEV status, due date, required action,
vendor/product, references, source name, and raw URL in tags, metadata, or observations. CISA and
NVD records for an exact CVE share a canonical NVD detail URL. Exact CVE IDs are also strong
security-clustering anchors across source and ordinary time-window boundaries. Multi-CVE records
strongly merge only when their CVE sets are identical, preventing an `A -> A+B -> B` bridge.

Security Importance is deterministic and combines the base Story score (15%), severity/CVSS
(35%), known exploitation (30%), and action/due-date evidence (20%). CVSS evidence is selected by
version priority (`v4`, `v3.1`, `v3.0`, then `v2`), then score. The standalone HTML report contains
the score reasons, action fields, every persisted source observation, and source freshness.

Freshness is passive: it reads `source_runs` and never performs another request. Every configured
enabled source appears, even when absent from the current fetch result. A source is stale when it
has no successful/degraded run or its latest such run is older than `stale_after_hours`.

## Deduplication And Storage

Rules run in this order: an existing `(source, source_content_id)` observation, equal canonical URL
across sources, exact normalized title within the same source and 24 hours, then same-source fuzzy
title matching for titles of at least 12 characters at a `0.92` ratio. Fuzzy matching never crosses
sources. Every input remains an observation even when it shares a canonical item.

`output/intelligence.db` uses SQLite schema version 7, WAL, foreign keys, and a five-second busy
timeout:

| Table | Purpose |
|-------|---------|
| `content_items` | Canonical normalized records |
| `content_observations` | Per-source evidence and first/last observation times |
| `source_runs` | Adapter status, duration, counts, and error summary |
| `clusters` | Deterministic cluster signatures and members |
| `stories` | Stable Story fields, Importance, and generator metadata |
| `story_members` | Idempotent Story-to-ContentItem membership |
| `assistant_sessions` | Principal-owned sessions with sliding UTC expiry |
| `assistant_messages` | Complete, idempotent user/assistant turns |
| `feishu_events` | Event claims, leases, duplicate suppression and saved-reply delivery retry |
| `feishu_deliveries` | Daily delivery claims and confirmed chunk checkpoints |
| `lark_instant_batches` | Frozen instant payloads, leases, retry state and chunk checkpoints |
| `lark_story_deliveries` | Persistent target/Story registration, sent state and restore quarantine |

Production uses explicit v6-to-v7 migration and `LARK_DELIVERY_MODE=instant`.
`stories.created_at` determines first persistence; event time and later updates do not
reset delivery identity. Each tick retries saved work or registers up to 20 Stories.
Existing unregistered Stories remain eligible after migration, so a fresh production
database avoids importing a historical backlog. Daily delivery is available only when
explicitly selected; the production configuration runs one delivery mode.

The date-partitioned databases in `output/news/` and `output/rss/`, plus
`output/ai_frontier.db`, remain the compatibility authority for current reports and MCP. Unified
storage remains local-only in the current milestone and is not synchronized by the S3 backend.

## Configuration And Rollback

```yaml
intelligence:
  enabled: true
  database_path: "output/intelligence.db"
  story:
    enabled: true
    output_dir: "output/stories"
    timezone: "Asia/Shanghai"
    clustering:
      time_window_hours: 24
      token_jaccard_threshold: 0.35
      title_similarity_threshold: 0.70
      min_shared_tokens: 2
      entity_keywords: {}
    ranking:
      user_interests: []
      source_reliability: {}
      recency_half_life_hours: 24
    report:
      enabled: true
      max_stories: 100
  assistant:
    enabled: true
    session_ttl_days: 30
    max_messages: 100
    max_history_messages: 12
    max_context_chars: 24000
    max_input_chars: 8000
    max_output_chars: 12000
    default_lookback_days: 7
    max_stories: 20
    max_members_per_story: 8
    max_observations_per_story: 16
    max_items: 20
    max_citations: 12
    max_tool_calls: 3
    max_tool_result_chars: 4000
    tools:
      search_stories: true
      search_content_items: true
      get_story_evidence: true
  security:
    enabled: true
    timezone: "Asia/Shanghai"
    output_dir: "output/security"
    max_concurrency: 4
    stale_after_hours: 48
    sources:
      cisa_kev:
        enabled: true
        timeout: 30
        max_items: 500
      nvd:
        enabled: true
        timeout: 30
        lookback_hours: 48
        results_per_page: 100
        max_pages: 2
        max_items: 200
        request_interval_seconds: 6
      rss:
        enabled: true
        timeout: 20
        max_age_days: 7
        feeds:
          - id: "cisa-advisories"
            name: "CISA Cybersecurity Advisories"
            url: "https://www.cisa.gov/cybersecurity-advisories/all.xml"
            max_items: 50
    ranking:
      weights: {base: 0.15, severity: 0.35, known_exploited: 0.30, action: 0.20}
    report:
      enabled: true
      lookback_days: 30
      max_candidates: 500
      max_stories: 100
```

Non-empty `INTELLIGENCE_ENABLED` and `INTELLIGENCE_DB_PATH` values override YAML. Set
`INTELLIGENCE_ENABLED=false` to restore legacy acquisition completely. If the unified database
cannot open or a batch write fails, the process logs the error and continues the legacy output path
with already-fetched records; it does not refetch upstream sources.

`INTELLIGENCE_STORY_ENABLED`, `INTELLIGENCE_STORY_OUTPUT_DIR`,
`INTELLIGENCE_STORY_WORDING_ENABLED`, and comma-separated `INTELLIGENCE_USER_INTERESTS` override
their Story settings. Disable only Story derivation with `INTELLIGENCE_STORY_ENABLED=false`.
Wording enhancement is off by default; when enabled and a `GEMINI_API_KEY` is available, the lazy
Gemini client may rewrite only the Story title and summary. It cannot choose identity, members,
evidence, importance, or ranking, and all provider failures use deterministic fallback wording.
Story persistence/report failures are best effort and cannot interrupt canonical ingestion or
legacy output. The Story report is additive and never replaces `output/index.html`.

`INTELLIGENCE_SECURITY_ENABLED`, `INTELLIGENCE_SECURITY_OUTPUT_DIR`,
`INTELLIGENCE_SECURITY_MAX_CONCURRENCY`, and `INTELLIGENCE_SECURITY_STALE_AFTER_HOURS` override
their security settings. `NVD_API_KEY` is optional and environment-only; credential-looking YAML
fields are discarded. Set `INTELLIGENCE_SECURITY_ENABLED=false` to disable only security
collection and reporting. Set `INTELLIGENCE_ENABLED=false` to disable the complete unified path,
including Security and Story processing. Collection, persistence, Story processing, analysis,
freshness, and report stages are isolated so a security failure cannot interrupt or refetch the
legacy NewsNow, RSS, or AI Frontier paths.

## Gemini And Local Assistant

`trendradar.ai.GeminiClient` is the single provider boundary for chat, summaries, analysis, Story
wording, digest text, security narrative, and translation. `GEMINI_API_KEY` is read only from the
environment. Provider SDK objects, prompts, credentials, raw errors, and mutable ranking authority
do not leave this boundary. Gemini may improve wording but cannot change canonical IDs, Story
membership, Importance, CVE facts, source evidence, or freshness.

`AssistantService` reads only the caller-provided `IntelligenceStorage`; its factory never opens a
second database. Sessions belong to one `principal_id`, expire after 30 days by default, and refresh
their expiry on use. A turn is stored atomically as one user and one assistant message. The default
retention is 100 messages; context loads the newest complete turns only, with limits of 12 messages
and 24,000 characters. `(session_id, request_id)` makes retries idempotent.

Local search uses explicit aware UTC half-open ranges `[start, end)`, defaulting to the previous
seven days. Stories are ordered by Importance descending, event time descending, then ID;
standalone ContentItems use event time descending, then ID. Results report the effective range and
whether history, Stories, members, observations, items, citations, context, or tool calls were
truncated. Items represented by any selected Story member are not repeated as standalone results.

Citations are immutable snapshots constructed from persisted Story, ContentItem, and observation
IDs. A model response may refer only to citation refs supplied during that turn. Unknown refs are
removed before persistence and mark the answer degraded. Without Gemini, or when Gemini fails, the
service returns a bounded deterministic answer from the same local evidence and stores a complete
turn.

The local tool set is `search_stories`, `search_content_items`, and `get_story_evidence`. Tool
schemas are closed and immutable; names, permissions, argument types/ranges, enabled flags, result
size, duplicate calls, and the three-call limit are enforced before dispatch. Feishu adapts
inward to this core. Phase 6 additionally registers the opt-in `research_external`
tool, routed through a bounded `ResearchGateway`; see [research.md](research.md)
for its five allowlisted capabilities. It cannot expose arbitrary files, shell,
dynamic imports, crawler triggers, MCP dispatch or unregistered network tools.

`INTELLIGENCE_ASSISTANT_ENABLED=false` disables only the Assistant. The other
`INTELLIGENCE_ASSISTANT_*` variables in `.env.example` override bounded operational limits. Set
`GEMINI_ENABLED=false` or omit `GEMINI_API_KEY` to retain deterministic local answers without model
synthesis. `INTELLIGENCE_ENABLED=false` remains the complete rollback for unified storage, Story,
Security, and Assistant processing; legacy databases, reports and MCP remain available.
Lark Story delivery requires unified storage; retired notification channels are not restored.

## Lark Assistant

For live debugging, follow the [Phase 5 acceptance runbook](phase5-live-acceptance.md) and
record outcomes separately from the existing offline verification.

Phase 5 adds an opt-in official-SDK WebSocket transport for Lark international under the
compatibility package `trendradar/integrations/feishu/`, with a public entrypoint at
`trendradar/integrations/lark/`. Existing crawler, AI Frontier and MCP do not start
the bot. Lark is the sole notification transport. Install dependencies from `requirements.lock`; the
SDK is pinned to `lark-oapi==1.7.3` because the isolated lifecycle bridge uses its
internal connect/disconnect hooks. No inbound public HTTP port is required.

Inject `LARK_APP_ID` and `LARK_APP_SECRET` through the process environment.
Configure `LARK_IDENTITY_FIELDS` as JSON, for example
`{"open_id":["your-open-id"],"union_id":["your-union-id"]}`. Supported identity
fields are `open_id`, `user_id`, and `union_id`, not display names. Empty or invalid
identity configuration denies access. The legacy comma-separated
`LARK_ALLOWED_USERS` remains an `open_id` fallback; a non-empty environment value
overrides YAML. Credential values are never accepted from YAML.

Enable `LARK_ENABLED=true`. Default chat modes are `p2p,group`; group messages
require an explicit mention matching `LARK_BOT_ID` (the bot's open ID). Set
`LARK_ALLOWED_CHAT_TYPES=p2p` for private-only use. In the Lark developer
console, enable bot capability and long-connection event subscriptions for
`im.message.receive_v1`, grant the appropriate private/group message receipt,
bot-send and message-resource permissions, publish the app, and add the bot to
the target conversation. Actual permission labels and tenant approval are
provider-console concerns. The [live UAT record](../.planning/phases/05-feishu-assistant/05-LIVE-UAT.md)
separates confirmed Windows tenant behavior from the skipped and pending scenarios.

```powershell
python -m trendradar.integrations.lark --check
python -m trendradar.integrations.lark
```

`--check` validates settings without opening SQLite or connecting to Lark.
Optional `--config PATH` uses the same explicit-path/environment/YAML precedence
as existing entrypoints. Local `.env` files must be injected by the launcher;
the runner does not load them automatically.

Text, image-only and mixed rich-text posts route to the existing Assistant.
Image limits are four images, 4 MiB per image and 8 MiB per request; only bounded
Lark message resources are downloaded, and image bytes are not persisted.
The 32-entry worker queue keeps SDK callbacks short. Existing local tool
allowlists, citations and deterministic Gemini fallback remain authoritative.

Schema v4 adds `feishu_events`; v5 adds `feishu_deliveries`; v6 adds bounded prepared
event payloads and delivery-attempt tracking for restart recovery. These are forward-only
additions to `intelligence.db`, not changes to legacy news/RSS/AI schemas.
Completed event IDs are treated as already delivered, including across restarts:
the duplicate is acknowledged locally without another Lark send or Assistant
turn. Prepared events are persisted before entering the worker queue, and failed
provider deliveries retry the saved reply without another Assistant turn.
Processing duplicates receive a short status reply; leases, owner fencing and at
most three processing or delivery attempts bound recovery.
Reconnect defaults are five consecutive failures then a 300-second cooldown;
only a connection stable for 60 seconds resets the failure streak.

Enable `LARK_DELIVERY_ENABLED=true` and set `LARK_DELIVERY_TARGET` to a chat ID
for daily Story delivery. `LARK_DELIVERY_TIME` / `LARK_DELIVERY_END` override
the existing `notification.push_window.start/end`; defaults cover 00:00-23:59.
The worker checks every 60 seconds, using `Asia/Shanghai`, after any in-flight
Assistant turn. Ranked Stories, Importance, source links and optional digest
follow the existing Story report baseline. Empty output remains retryable.
Successful windows are keyed by target, local date and configured window;
partial failures resume persisted chunks with stable SDK send UUIDs.

Local completion is durable, but an external service accepting a request just
before a process crash is not an atomic transaction with SQLite. Gemini calls
with no saved response and Lark sends outside its UUID deduplication lifetime
can still repeat after that narrow uncertain-outcome window. Live evidence is
recorded separately; offline tests cannot establish credential or delivery acceptance.

Rollback: `LARK_ENABLED=false` disables only this runner;
`INTELLIGENCE_ENABLED=false` also disables it and preserves the legacy acquisition
path. No commit, push, deployment or runtime database migration is performed by
the test suite. Back up the database before enabling a new schema in production.

## Historical Backfill

Backfill is explicit, inclusive of both dates, and idempotent:

```powershell
python -m trendradar.intelligence.backfill --from 2026-08-01 --to 2026-08-31
python -m trendradar.intelligence.backfill --from 2026-08-01 --to 2026-08-31 --include news,rss
python -m trendradar.intelligence.backfill --from 2026-08-01 --to 2026-08-31 --dry-run
```

Valid include values are `news`, `rss`, and `ai`. Dry runs use in-memory SQLite and create no target
database. Missing databases are ignored; corrupt legacy databases are logged and skipped. Back up
runtime data before any future schema migration. When Story intelligence is enabled, backfill also
derives Stories from each chronological canonical batch without fetching upstream data; reruns add
no duplicate Story or membership rows.
