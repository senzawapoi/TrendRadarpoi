# Phase 6 Research

Date: 2026-10-11. Architecture confidence: high. Live backend availability: unverified.

## Verified Sources

- [Agent-Reach routing skill](https://github.com/Panniantong/Agent-Reach/blob/main/agent_reach/skill/SKILL.md)
  identifies a capability router and upstream tools rather than a unified search SDK.
- [Search reference](https://github.com/Panniantong/Agent-Reach/blob/main/agent_reach/skill/references/search.md)
  documents `mcporter call exa.web_search_exa query="query" numResults=5`.
- [Video reference](https://github.com/Panniantong/Agent-Reach/blob/main/agent_reach/skill/references/video.md)
  documents yt-dlp metadata and manual/automatic subtitles. Successful exit alone is
  insufficient: a transcript must have non-empty content. No audio fallback here.
- [MCPorter](https://github.com/steipete/mcporter) supports explicit HTTP configuration,
  JSON arguments/output. Isolate configuration to a fixed Exa server to prevent imports
  of unrelated local MCP servers or stdio executables.

Current Agent-Reach docs say authenticated Reddit uses OpenCLI/rdt, not a reliable
zero-configuration JSON endpoint. This phase instead restricts Exa results to public
Reddit URLs and documents the indexed-search limitation. It never reads browser cookies.

## Repository Reuse

Reuse ToolSpec/ToolRegistry's closed schemas, permission gates and three-call budget;
Assistant's local fallback, immutable Citation snapshots, session replay and Lark's
existing authorization boundary. Extend citation validation with a research namespace.
No dependency or schema migration is needed. Optional tools are resolved only on demand.

## Verification And Risks

Inject provider/process functions for offline parser and Assistant tests. Exercise actual
harmless child processes for deadline/output limits and sanitized environment. Kill/reap
timed-out processes; avoid abandoned timeout threads. Restrict webpage requests to Jina's
fixed proxy, captions to YouTube's fixed timedtext endpoint, and disallow redirects.
Upstream schemas may change; parser failures must be controlled, never raw-output fallback.

Three delegated agents failed with service-side HTTP 429 before producing artifacts;
planning, implementation and verification continue inline. No independent-agent review
is claimed. Real tool installation, provider quotas, anti-bot challenges and VPS behavior
must be checked later against the actual deployment environment.
