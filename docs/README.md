# Documentation Guide

## Start Here

| Task | Read |
|------|------|
| Configure keyword matching, aliases, filtering and HTML report modes | [Configuration / 配置与关键词](configuration.md) (中文 / English) |
| Connect a local MCP client over stdio | [MCP client setup / MCP 客户端配置](mcp-setup.md) (中文 / English) |
| Understand ingestion, Story, Security, storage and rollback | [Intelligence guide](intelligence.md) |
| Configure or run the opt-in Lark Assistant | [Lark setup and limits](intelligence.md#lark-assistant) |
| Execute Phase 5 live acceptance and troubleshoot failures | [Live acceptance runbook](phase5-live-acceptance.md) and [result record](../.planning/phases/05-feishu-assistant/05-LIVE-UAT.md) |
| Build, inspect or tidy the isolated Windows Phase 5 sandbox | [Local test sandbox](../test/README.md) |
| Review component boundaries and remaining risks | [Architecture review](code-review.md) and [codebase concerns](../.planning/codebase/CONCERNS.md) |
| Verify compatibility and compare phase checkpoints | [Runtime baseline](baseline.md) |
| Resume planned work | [Current state](../.planning/STATE.md), [roadmap](../.planning/ROADMAP.md) and [requirements](../.planning/REQUIREMENTS.md) |
| Inspect Phase 5 acceptance evidence | [Offline verification](../.planning/phases/05-feishu-assistant/VERIFICATION.md) |
| Configure optional Agent-Reach research | [External research boundary](research.md) |
| Contribute code or use an agent | [Repository guidelines](../AGENTS.md) and [Chinese agent guide](../CLAUDE.md) |
| Configure the seven AI source types | [AI Frontier guide](../trendradar/ai_frontier/README.md) |
| Deploy on Linux VPS and restore safely | [Deployment runbook](deployment.md) and [Phase 7 acceptance](phase7-acceptance.md) |
| Resume Phase 7 deployment and translation repair | [Current handoff](phase7-release-20261023/HANDOFF.md) and [07-06 plan](../.planning/phases/07-deployment/07-06-PLAN.md) |
| Inspect earlier Phase 7 repairs and tests | [Historical handoff](phase7-actual-gap-evidence/HANDOFF.md) and [07-05 plan](../.planning/phases/07-deployment/07-05-PLAN.md) |

## Delivery Status

Phase 0-6 implementation is offline-verified. Recorded Phase 7 release
`p7-20261023-8fc8f82` was deployed through approved GitHub run 39905435713.
Translation uses Gemini 3.1 Flash Lite; Lark is the only notification transport.
The subsequent canonical-title repair is local and uncommitted: it is not part of
that release. Chinese-title Lark acceptance remains open despite successful
legacy HTML translation. Final local Windows/Linux regression and Python 3.12 archive
installation now pass; the process-helper race is fixed. See the
[current handoff](phase7-release-20261023/HANDOFF.md) and
[follow-up evidence](phase7-release-20261023/TRANSLATION-FOLLOWUP.md) for results,
retained failed runs, evidence locations and resume order.

Source-health issues, Podcast/Blog recovery and 48-hour observation remain open.
This release uses local backups only; offsite recovery is not accepted. Preserve
the Phase 5 B6 accepted skip. Windows UAT and VPS observations have separate evidence;
neither substitutes for a new release's checks. Lark and external research remain
opt-in, and `--check` validates configuration without proving tenant permissions.
The [v6 report](phase7-actual-gap-evidence/verification-20261022.md) and
[pre-release record](phase7-release-20261023/README.md) are historical checkpoints.

The four root `TrendRadarpoi_*` requirement documents preserve the original brief. Use the GSD
state and phase verification files above for implementation progress and unresolved work.
`conductor/` preserves the historical pre-v5 snapshot, not current runtime instructions.

## Local Verification

Run from the repository root with Python 3.10+. Install runtime dependencies with
`python -m pip install -r requirements.txt`; install the currently undeclared test/lint tools with
`python -m pip install pytest ruff`. Run `python -m pytest tests -q` and
`python -m ruff check <changed-python-paths>`. Full-tree Ruff has existing debt; do not mix a
repository-wide formatting sweep into feature work.

## Workspace Hygiene

Preserve uncommitted work, source documents, GSD phase history and `output/`: SQLite databases and
generated reports are runtime state. Only known ignored tool caches such as `__pycache__/`,
`.pytest_cache/` and `.ruff_cache/` are disposable. Never use broad cleanup commands to remove
untracked files; they may contain unfinished implementation or user data. Retain `dist/` audit
archives and the isolated Linux test toolchain while Phase 7 reproduction remains unfinished.
Keep secrets outside Git.
During live UAT, also preserve `test/runtime/`, its SQLite WAL/SHM, images and logs. Check
`test/runtime/lark-live.json` against the running process before any restart; never launch a
second bot or use `-Reset` as cache cleanup. See the sandbox guide for retention and stop rules.
