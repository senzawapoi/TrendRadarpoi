# External Integrations

**Analysis Date:** 2026-09-12

## APIs & External Services

**Trending and feeds:**
- NewsNow-compatible API - hot-list source for `trendradar/crawler/fetcher.py`; default endpoint is public and requires no configured credential.
- RSS/Atom and JSON Feed publishers - fetched and parsed by `trendradar/crawler/rss/`.
- ArXiv Atom, Reddit JSON, Hacker News Algolia, GitHub Trending HTML, Nitter RSS, YouTube video RSS, and official blog pages - adapters under `trendradar/ai_frontier/sources/`.
- CISA KEV JSON, NVD CVE API 2.0, and configured security RSS/Atom feeds - bounded adapters under
  `trendradar/sources/security.py` and `trendradar/domains/security/collector.py`.

**AI:**
- Google Gemini - the single provider boundary is `trendradar/ai/client.py`; translation, Story
  wording, digest, security narrative, Chat, and the MCP facade delegate inward to it.
  - SDK/client: lazy, injectable `google-genai` with provider-neutral results and sanitized errors.
  - Auth: `GEMINI_API_KEY` is environment-only; credential-looking YAML fields are discarded.
  - Missing, disabled, timed-out, rate-limited, or invalid provider responses use bounded
    deterministic degradation and do not interrupt collection or storage.

**Translation fallbacks:**
- Google Translate public endpoint and MyMemory - fixed-order anonymous fallbacks owned by
  `trendradar/ai/translator.py`; `mcp_server/tools/translation.py` is only a compatibility facade.

**Feishu application bot:**
- Opt-in official `lark-oapi==1.7.3` WebSocket transport under `trendradar/integrations/feishu/`.
- Receives private messages and explicitly mentioned group messages; adapts text/image inputs to
  the local Assistant and sends replies/daily Story digests through SDK APIs.
- Identity/chat authorization precedes payload parsing, resource downloads, and Gemini calls.
- Setup, environment fields and offline/live limits: [Feishu guide](../../docs/intelligence.md#feishu-assistant).

## Data Storage

**Databases:**
- SQLite files under `output/news/YYYY-MM-DD.db` and `output/rss/YYYY-MM-DD.db` store hot-list and RSS history using `trendradar/storage/local.py`.
- `output/ai_frontier.db` stores AI Frontier items independently through `trendradar/ai_frontier/storage.py`.
- `output/intelligence.db` schema version 6 stores canonical items/observations/source runs,
  clusters/Stories/memberships, principal-scoped Assistant sessions/messages, and Feishu
  event/reply and daily-delivery ledgers.
- The three legacy stores remain authoritative for current reports, notifications, and MCP;
  unified Story, Security, and Assistant views are additive.

**File Storage:**
- Local filesystem holds SQLite, TXT snapshots, and generated HTML under ignored `output/`.
- Optional S3-compatible remote storage uses `boto3` in `trendradar/storage/remote.py` with endpoint, bucket, region, and credentials from environment/configuration.
- Unified `intelligence.db` remains local-only and is not synchronized by the S3 backend.

**Caching:**
- GitHub Actions caches `output/` and `output/ai_frontier.db` between scheduled runs.
- MCP has an in-process cache singleton in `mcp_server/services/cache_service.py`.
- No external cache service is used.

## Authentication & Identity

**Auth Provider:**
- None for the crawler and MCP application itself.
- MCP supports stdio and HTTP transports but implements no application-level authentication in `mcp_server/server.py`.
- Local Assistant sessions are scoped by `principal_id`; Phase 5 maps configured Feishu identity
  fields and chat scope to stable hashed principals/sessions, denying unmatched users by default.

## Monitoring & Observability

**Error Tracking:**
- No external error tracking or metrics backend is configured.

**Logs:**
- `trendradar/utils/logging.py` provides structlog console logs with run and correlation IDs.
- MCP and older utilities still use direct `print`, so logging is not uniform.

## CI/CD & Deployment

**Hosting:**
- GitHub Actions runs scheduled crawler and AI Frontier jobs.
- Docker images provide crawler/supercronic and MCP server deployment options.
- Local Assistant and opt-in Feishu transport/daily scheduling are implemented and offline-tested.
  Agent-Reach gateway and VPS service deployment remain outside the completed Phase 1-5 scope.

**CI Pipeline:**
- `.github/workflows/crawler.yml` crawls hourly and restores cached output.
- `.github/workflows/ai-frontier.yml` crawls every two hours and uploads reports.
- `.github/workflows/docker.yml` builds and pushes release images.
- No workflow currently executes pytest, Ruff, mypy, migration checks, or secret scanning.

## Environment Configuration

**Required env vars:**
- None for default public-source collection; enable only integrations whose credentials are configured.
- `GEMINI_API_KEY` for Gemini-backed translation/analysis.
- Optional `NVD_API_KEY` for higher NVD limits; it is environment-only.
- `LARK_APP_ID` and `LARK_APP_SECRET` are environment-only international app credentials.
  Enabling the bot requires configured identities; group use requires `LARK_BOT_ID`.
  Existing `FEISHU_*` aliases remain compatible. See the Lark guide.
- Notification credentials such as `BARK_URL`, `FEISHU_WEBHOOK_URL`, Telegram, DingTalk, WeCom, email, ntfy, and Slack settings as channels are enabled.
- `S3_ENDPOINT_URL`, `S3_BUCKET_NAME`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, and `S3_REGION` for remote storage.

**Unified intelligence overrides:**
- `INTELLIGENCE_ENABLED` overrides `intelligence.enabled`; `false` restores legacy acquisition.
- `INTELLIGENCE_DB_PATH` overrides `intelligence.database_path` and defaults to `output/intelligence.db`.
- `GEMINI_ENABLED`, `INTELLIGENCE_STORY_ENABLED`, `INTELLIGENCE_SECURITY_ENABLED`, and
  `INTELLIGENCE_ASSISTANT_ENABLED` disable their narrower optional layers.
- `LARK_ENABLED=false` disables the separate bot runner; `LARK_DELIVERY_ENABLED` independently
  controls daily delivery within it. Neither changes legacy webhook notification settings.
- `INTELLIGENCE_RESEARCH_ENABLED=false` disables optional ResearchGateway routes;
  `INTELLIGENCE_RESEARCH_GITHUB_TOKEN` is their explicit isolated GitHub credential.
  See [research contracts](../../docs/research.md).

**Secrets location:**
- Use local `.env`, GitHub Secrets, or VPS secret injection; `.gitignore` excludes `.env*` and `output/`.
- No executable default Gemini credential remains; future active credentials belong only in secret injection.

## Webhooks & Callbacks

**Incoming:**
- The opt-in Feishu SDK consumes `im.message.receive_v1` events over an outbound WebSocket
  connection; no public HTTP callback port is required.

**Outgoing:**
- Feishu, DingTalk, WeCom, Slack, Bark, ntfy, Telegram, and email senders live in `trendradar/notification/senders.py` and `trendradar/notification/dispatcher.py`.
- Legacy Feishu webhook notifications coexist with SDK bot replies and durable daily delivery in
  `trendradar/integrations/feishu/`; configuring one does not start the other.

---

*Integration audit: 2026-09-12; configuration names reconciled 2026-10-14.*
