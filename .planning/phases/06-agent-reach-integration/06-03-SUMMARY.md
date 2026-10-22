---
phase: 06-agent-reach-integration
plan: '03'
status: complete
verified: 2026-10-11
---

# 06-03 Summary

Added opt-in `intelligence.research` settings and `INTELLIGENCE_RESEARCH_*`
environment overrides. The Assistant exposes one closed `research_external` tool
only when the gateway has enabled capabilities and the tool gate is enabled. It
creates bounded server-side `research:` citations marked external and untrusted;
external output is not inserted into canonical ContentItems or Stories. Gateway
failure preserves local evidence and marks the response degraded. Disabled or
unconfigured research performs no upstream call. Existing local tools and Lark
authorization boundaries remain unchanged.

Verification: Phase 6 research tests and the full repository suite passed; no live
Agent-Reach tool, provider, credential or VPS acceptance was performed.
