# Codebase Structure

**Analysis Date:** 2026-10-23 (workspace topology reconciliation)

## Directory Layout

```text
TrendRadarpoi-master/
├── trendradar/                 # Main Python package
│   ├── core/                   # Configuration, analysis, domain errors
│   ├── crawler/                # Hot-list and RSS acquisition
│   ├── sources/                # Unified adapters over existing collectors
│   ├── intelligence/           # Canonical/Story pipeline, SQLite, projection, backfill
│   ├── ai/                     # Gemini, translation/analysis, local Assistant and tools
│   ├── integrations/feishu/    # Opt-in SDK transport, authorization, deduplication and delivery
│   ├── integrations/lark/      # International Lark entrypoint over the compatible implementation
│   ├── research/               # Optional bounded ResearchGateway and Agent-Reach routes
│   ├── ops/                    # Database checks, health, maintenance and backup/recovery
│   ├── domains/security/       # Security collection, analysis, ranking, and report
│   ├── storage/                # SQLite/local/S3 persistence
│   ├── services/               # Application services, currently translation
│   ├── report/                 # HTML/report generation
│   ├── ai_frontier/            # Independent AI-source subsystem
│   └── utils/                  # Time, URL, and logging helpers
├── mcp_server/                 # FastMCP interface, services, tools, validators
├── tests/                      # AI, AI Frontier, intelligence, Feishu and baseline tests
├── docs/README.md              # Task-oriented documentation navigation
├── docs/intelligence.md        # Intelligence, Assistant, Feishu and rollback guide
├── config/                     # Tracked runtime and feed configuration
├── .github/workflows/          # CI/release, manual crawl diagnostics and image builds
├── docker/                     # Container images, compose, and process scripts
├── deploy/                     # Linux systemd units, environment templates and fixed installer entry
├── scripts/deploy/             # Release, trusted environment loader, preflight and offsite helpers
├── test/                       # Windows UAT sandbox; runtime evidence must be retained
├── conductor/                  # Historical pre-v5 product/architecture snapshot
├── output/                     # Generated SQLite and reports; gitignored
└── pyproject.toml              # Package, scripts, Ruff, and mypy configuration
```

## Directory Purposes

**`trendradar/`:**
- Purpose: production crawler and reporting application.
- Contains: composition roots, collectors, canonical models/adapters, storage, analysis, notification, and AI Frontier.
- Key files: `trendradar/__main__.py`, `trendradar/context.py`, `trendradar/ai_frontier/__main__.py`.

**`trendradar/core/models/`, `trendradar/sources/`, and `trendradar/intelligence/`:**
- Purpose: normalize all existing sources to `ContentItem`, retain provenance, build/rank Stories, and project records back to legacy contracts.
- Contains: compatibility conversions, adapters, bounded runner, deduplication, schema-v7 SQLite,
  Story processing, translation propagation, Assistant/Feishu persistence, and explicit backfill.
- Key files: `trendradar/core/models/content.py`, `trendradar/sources/base.py`, `trendradar/intelligence/storage.py`.

**`trendradar/ai/` and `trendradar/domains/security/`:**
- Purpose: provide the shared Gemini/local Assistant boundary and the bounded Security domain.
- Contains: provider DTO/errors, translation/narrative adapters, Session/retrieval/citations/tools,
  CISA/NVD/RSS collection, deterministic analysis, freshness, and reporting.
- Key files: `trendradar/ai/client.py`, `trendradar/ai/assistant.py`,
  `trendradar/domains/security/collector.py`.

**`mcp_server/`:**
- Purpose: expose stored intelligence and operational tools over MCP.
- Contains: FastMCP registration, parsing/data services, analytics, search, storage sync, system, and translation tools.
- Key files: `mcp_server/server.py`, `mcp_server/services/`, `mcp_server/tools/`.

**`trendradar/integrations/feishu/`:**
- Purpose: adapt official SDK events to the existing local Assistant without widening its tools.
- Contains: identity/chat validation, bounded media, event deduplication, SDK lifecycle, replies and daily delivery.
- Key files: `__main__.py`, `handler.py`, `client.py`, `ledger.py`, and `scheduler.py`.

**`tests/`:**
- Purpose: pytest test suite.
- Contains: Gemini/Assistant, AI Frontier, compatibility, intelligence, and Feishu offline coverage.
- Key files: `tests/ai/test_assistant_integration.py`, `tests/ai_frontier/test_fetcher.py`,
  `tests/baseline/test_storage_compatibility.py`, `tests/intelligence/test_integration.py`.

**`config/`:**
- Purpose: user-editable source, report, storage, and notification configuration.
- Contains: `config/config.yaml`, keyword rules, and backups.
- Treat credentials as environment-only even where configuration supports string fields.

