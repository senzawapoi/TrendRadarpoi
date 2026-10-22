# Coding Conventions

**Analysis Date:** 2026-09-12

## Naming Patterns

**Files:**
- Use lowercase snake case for Python modules: `translation_service.py`, `github_trending.py`.
- Name executable package entry points `__main__.py`.

**Functions:**
- Use `snake_case`; prefix non-public helpers with `_`, such as `_deep_merge()` and `_row_to_item()`.
- Async I/O functions use `async def` without an `async_` name prefix.

**Variables:**
- Use descriptive snake case; uppercase constants hold defaults and provider limits.
- Configuration dictionaries commonly use `*_cfg` or `*_config` suffixes.

**Types:**
- Use PascalCase for classes and dataclasses: `AppContext`, `StorageManager`, `AIItem`, `RSSFetcher`.
- Source implementations end in `Source`; service/facade types end in `Service`, `Tools`, `Manager`, or `Dispatcher`.

## Code Style

**Formatting:**
- No formatter is configured. Preserve local layout and avoid whole-file formatting in legacy modules.
- Newer modules use four spaces, double-quoted strings, trailing commas, and line wrapping near 100 columns.
- Older MCP modules use mixed quote styles and whitespace; treat Ruff output as existing debt, not a reason for unrelated rewrites.

**Linting:**
- Ruff configuration is in `pyproject.toml`, targeting Python 3.10 with line length 100.
- Enabled families include E/W/F/I/UP/B/C4/SIM/RUF; CJK ambiguous-character checks and E501 are intentionally ignored.
- Full-repository Ruff has legacy violations; narrow changed-file checks are the practical baseline
  until a dedicated cleanup is planned. Do not treat historical counts as current measurements.

## Import Organization

**Order:**
1. `from __future__ import annotations` when modern annotations are used.
2. Python standard library.
3. Third-party dependencies.
4. Absolute project imports from `trendradar` or `mcp_server`.

**Path Aliases:**
- None. Use absolute package imports for cross-package references and relative imports within MCP subpackages where already established.

## Error Handling

**Patterns:**
- Prefer typed exceptions from `trendradar/core/exceptions.py` for core boundaries.
- Preserve partial results for batch/network operations; AI Frontier isolates individual source failures.
- Retry transient I/O with bounded attempts, timeout, and contextual logs.
- Do not introduce bare `except` or broad exception swallowing; legacy code contains both and should be narrowed during touched-module refactors.
- Chain translated exceptions with `raise ... from exc`.

## Logging

**Framework:** structlog through the module singleton `trendradar.utils.logging.log`.

**Patterns:**
- Log lifecycle events at info/success, recoverable source/provider failures at warning, and terminal failures at error/exception.
- Include structured fields such as source name, status, count, and error text rather than interpolating all context into the message.
- Never log API keys, webhook URLs, tokens, headers, or raw secret-bearing configuration.
- MCP still uses `print`; new shared services should use the core logger and let interfaces format responses separately.

## Comments

**When to Comment:**
- Use concise Chinese docstrings for public classes/functions where that is the surrounding style.
- Explain provider quirks, compatibility logic, or non-obvious fallback behavior; do not narrate assignments.
- Section dividers are used in large orchestrators and provider adapters, but new modules should remain small enough not to need many.

**Docstrings:**
- Triple-quoted module, class, and function docstrings are common.
- Public methods often document Args/Returns; type hints still define the authoritative interface.

## Function Design

**Size:**
- Keep source parsing and network acquisition separate, following `_parse_*` plus `fetch()` patterns in `trendradar/ai_frontier/sources/`.
- Keep new composition roots thin; avoid extending the large `trendradar/__main__.py` or MCP tool methods with more policy.

**Parameters:**
- Use explicit type hints and `T | None` for optional values on Python 3.10+.
- Accept configuration dictionaries at external boundaries but convert to typed domain objects before shared pipeline logic.

**Return Values:**
- Return domain objects from core services; use dictionaries only at configuration, serialization, and MCP response boundaries.
- For partial batches, prefer `BatchResult` or explicit `(successes, failures)` data over boolean-only outcomes.

## Module Design

**Exports:**
- Keep implementation in focused modules and expose stable package APIs through `__init__.py` only when callers benefit.
- Interface layers may import core/application services; core/application modules must not import
  `mcp_server` or Feishu transport modules.

**Barrel Files:**
- Python package `__init__.py` files exist but are lightweight; avoid broad wildcard exports.

---

*Convention analysis: 2026-09-12*
