# TrendRadarpoi

A personal intelligence assistant collecting news, RSS, AI and security sources. Content is deduplicated into Stories with retained evidence, searchable local history, HTML reports and Lark text/image conversations.

[中文](README.md) | [Documentation](docs/README.md) | [Deployment](docs/deployment.md)

[Configuration and keyword rules](docs/configuration.md) | [MCP client setup](docs/mcp-setup.md) (bilingual guides)

## Run Locally

Python 3.10+ is supported; production uses a separate Python 3.12 virtual environment.

```bash
python -m pip install -r requirements.lock
python -m trendradar
python -m trendradar.ai_frontier
python -m mcp_server.server --transport stdio
python -m trendradar.integrations.lark --check
```

The unified store is `output/intelligence.db`. Existing news/RSS date databases and `output/ai_frontier.db` remain available to reports and MCP. Explicitly migrate production databases before starting services. Production starts with new databases, without importing UAT fixtures.

## Models

All Google calls share environment-only `GEMINI_API_KEY`. Inference tries `gemini-3.8-flash`, `gemini-3.5-flash-lite`, then `gemini-3.1-flash-lite`. `GEMINI_MODELS` accepts an ordered comma-separated list, ahead of legacy `GEMINI_MODEL` and YAML settings. Each request attempts a candidate once, with at most three attempts. Model failures trigger immediate failover and a default 60-second cooldown; shared authentication errors stop immediately. Exhaustion returns the existing deterministic local-evidence response.

Translation uses a separate fixed `gemma-4-31b-it` profile with the same API key. It never inherits inference models or uses anonymous providers. Failed translations retain original text.

## Lark Delivery

Use the environment-only credentials and identity settings in [.env.example](.env.example). Lark is disabled by default. Authorized direct messages and group mentions support text and images; completed duplicate events do not receive another reply.

Production uses `LARK_DELIVERY_MODE=instant`, with daily delivery disabled. The Scheduler checks every 60 seconds, queues newly persisted Stories and processes at most 20 per batch. Overflow stays queued. Saved payloads, leases and chunk checkpoints survive retries and restarts. Collection frequency is unchanged; collectors generate reports without sending notifications. Maintenance guards suspend delivery.

## Operations

The systemd deployment retains a fixed trusted installer, transaction journals, `PrivateTmp` and `ProtectHome`. Initial shared limits are `MemoryHigh=512M`, `MemoryMax=768M`, `CPUQuota=50%`; collectors run serially.

Hourly SQLite snapshots cover unified, AI Frontier and date-partitioned news/RSS stores. Managed retention preserves 24 hourly, 7 daily and 4 weekly snapshots. This deployment uses local backups only (`TRENDRADAR_OFFSITE_ENABLED=false`); offsite recovery remains unaccepted. GitHub collection workflows are manual diagnostics; VPS timers own production scheduling.

```bash
python -m pytest tests -q
python -m ruff check <changed-python-paths>
python -m trendradar.ops health --readiness --json
```

Track implementation in [07-06-PLAN.md](.planning/phases/07-deployment/07-06-PLAN.md). Offline verification, live VPS acceptance and at least 48 hours of observation are separate gates. Historical evidence is preserved in the [handoff](docs/phase7-actual-gap-evidence/HANDOFF.md).

## Attribution

Based on [sansan0/TrendRadar](https://github.com/sansan0/TrendRadar), licensed under [GPL-3.0](LICENSE). Some AI Frontier default Podcast, Blog and X sources follow [follow-builders](https://github.com/zarazhangrui/follow-builders).