**`conductor/`:**
- Purpose: preserve the pre-v5 product, architecture, decisions, and workflow snapshot.
- It is historical context; current authority is executable configuration, `docs/`, and GSD `.planning/`.

## Key File Locations

**Entry Points:**
- `trendradar/__main__.py`: main scheduled pipeline.
- `trendradar/ai_frontier/__main__.py`: AI Frontier pipeline.
- `mcp_server/server.py`: MCP stdio/HTTP service.
- `trendradar/integrations/feishu/__main__.py`: opt-in bot and daily scheduler; `--check` is offline.
- `docker/entrypoint.sh`: crawler container run-mode selection.

**Configuration:**
- `config/config.yaml`: runtime settings and source definitions.
- `config/frequency_words.txt`: keyword matching rules.
- `pyproject.toml`: build and static-analysis settings.
- `.github/workflows/*.yml`: CI/release and manual diagnostics; production collection uses VPS timers.

**Core Logic:**
- `trendradar/core/analyzer.py`: hot/RSS frequency and rank analysis.
- `trendradar/core/models/`: canonical content, normalization, and legacy conversion.
- `trendradar/sources/`: common adapters that reuse existing transports/parsers.
- `trendradar/intelligence/`: canonical persistence, deduplication, projections, and backfill.
- `trendradar/ai/`: shared Gemini, translation/analysis, Assistant, Session, retrieval, and tools.
- `trendradar/domains/security/`: Security collection, analysis, and report generation.
- `trendradar/storage/base.py`: core stored record dataclasses and backend contract.
- `trendradar/ai_frontier/sources/base.py`: AI Frontier item and source contract.
- `trendradar/integrations/feishu/instant.py`: durable instant Story delivery.

**Testing:**
- `tests/ai/test_*.py`: core Gemini, consumer, Session, retrieval, Assistant, and tool tests.
- `tests/ai_frontier/test_*.py`: function-style tests mirroring AI Frontier modules.
- `tests/integrations/feishu/test_*.py`: authorization, SDK, media, deduplication, reconnect and delivery.
- `tests/intelligence/test_*.py`: unified model/storage/adapter/deduplication, Story, Security,
  integration, report, and backfill tests.
- `tests/baseline/test_*.py`: offline entrypoint and legacy SQLite compatibility tests.
- `tests/ai/conftest.py` owns Assistant fixtures; no repository-level `conftest.py`, pytest
  configuration, or coverage gate exists.

## Naming Conventions

**Files:**
- Use lowercase `snake_case.py`, with `__main__.py` for executable modules and `__init__.py` for package boundaries.
- Test files use `test_<module>.py` under a mirrored subsystem directory.
- SQL schemas use descriptive lowercase names such as `rss_schema.sql`.

**Directories:**
- Use lowercase package names with underscores, such as `ai_frontier` and `mcp_server`.
- Keep generated output in `output/`; do not commit runtime databases or reports.

## Where to Add New Code

**Unified intelligence pipeline:**
- Domain contracts: extend `trendradar/core/models/` without breaking existing compatibility converters.
- Source compatibility adapters: add wrappers under `trendradar/sources/`; keep transport and parser ownership in existing collector modules.
- Pipeline orchestration and persistence: extend focused modules under `trendradar/intelligence/`; keep `__main__.py` files as composition roots.
- Tests: mirror changed behavior under `tests/intelligence/` and retain explicit legacy-path coverage.

**Gemini and assistant services:**
- Shared Gemini client, analysis/translation adapters, Assistant sessions, retrieval, citations,
  tools, and orchestration: `trendradar/ai/`.
- Keep legacy-compatible translation facade behavior in `trendradar/services/translation_service.py`.
- MCP wrappers should remain under `mcp_server/tools/` and import core services, never the reverse.

**Feishu bot:**
- Incoming WebSocket transport, identity checks, and reply orchestration belong in the
  `trendradar/integrations/feishu/` package.
- Lark is the only notification transport. Replies, instant posts and optional daily
  delivery use the compatible Feishu integration's SDK client and durable ledgers.

**Security intelligence and research:**
- Security collectors/analyzers/reports: `trendradar/domains/security/`, with source adapters in
  `trendradar/sources/security.py`.
- Future Agent-Reach access must sit behind a narrow `ResearchGateway`; do not place it in crawler
  source registration or expose its shell interface.

**Utilities:**
- Shared low-level helpers belong in `trendradar/utils/`; domain policy does not.

## Special Directories

**`output/`:**
- Purpose: runtime SQLite state, snapshots, and generated reports.
- Generated: Yes.
- Committed: No; excluded by `.gitignore`.

**`.planning/`:**
- Purpose: GSD project context, roadmap, state, phase plans, and codebase map.
- Generated: Yes, through GSD workflows.
- Committed: Controlled by `.planning/config.json`; initialization defaults currently favor tracked docs.

---

*Structure analysis: 2026-10-14*
