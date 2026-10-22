# Documentation Guide

## Start Here

| Task | Read |
|------|------|
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
| Resume Phase 7 actual-gap repairs and tests | [Current handoff](phase7-actual-gap-evidence/HANDOFF.md) and [07-05 plan](../.planning/phases/07-deployment/07-05-PLAN.md) |

## Delivery Status

Phase 0-6 implementation is offline-verified. Phase 7 authorized local work is
complete: frozen v6 Windows full 683 passed/342 skipped, Linux full 1019 passed/
6 skipped, two explained upstream warnings each, all exit 0. Real systemd
quiesce has 11 passing cases and backup units 2 within Linux full. Separate
actual empty-venv dirty installation passes; all 301 source/resource hashes
and archive members match. [Final report](phase7-actual-gap-evidence/verification-20261022.md)
binds commands, environments, artifact and all skips. The 28-case audit is
27 PASS/1 BLOCKED (RG-04 clean candidate): G1 PASS; G2 blocked; G3/VPS pending.
Actual GitHub execution and remote backup remain open. Historical failures and
archived pre-fix reproduction are retained; do not poll old test handles.

ENV-03 fixed-entry YAML readability was repaired: the 48-test Linux follow-up
passed. The 2026-10-14 deployment-only run finished with 466 passed and 6 skipped.
These are historical scoped results. The dated 2026-10-15 handoff's local work
is complete; current evidence includes repaired Windows tzdata and same-boot
controller leases without relaxing the 15-second/identity fences.
The live UAT record confirms Lark private
text/follow-up, pure-image, a fresh single-post mixed-image request, explicit group mentions,
session isolation and normal same-database restart continuity. Controlled recovery checks pass;
real network interruption remains unexecuted, and scheduled delivery awaits recipient confirmation.
This is Windows UAT, not Linux VPS deployment. Lark stays disabled by default; external research
also stays disabled by default. `--check` validates
configuration without network access or database writes, not provider credentials or tenant
permissions. Phase 7 requires completion of the current test matrix and its VPS gates; Phase 8 remains
roadmap work. Phase 5 B6 non-whitelisted testing is an accepted skip; C3 real
interruption and C4 recipient confirmation remain open.

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
