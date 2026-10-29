# PR 8 Handoff Repairs Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Diagnose the reported English-title delivery and repair direct-parent Lark replies and tool argument recovery, preserving current authorization and delivery guarantees.

**Architecture:** Keep canonical title translation before Story publication; preserve raw evidence and frozen delivery payloads. Transport resolves one authorized direct parent and passes a bounded, untrusted DTO to the Assistant. The core owns argument validation and evidence-backed recovery.

**Tech Stack:** Python 3.10-compatible source, Python 3.12 WSL native filesystem, locked existing dependencies, pytest, Ruff, SQLite read-only production diagnosis.

---

## Baseline and scope

- PR 8 is merged as a0dd38ecbea50737781241c1244cc3752feeb1cf.
- Local repair branch starts from b700fc64991f8ab4438e45212bba80d086d076db; both commits have tree 07164edf43ab050af34b2369680ac6047959d499. Local GitHub fetch was unavailable.
- Worktree: C:\Users\DELL\Desktop\TrendRadarpoi-pr8-repair-20261024.
- WSL source and interpreter are recorded in output/pr8-repair-20261024/linux-scene.json.
- User authorized local review and repair, including review/port of the deferred patch. No commit, push, production change or Lark/model call is included.
- Preserve old workspaces, audit archives, runtime SQLite/WAL/SHM and immutable delivery snapshots.

## Task 1: Reproduce and diagnose title publication

Files: trendradar/ai/translator.py, trendradar/intelligence/translation.py, relevant title-publication tests, docs/intelligence.md.

1. Query the deployed database read-only for the 2026-10-23 19:41 Asia/Shanghai delivery window; correlate frozen post text, Story title and canonical translation metadata.
2. Inspect translation output parsing and failure handling. Record observed cause separately from hypotheses.
3. Add a deterministic regression for any demonstrated code defect. Run it before changing implementation; expect failure.
4. Make the smallest correction that retains raw titles, ranking identity and delivery immutability. Never requeue or rewrite delivered messages.
5. Run focused translation/publication tests. If the issue is provider-side or needs production evidence unavailable locally, document the precise remaining acceptance gate.

## Task 2: Repair tool argument validation

Files: trendradar/ai/tools.py, tests/ai/test_tools.py, tests/ai/test_tool_recovery.py.

1. Review the preserved patch as reference only; port tests for joint time_range, legacy pair compatibility and safe error classification.
2. Run the new tests on the baseline and record expected failures.
3. Implement strict timezone-aware paired bounds, UTC normalization, range/result limits, and invalid_arguments distinct from permission/availability/execution failures.
4. Verify logging excludes query content, arguments and raw exception values.
5. Run focused tool tests; expect all passing.

## Task 3: Bound evidence-backed tool correction

Files: trendradar/ai/assistant.py, tests/ai/test_tool_recovery.py, tests/ai/test_assistant*.py.

1. Add/port tests for the existing three-call budget, one correction per need, valid original bound preservation and retained failed audit entries.
2. Require visible citation-backed search evidence before resolving a prior argument error. Empty/truncated/malformed results cannot clear it.
3. Adapt the recovery loop without losing the current multi-model routing and citation validation.
4. Run Assistant and tool tests; expect unresolved failures to remain visibly degraded.

## Task 4: Add safe direct-parent reply context

Files: trendradar/ai/models.py, trendradar/ai/assistant.py, trendradar/integrations/feishu/{models,client,handler,reply_context}.py, tests/ai/test_quoted_context.py, tests/integrations/feishu/{test_client,test_quoted_replies,test_reply_context,test_idempotency}.py.

1. Port DTO/parser/client/handler tests from the reference patch, checking compatibility with current Worker, maintenance and saved-reply paths.
2. Persist only optional direct parent_id in v1 events; old events remain valid.
3. Perform one same-chat GetMessage only after authorization, genuine mention, claim and lease. Never traverse root/ancestor/history.
4. Prioritize current question within combined input limit; quote at most 4000 characters. Preserve visible HTTP(S) links without fetching; disclose omissions.
5. Keep quote text untrusted and separate; no quote-derived permissions or verified citations.
6. Verify unavailable Assistant, no allowance, completed duplicate and saved-reply retry perform no unnecessary lookup/model/download.
7. Run focused AI/Lark suites; expect all passing.

## Task 5: Review Phase 7 gates and validate exact working tree

Files: docs/handoff/deferred-lark-repair.md, docs/phase7-release-20261023/HANDOFF.md, docs/repository-handoff-20261023.md, repair acceptance notes.

1. Review existing PR 8 source coverage and installer fixes; run their relevant regression tests without changing production state.
2. Run changed-file Ruff, then focused tests in WSL Python 3.12.
3. Run full pytest on the same native Linux source and preserve JUnit/log evidence in output/pr8-repair-20261024. Investigate failures without deleting their scenes.
4. Compare changed files between Windows and WSL and record HEAD, tree basis and working diff.
5. Update handoff with implemented fixes, actual counts and commands, unresolved production acceptance, and exact owner inputs needed.

Example commands (from WSL source; interpreter read from scene file):

- $PY -m pytest tests/ai tests/integrations/feishu -q
- $PY -m pytest tests -q --junitxml=<evidence>/full.xml
- $PY -m ruff check <changed Python paths>
- git diff --check

## Remaining external gates

Production is still release p7-20261023-28e7283 until a separately authorized deployment. Verify/bootstrap the fixed root-owned installer before that rollout. Live quote acceptance needs approved direct-message read permission and the sole Bot/Worker at the tested build. Forty-eight-hour observation, resource limits and offsite backup/restore remain separate gates; local regression does not close Phase 7.

## Execution result — 2026-10-24

Local review and implementation are complete. Read-only production diagnosis found a Gemini
server error followed by cooldown and 21 documented original-title fallbacks; no translation
policy or frozen message was changed. Quote/tool repairs include additional failover,
provider-input and malformed-empty-result fixes beyond the historical reference patch.
Final focused regression: 538 passed. Final Linux full regression: 1464 passed, 6 explained
skips, 2 existing dependency warnings, 543.12 seconds. Changed Python Ruff and Git whitespace
checks passed; all 299 source/config/dependency paths match the tested WSL source after
line-ending normalization. See [the repair record](../handoff/PR8-REPAIR-20261024.md).
Commit/push, deployment and external operational gates remain outside this completed local task.
