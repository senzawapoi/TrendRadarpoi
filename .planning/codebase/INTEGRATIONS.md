# External Integrations

**Analysis Date:** 2026-10-23

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

**Translation:**
- `gemini-3.1-flash-lite` uses the shared key with an independent profile in
  `trendradar/ai/translator.py`. Failure retains original text; anonymous fallbacks
  and Gemma fallback are removed. MCP delegates to the same core service.
- Inference defaults to 3.8 Flash, 3.5 Flash Lite, then 3.1 Flash Lite; translation
  does not inherit that list. Canonical title resolution precedes Story publication.

**Feishu application bot:**
- Opt-in official `lark-oapi==1.7.3` WebSocket transport under `trendradar/integrations/feishu/`.
- Receives private messages and explicitly mentioned group messages; adapts text/image inputs to
  the local Assistant and sends replies and instant/optional daily Stories through SDK APIs.
- Identity/chat authorization precedes payload parsing, resource downloads, and Gemini calls.
- Setup, environment fields and offline/live limits: [Lark guide](../../docs/intelligence.md#lark-assistant).

## Data Storage

**Databases:**
- SQLite files under `output/news/YYYY-MM-DD.db` and `output/rss/YYYY-MM-DD.db` store hot-list and RSS history using `trendradar/storage/local.py`.
- `output/ai_frontier.db` stores AI Frontier items independently through `trendradar/ai_frontier/storage.py`.
- `output/intelligence.db` schema version 7 stores canonical items/observations/source runs,
  clusters/Stories/memberships, principal-scoped Assistant sessions/messages, and Feishu
  event/reply, daily-delivery and instant-delivery ledgers.
- The three legacy stores remain authoritative for current reports, notifications, and MCP;
  unified Story, Security, and Assistant views are additive.

**File Storage:**
- Local filesystem holds SQLite, TXT snapshots, and generated HTML under ignored `output/`.
- Optional S3-compatible remote storage uses `boto3` in `trendradar/storage/remote.py` with endpoint, bucket, region, and credentials from environment/configuration.
- Unified `intelligence.db` remains local-only and is not synchronized by the S3 backend.

**Caching:**
- Manual GitHub diagnostics may cache output; production data persists on the VPS with local snapshots.
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
- VPS timers own scheduled crawler and AI Frontier jobs, with serial collection.
- Docker images provide crawler/supercronic and MCP server deployment options.
- Local Assistant, opt-in Lark transport and ResearchGateway are implemented.
  Recorded VPS deployment and remaining acceptance are in the [current handoff](../../docs/phase7-release-20261023/HANDOFF.md).

**CI Pipeline:**
- `.github/workflows/crawler.yml` and `ai-frontier.yml` are manual diagnostics.
- `.github/workflows/docker.yml` builds and pushes release images.
- Phase 7 workflows run pytest, scoped Ruff, build/install checks and guarded deployment.
  Privileged Linux coverage and exact artifact evidence remain separate release gates.

## Environment Configuration

**Required env vars:**
- None for default public-source collection; enable only integrations whose credentials are configured.
- `GEMINI_API_KEY` for Gemini-backed translation/analysis.
- Optional `NVD_API_KEY` for higher NVD limits; it is environment-only.
- `LARK_APP_ID` and `LARK_APP_SECRET` are environment-only international app credentials.
  Enabling the bot requires configured identities; group use requires `LARK_BOT_ID`.
  Existing `FEISHU_*` aliases remain compatible. See the Lark guide.
- `S3_ENDPOINT_URL`, `S3_BUCKET_NAME`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, and `S3_REGION` for remote storage.

**Unified intelligence overrides:**
- `INTELLIGENCE_ENABLED` overrides `intelligence.enabled`; `false` restores legacy acquisition.
- `INTELLIGENCE_DB_PATH` overrides `intelligence.database_path` and defaults to `output/intelligence.db`.
- `GEMINI_ENABLED`, `INTELLIGENCE_STORY_ENABLED`, `INTELLIGENCE_SECURITY_ENABLED`, and
  `INTELLIGENCE_ASSISTANT_ENABLED` disable their narrower optional layers.
- `LARK_ENABLED=false` disables the separate bot runner; `LARK_DELIVERY_ENABLED` independently
  controls delivery, with `LARK_DELIVERY_MODE=instant` in production. Legacy webhook senders are removed.
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
- Lark SDK bot replies and durable Story delivery use `trendradar/integrations/feishu/`
  behind the international `trendradar.integrations.lark` entrypoint. No other notification sender remains.

---

*Integration map reconciled 2026-10-23; external availability is not rechecked by documentation cleanup.*
