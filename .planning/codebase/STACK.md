# Technology Stack

**Analysis Date:** 2026-10-23 (deployment and dependency reconciliation)

## Languages

**Primary:**
- Python 3.10+ - crawler, storage, analysis, notifications, AI Frontier, and MCP server under `trendradar/` and `mcp_server/`.

**Secondary:**
- SQL (SQLite dialect) - schemas in `trendradar/storage/schema.sql` and `trendradar/storage/rss_schema.sql`.
- YAML - runtime configuration in `config/config.yaml`, Docker Compose, and GitHub Actions workflows.
- Shell and batch scripts - Docker entrypoint and setup/start scripts in `docker/`, `setup-*.sh`, and `setup-*.bat`.
- HTML/CSS/JavaScript - generated reports in `trendradar/report/` and the checked-in `index.html` example.

## Runtime

**Environment:**
- CPython 3.10 or newer, declared in `pyproject.toml`.
- Linux VPS uses Python 3.12; Windows setup scripts support local development and isolated UAT.

**Package Manager:**
- pip with `requirements.txt` for CI and Docker installs.
- Hatchling 1.32.4 builds the package from `pyproject.toml`.
- `requirements.lock` pins the runtime graph used by Phase 7 installer/CI.
- `build-requirements.lock` pins pip/Hatchling and resolved build dependencies;
  install the application with `--no-build-isolation --no-deps` after both locks.
  The recorded deployed commit has empty Python 3.12 archive-install and CI evidence;
  the uncommitted title repair needs its own frozen verification. See the
  [current handoff](../../docs/phase7-release-20261023/HANDOFF.md).

## Frameworks

**Core:**
- FastMCP 2.12-2.13 - stdio/HTTP MCP server in `mcp_server/server.py`.
- aiohttp 3.9+ - asynchronous RSS and AI Frontier HTTP clients.
- requests 2.32+ - synchronous crawler, notifications, and MCP-side network calls.
- feedparser 6.x - RSS/Atom parsing for core RSS and several AI Frontier adapters.

**Testing:**
- pytest - function-style tests under `tests/ai/`, `tests/ai_frontier/`, `tests/intelligence/`,
  `tests/integrations/feishu/`, and `tests/baseline/`; not declared in project dependencies.

**Build/Dev:**
- Ruff - lint rules in `pyproject.toml`, target Python 3.10 and line length 100; the executable is not declared as a dev dependency.
- mypy 1.x - configured and declared in the `dev` dependency group, but no CI type-check step is present.
- Docker Buildx - multi-architecture images from `docker/Dockerfile` and `docker/Dockerfile.mcp`.

## Key Dependencies

**Critical:**
- PyYAML 6.x - loads `config/config.yaml` through `trendradar/core/loader.py`.
- boto3 1.x - optional S3-compatible storage in `trendradar/storage/remote.py`.
- google-genai 1.x - lazily used by the provider-neutral core client in `trendradar/ai/client.py`.
- lark-oapi 1.7.3 - pinned official Feishu SDK; the isolated lifecycle/resource bridge uses private
  hooks that must be revalidated before upgrades.
- beautifulsoup4 4.12+ - GitHub Trending and official blog HTML extraction.
- structlog 24.x - structured application logging in `trendradar/utils/logging.py`.
- tenacity 8.x - retry policy in RSS network paths; Gemini candidate attempts are bounded by
  the core client, with SDK implicit retries disabled.

**Infrastructure:**
- SQLite from the Python standard library - date-partitioned news/RSS stores,
  schema-v1 `output/ai_frontier.db`, and schema-v7 `output/intelligence.db` for canonical, Story, Session,
  and Feishu event/delivery data.
- supercronic - cron process used by the crawler Docker image through `docker/entrypoint.sh`.
- GitHub Actions cache/artifacts - diagnostics/report retention and release artifacts; VPS snapshots protect production SQLite.

## Configuration

**Environment:**
- Main runtime behavior is defined in `config/config.yaml` and normalized by `trendradar/core/loader.py`.
- Secrets and deployment overrides are supplied through environment variables; `.env*` is ignored by `.gitignore`.
- Source lists and thresholds for AI Frontier live under `ai_frontier` in `config/config.yaml`.

**Build:**
- `pyproject.toml` defines package metadata, console scripts, Hatchling, Ruff, and mypy.
- `requirements.txt` remains the general/Docker installation manifest; Phase 7 CI and installer use `requirements.lock`.
- `version` reports 4.7.0 while `pyproject.toml` reports 4.6.0; release metadata is not single-sourced.

## Platform Requirements

**Development:**
- Python 3.10+, network access for public feeds/APIs, and writable `output/` for SQLite/report state.
- Run from repository root because several modules resolve `config/` and `output/` with relative paths.

**Production:**
- VPS systemd timers own scheduled batch crawling; GitHub collection is manual diagnostics. Legacy Docker remains available.
- Security, local Assistant and ResearchGateway are implemented and offline-tested.
  Windows and VPS have separate live evidence. Title-repair release validation,
  Chinese-title receipt, source health and 48-hour observation remain open;
  backups are local-only and offsite recovery is unaccepted.

---

*Stack reconciled: 2026-10-23; live service state not rechecked.*
