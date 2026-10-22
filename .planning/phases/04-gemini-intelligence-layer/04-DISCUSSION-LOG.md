# Phase 4: Gemini Intelligence Layer - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md; this log preserves the alternatives considered.

**Date:** 2026-09-04
**Phase:** 04-gemini-intelligence-layer
**Areas discussed:** Gemini ownership, compatibility, local retrieval, sessions, citations, tools

## Gemini Ownership

| Option | Description | Selected |
|--------|-------------|----------|
| Typed core client plus compatibility facades | One provider-neutral client; old public contracts delegate inward | Yes |
| Raw SDK wrapper | Return strings and let callers handle SDK/provider behavior | No |

**Basis:** The user required compatibility and instructed the implementation to follow the v5
documents. The documents require core services to own Gemini and forbid a core dependency on MCP.

## Translation Without A Gemini Key

| Option | Description | Selected |
|--------|-------------|----------|
| Preserve free-provider fallback | Gemini is skipped; existing MCP translation fallbacks remain | Yes |
| Disable all translation | No external translation occurs without `GEMINI_API_KEY` | No |

**Basis:** Compatibility was explicitly locked. The known repository Google key is already
revoked and is not treated as usable configuration.

## Assistant Persistence

| Option | Description | Selected |
|--------|-------------|----------|
| Versioned `intelligence.db` tables | One local backup and direct Story evidence access | Yes |
| Separate assistant database | Stronger physical separation but another operational store | No |

**Basis:** Personal, low-maintenance SQLite operation is a project-level constraint.

## Session Retention

| Option | Description | Selected |
|--------|-------------|----------|
| 30-day sliding TTL, 100 messages | Bounded context with useful continuity | Yes |
| Process-only or unbounded history | Less storage logic or more history, but violates Phase 4 bounds | No |

## Tool Boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Static local allowlist | Typed local intelligence tools; deny every unregistered capability | Yes |
| Dynamic/native dispatch | Let model/provider names resolve handlers dynamically | No |

## Claude's Discretion

- Exact retry/backoff implementation and prompt structure.
- Internal DTO/module names and SQLite indexes.
- Deterministic degraded reply wording.

## Deferred Ideas

- Feishu transport remains Phase 5.
- Agent-Reach and external research remain Phase 6.

