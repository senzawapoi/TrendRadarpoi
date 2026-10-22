# Phase 6 Context

Date: 2026-10-11. Status: authorized for implementation by the current user request.

## Scope And Decisions

- D-01: ResearchGateway is the only Assistant external-research boundary. It is opt-in,
  independent of crawlers, SQLite ingestion and the base application's dependencies.
- D-02: Expose research/search/fetch contracts and five fixed capabilities: search_web,
  search_github, search_reddit, read_webpage, get_video_transcript. No arbitrary command,
  executable, plugin, installation, browser session, or MCP server selection from callers.
- D-03: Validate permissions and parameters before I/O. Bound concurrency, wall time,
  process output, response bytes, result count and Assistant-visible text. Audit only
  capability, opaque principal, outcome, count and duration.
- D-04: Agent-Reach is an upstream capability router, not a Python search SDK. Use its
  documented Exa/mcporter, gh, Jina Reader and yt-dlp backends behind a local adapter.
  Reddit research uses public indexed Reddit pages through Exa; authenticated Reddit,
  browser cookies, audio transcription and installation are outside this phase.
- D-05: External results are untrusted, server-cited snapshots, separate from persisted
  Story evidence and rankings. Local retrieval remains first; failure never refetches
  the crawler or prevents a local answer.
- D-06: Windows development uses isolated offline tests; Linux VPS installation/live
  backend acceptance remain separate. Do not alter test/runtime, output or credentials.

## Existing Acceptance

Phase 5 implementation/offline verification exists. B6 unauthorized-user branch was
explicitly skipped; C3 real interruption/cooldown and C4 recipient confirmation remain
open. Advancing to Phase 6 does not change those records. No commit or deployment is authorized.
