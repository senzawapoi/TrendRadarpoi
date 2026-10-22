# Optional External Research

Phase 6 adds an opt-in `ResearchGateway` for on-demand external evidence. It is
separate from the crawler and `intelligence.db`; it does not ingest, rank, cluster,
or persist provider output. `INTELLIGENCE_RESEARCH_ENABLED=false` is the rollback.

The gateway exposes five compiled-in capabilities: `search_web`, `search_github`,
`search_reddit`, `read_webpage`, and `get_video_transcript`. The Agent-Reach routes
these through fixed upstream tools: Exa via `mcporter`, GitHub CLI, public Reddit
URLs in Exa results, Jina Reader, and YouTube `yt-dlp` captions. It does not read
browser cookies, install tools, accept an executable path, or expose shell access.
The GitHub route uses an isolated `GH_CONFIG_DIR` and accepts only the explicit
`INTELLIGENCE_RESEARCH_GITHUB_TOKEN` mapping; host `gh` profiles and generic
environment variables are not inherited. Application credentials such as Gemini
and Lark secrets are not inherited. Repeated completed `event_id` callbacks are
locally suppressed after successful delivery; failed provider delivery still
retries the saved reply. These paths are separate from provider/model retry.

Enable only on a machine where the optional tools are already installed and tested:

```text
INTELLIGENCE_RESEARCH_ENABLED=true
INTELLIGENCE_RESEARCH_CAPABILITIES=search_web,read_webpage
```

External results are bounded, marked untrusted, and cited with server-built
`research:` references for the current Assistant response. Provider failures produce
a degraded local answer and do not refetch existing TrendRadar sources. Offline
tests inject process/HTTP boundaries; passing them is not live provider or VPS
acceptance.
