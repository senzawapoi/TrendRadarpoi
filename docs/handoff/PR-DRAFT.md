# Worktree Reconciliation Handoff

## Summary

This branch makes the Phase 7 codebase reviewable for long-term ChatGPT Work and
Codex maintenance. It keeps the deployed `28e7283` baseline, adds source-health
and installer safeguards, migrates the real PhaseGate tool, and records the
reconciliation of `TrendRadarpoi-master` without bulk-merging its dirty tree.

## Review Scope

- Source fan-out failures now survive normalization as explicit degraded/unhealthy
  state instead of becoming a successful empty result.
- Health freshness uses the last error-free source run and does not refetch during
  readiness checks.
- Release archives are validated for traversal, link and unsupported-file members
  before service probing or maintenance state changes.
- Archive construction normalizes Bash/sh line endings (including the extensionless
  fixed installer), preserving source files and non-shell bytes. A real empty-venv
  installation exposed this CRLF failure before the regression fix.
- CI includes the role-capture regression and PhaseGate self/structure checks.
- `.gitignore`, locked dependencies, WSL/Linux guidance, Phase 7 handoff state and
  the 19:41 translation follow-up are explicit.
- The old Lark quote/tool patch is preserved as a source-only deferred reference;
  no active Bot/Worker code was mechanically copied.

## Verification

See [`handoff-validation-20261024.json`](../handoff-validation-20261024.json) and
[`workspace-audit-20261024-review.json`](workspace-audit-20261024-review.json), with the
full [candidate inventory and commit split](CANDIDATES.md). WSL Python 3.12 full
regression passed 1212 tests with 6 skips; PhaseGate self-tests passed 51;
changed-path Ruff and CI-selection tests passed. Separate empty-venv archive
installation passed using a pinned runtime wheelhouse, including pip check,
installed-package imports and smoke. JUnit and normalized source fingerprints are
linked from the validation record. This dirty archive is packaging evidence; a
clean exact-commit release still requires fresh validation after review.

## Commit Split And Stack

The owner approved publication after reviewing the inventory, security and tests.
The four commits separate source health (`d1cd72c`), deployment (`b8889dc`),
PhaseGate/audit (`464ddd9`) and this maintainer documentation/evidence. The PR base
is `fix/phase7-lark-routing-20261023` (PR #7), not `master`; this avoids repeating
the already deployed baseline. Reassess the stack base after #7 merges.

## Safety and Release Boundary

No production deployment, merge, database migration or live provider call is part
of this handoff. Existing schema/config compatibility, Bot authorization and
frozen delivery payloads remain unchanged. Revert individual handoff commits for
code rollback; do not reset runtime state. The old Lark patch is reference-only.
Do not close the later 19:41 translation issue based on the earlier Chinese receipt.
Source stability, live Lark acceptance, 48-hour observation and offsite recovery
remain open. Fresh final-commit install/CI results belong in the published PR;
pre-commit records retain their original dirty-tree provenance.
