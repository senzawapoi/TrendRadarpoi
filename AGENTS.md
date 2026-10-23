# Repository Guidelines

## Project Structure & Module Organization

`trendradar/` is the main package. `core/models/` defines canonical content; `sources/` wraps collectors; `intelligence/` owns adapters, Stories, SQLite, and backfill. `ai/` owns Gemini/Assistant; `domains/security/` owns security intelligence; `integrations/feishu/` owns the opt-in bot. Legacy output remains in `storage/` and `report/`; Lark is the only notification transport. `ai_frontier/` provides seven-source collection; `mcp_server/` exposes FastMCP. Tests mirror subsystems under `tests/`, including `baseline/`, `deployment/` and `integrations/feishu/`. Configuration lives in `config/`; VPS deployment files in `deploy/`, `scripts/deploy/` and `.github/workflows/`, with legacy containers in `docker/`. Preserve `output/` as runtime state.

## Build, Test, and Development Commands

Run commands from the repository root:

```powershell
python -m pip install -r requirements.txt      # Install dependencies
python -m trendradar                           # Run the main pipeline
python -m trendradar.ai_frontier               # Run AI Frontier
python -m mcp_server.server --transport stdio  # Start the MCP server
python -m trendradar.integrations.lark --check  # Validate settings offline
python -m trendradar.intelligence.backfill --from 2026-08-01 --to 2026-08-31 --dry-run
python -m pytest tests -q                      # Run all tests
python -m ruff check <changed-python-paths>     # Lint changed Python files
```

Install undeclared dev tools with `python -m pip install pytest ruff`. Keep changed files clean; full-tree Ruff has legacy debt.

## Coding Style & Naming Conventions

Target Python 3.10+, four-space indentation, type hints, and 100 columns. Use `snake_case` for modules/functions, `PascalCase` for classes, and `UPPER_CASE` for constants. Separate fetching from parsing/normalization. Core services must not depend on MCP or Feishu transports; interfaces depend inward.

## Testing Guidelines

Use pytest with `test_<module>.py` and `test_<behavior>()`. Mock HTTP, providers, environment, and time; use `tmp_path` for SQLite. Behavior changes need focused tests and a full run. Exercise adapters and `INTELLIGENCE_ENABLED=false` rollback. Preserve Feishu authorization, completed-event suppression, saved-reply delivery retry, media, and reconnect bounds; offline tests do not validate live tenants.

## Commit & Pull Request Guidelines

Use Conventional Commits: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`, optionally scoped, such as `feat(ai_frontier):`. Describe behavior, configuration/schema impact, migration/rollback, and verification in PRs. Link issues; add screenshots for rendered-output changes.

## Security & Configuration

Never commit credentials, webhook URLs, `.env`, or databases. Gemini and Lark app credentials are environment-only. Use `LARK_*` for the international bot; legacy `FEISHU_*` aliases remain supported. `LARK_ENABLED` defaults false; authorize before parsing content or fetching media. `INTELLIGENCE_DB_PATH` defaults to `output/intelligence.db`; failures must not interrupt legacy outputs or refetch upstream. Test migrations on temporary databases.

## Agent-Specific Instructions

Read `.planning/PROJECT.md`, relevant `.planning/codebase/` files, and `docs/intelligence.md` before architectural work. [Documentation navigation](docs/README.md) and `.planning/STATE.md` guide handoff. Preserve user changes; never commit or deploy without explicit instruction.

For Phase 7, follow [07-06 plan](.planning/phases/07-deployment/07-06-PLAN.md); the [actual-gap handoff](docs/phase7-actual-gap-evidence/HANDOFF.md) preserves earlier evidence. Keep audit archives and the isolated Linux toolchain until verification closes. Use the fixed installer and trusted `common.env`; never remove pending transaction records to bypass maintenance. Preserve `PrivateTmp` and place service interpreters outside temporary directories.

During Windows UAT, follow [test/README.md](test/README.md). Preserve `test/runtime/`, including SQLite WAL/SHM, fixtures and logs. Verify `lark-live.json` against the live process; never start a second bot or reset the sandbox while testing. Local acceptance is not Linux VPS deployment. This release uses Python 3.12, instant Lark delivery and local backups only; offsite recovery and 48-hour observation remain separate gates.
