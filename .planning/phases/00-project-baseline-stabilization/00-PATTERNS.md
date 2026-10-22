# Phase 0 Pattern Map

## Settings and YAML

| New/changed file | Closest existing analog | Pattern to preserve |
|------------------|-------------------------|---------------------|
| `trendradar/core/settings.py` | `trendradar/core/loader.py` | UTF-8 YAML, env-over-YAML precedence, Python 3.10 types |
| `config/settings.py` | package facade modules | Explicit imports and `__all__`; no business logic |
| `trendradar/ai_frontier/__main__.py` | `load_ai_frontier_config()` | Deep merge onto defaults and graceful invalid-file fallback |
| MCP config readers | `ParserService.parse_yaml_config()` | Preserve `FileParseError` or current empty fallback per caller |

Canonical dependency direction:

```text
entrypoints / MCP interface
          |
          v
trendradar.core.settings
          |
          v
  pathlib + os + PyYAML
```

`trendradar.core.settings` must never import `mcp_server` or application entrypoints.

## Tests

- Use pytest functions named `test_<behavior>`.
- Use `monkeypatch` for environment variables and `tmp_path` for YAML/SQLite.
- Test parsers and SQLite against real local data structures; mock only network/provider boundaries.
- Preserve the AI Frontier factory style used under `tests/ai_frontier/`.

## Documentation

- Repository docs are concise Markdown with concrete file paths and PowerShell-compatible commands.
- Mermaid is acceptable for the architecture diagram because it remains readable as text in GitHub.
- Do not include the revoked credential value, webhook URLs, cookies, or generated database contents.

## Landmines

- `.gitignore` currently ignores `.env.example` through `.env*`; add `!.env.example` after env rules.
- `config/` is not included in Hatch's package list; the canonical implementation cannot live only there.
- Main storage is date-partitioned; `DATABASE_PATH` must not silently replace existing paths in Phase 0.
- AI Frontier source files have unrelated uncommitted edits and must remain untouched.
