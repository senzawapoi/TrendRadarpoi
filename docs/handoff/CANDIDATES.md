# Pre-commit Candidate Inventory

Review snapshot: 2026-10-24, local `work/trendradar-handoff` at `28e7283`.
There are 56 candidate paths: 35 modified tracked files and 21 new files.
This records the pre-commit review state, when nothing was staged or published.
The owner approved this inventory and publication on 2026-10-24. The groups below
are the approved split; inspect Git history and the PR for completed commit IDs.
The [audit JSON](workspace-audit-20261024-review.json) records point-in-time hashes;
its own output is excluded from that JSON's candidate entries to avoid self-reference.
All 56 paths, including that report, appear below. `M` means modified; `A` means new.

## 1. Source Health And Parsers

Proposed commit: `fix(sources): preserve fan-out failures and source freshness`.
Keep valid siblings on partial failure, report truthful passive health and last
error-free run, and update Podcast/Blog parsing/configuration with regression tests.
No upstream refetch during health checks; legacy database schemas stay unchanged.

```text
M config/config.yaml
M tests/ai_frontier/test_official_blog.py
A tests/ai_frontier/test_source_health.py
M tests/ai_frontier/test_youtube_podcast.py
M tests/deployment/test_combined_readiness.py
M trendradar/ai_frontier/sources/arxiv.py
M trendradar/ai_frontier/sources/base.py
M trendradar/ai_frontier/sources/github_trending.py
M trendradar/ai_frontier/sources/hackernews.py
M trendradar/ai_frontier/sources/nitter.py
M trendradar/ai_frontier/sources/official_blog.py
M trendradar/ai_frontier/sources/reddit.py
M trendradar/ai_frontier/sources/youtube_podcast.py
M trendradar/intelligence/runner.py
M trendradar/ops/health.py
M trendradar/sources/ai_frontier.py
M trendradar/sources/base.py
```

## 2. Deployment Safeguards

Proposed commit: `fix(deploy): validate archives before service probes and preserve restart intent`.
Reject malformed tar entries before side effects; capture active roles before the
maintenance marker; normalize Shell CRLF only in archives (including extensionless
installers). Preserve source and other bytes. Include the CI role-capture hunk here;
the workflow's PhaseGate step belongs to commit 3, so stage this shared file by hunk.

```text
M .github/workflows/phase7-ci.yml
M scripts/deploy/build_release.py
M scripts/deploy/install_release.sh
M tests/deployment/test_deployment_contracts.py
M tests/deployment/test_installer_behavior.py
A tests/deployment/test_installer_role_capture.py
```

## 3. PhaseGate And Audit Tooling

Proposed commit: `chore(phasegate): preserve real gate and reproducible workspace audit`.
Migrate the real advisory tool, not its demo/pilot output; protect runtime/secret
paths and lint/run the tool in CI. Include the remaining PhaseGate workflow hunk.
Structural `inspect` does not close application or VPS gates.

```text
M .gitignore
A phasegate/README.md
A phasegate/phase7.json
A phasegate/phase7_gate.py
A phasegate/pytest_evidence.py
A phasegate/tests/test_real_gate.py
A scripts/dev/audit_repository_handoff.py
```

## 4. Maintainer Handoff And Evidence

Proposed commit: `docs(handoff): document reconciled baseline and open acceptance gates`.
Keep architecture/Phase constraints navigable, preserve the deferred Lark source
attachment without activating it, and bind test evidence to source snapshots.
The two earlier audit JSONs and earlier fingerprint remain historical snapshots;
the `review` audit and `final` fingerprint are the latest references.

```text
M .planning/PROJECT.md
M .planning/STATE.md
M .planning/codebase/TESTING.md
M .planning/phases/07-deployment/07-06-PLAN.md
M AGENTS.md
M CLAUDE.md
M README-EN.md
M README.md
M docs/README.md
M docs/deployment.md
A docs/handoff-validation-20261024.json
A docs/handoff/CANDIDATES.md
A docs/handoff/PR-DRAFT.md
A docs/handoff/deferred-lark-repair.md
A docs/handoff/deferred-lark-repair.patch
A docs/handoff/evidence/artifact-install-final-20261024.xml
A docs/handoff/evidence/full-final-20261024.xml
A docs/handoff/source-fingerprint-20261024.json
A docs/handoff/source-fingerprint-final-20261024.json
A docs/handoff/workspace-audit-20261024-final.json
A docs/handoff/workspace-audit-20261024-review.json
A docs/handoff/workspace-audit-20261024.json
M docs/phase7-release-20261023/HANDOFF.md
M docs/phase7-release-20261023/README.md
M docs/phase7-release-20261023/TRANSLATION-FOLLOWUP.md
A docs/repository-handoff-20261023.md
```

## Retained And Excluded

Original Phase 0-7 plans, requirements, root context/task/implementation documents,
architecture and dependency locks already exist in the primary baseline. The
path-by-path audit accounts for all 525 old dirty entries. No wholesale merge or
file deletion was performed. The deferred Lark patch is a review attachment, not
an apply-ready diff against this baseline.

Keep `output/`, UAT databases/WAL/SHM, credentials, SSH access files, logs, caches,
raw provider payloads, `.phasegate/` pilots, the demo ZIP and `phase-gate-demo/`
local. Only the two curated non-runtime JUnit files above are selected as new raw
test evidence; historical tracked acceptance records remain historical.

## Verification And Open Gates

WSL Python 3.12 full: 1212 passed, 6 skipped; separate empty-venv archive install:
1 passed; PhaseGate self-tests: 51 passed; changed-path Ruff, CI-scope tests and
pip check pass. See [machine evidence](../handoff-validation-20261024.json) for
commands, warning/skip classification, prior failures and source hashes.
These counts overlap and must not be summed.

Still open: the 10-23 19:41 untranslated Yahoo/other batch; target-tree port and
live acceptance of the old Lark tool/quote repair; source stability; 48-hour VPS
observation; offsite backup/restore. A dirty archive install does not close the
clean exact-commit release gate or prove current tenant delivery. Preserve B6 skip.

The requirements 7/8 review boundary was met; the owner approved all four commits,
branch push and a stacked PR on 2026-10-24. Rebind exact-commit evidence after
committing; PR #7 remains the stack base. Do not merge, deploy, reset, delete or
force-push. Historical audit JSON hashes describe their generation-time contents;
these post-approval documentation updates intentionally supersede that text.
