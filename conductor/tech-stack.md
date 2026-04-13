# TrendRadar — Tech Stack

## Language & Runtime

- **Python** >=3.10
- **Build**: hatchling (pyproject.toml)

## Core Dependencies

| Package | Version | Purpose |
|---------|---------|----------|
| requests | >=2.32.5,<3.0.0 | HTTP requests (trending APIs + RSS fallback) |
| feedparser | >=6.0.0,<7.0.0 | RSS/Atom parsing |
| PyYAML | >=6.0.3,<7.0.0 | Config file parsing |
| pytz | >=2025.2,<2026.0 | Timezone handling |
| boto3 | >=1.35.0,<2.0.0 | S3-compatible remote storage (R2/OSS/COS) |
| fastmcp | >=2.12.0,<2.14.0 | MCP Server framework |
| websockets | >=13.0,<14.0 | MCP WebSocket communication |

## Translation Service

- **Engine**: Google Gemini API
- **Wrapper**: `trendradar/services/translation_service.py` → `TranslationService`
- **Backend**: `mcp_server/tools/translation.py` → `TranslationTools`
- **API Key**: Environment variable `GEMINI_API_KEY`
- **Capability**: Auto-translate EN→ZH titles and summaries; degrades to monolingual without API key

## Storage

- **Primary**: SQLite (date-partitioned files under `output/YYYY-MM-DD/`)
  - `news_data.db` — Trending news data
  - `rss_data.db` — RSS feed data
- **Remote** (optional): S3-compatible (Cloudflare R2 / Alibaba OSS / Tencent COS)
- **Rotation**: `cleanup_old_data()` removes expired data per `retention_days`
- **Output formats**: SQLite (required), HTML report (optional), TXT snapshot (optional)

## Deployment

### GitHub Actions (currently used)

- **Workflow**: `.github/workflows/crawler.yml`
- **Schedule**: cron `30 * * * *` (minute 30 every hour)
- **Persistence**: `actions/cache@v4` caches `output/` directory (enables incremental mode across runs)
- **Env vars**: `GEMINI_API_KEY`, `BARK_URL` injected via GitHub Secrets

### Docker (optional)

- Dockerfile + docker-compose provided
- Suitable for long-running, precision-scheduled scenarios

## Configuration

- **Main config**: `config/config.yaml` (400 lines, covers all settings)
- **Keywords**: `config/frequency_words.txt` (regex word group syntax)

## MCP Server

- **Entry**: `mcp_server/server.py`
- **Protocol**: MCP (Model Context Protocol)
- **Command**: `trendradar-mcp`
