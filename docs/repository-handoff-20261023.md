# TrendRadarpoi Repository Handoff

Updated: 2026-10-28. Start here when ChatGPT Work or Codex resumes this repository.
This document complements the [Phase 7 handoff](phase7-release-20261023/HANDOFF.md).

## Current Git State

- Active recovery worktree: `C:/Users/DELL/Desktop/TrendRadarpoi-deploy-checkpoint-20261027`,
  branch `fix/deploy-recovery-20261028`, based on `241cefb`. The controller has passed 1503 full Linux tests (6 skips), with 59 focused checks;
  the [deployment checkpoint](handoff/DEPLOY-A20F2D8-20261028.md) are local work.
- Original repair worktree: `C:/Users/DELL/Desktop/TrendRadarpoi-pr8-repair-20261024`,
  branch `fix/pr8-handoff-repairs-20261024`, clean application commit `a20f2d8`.
- PR 9 merged into `fix/phase7-lark-routing-20261023` as `241cefb`; its content tree
  equals `a20f2d8`. PR 7 remains OPEN, base master. Do not automatically merge it.
- Application CI `40089562197` passed four jobs. Exact clean artifact validation in
  deploy run `40493521142` passed; VPS deployment failed readiness after installation.
- VPS current is `p7-20261027-a20f2d8`, under maintenance with roles/timers stopped.
  The last successful version was `p7-20261023-28e7283`; do not describe it as live now.
- User authorization for committing and deploying these repairs and continuing
  recovery is explicit. Preserve failed records and the business-boundary fence.
- The primary handoff tree `TrendRadarpoi-phase7-fix-20261023`, original dirty tree,
  runtime data and all historical pre-commit inventories remain retained.
- Old worktree: `C:/Users/DELL/Desktop/TrendRadarpoi-master`, local `main` at
  `5a427aba`, 42 commits ahead of its recorded `origin/main`, with 46 modified and
  479 untracked files. It remains untouched and is an audit source, not a merge base.
  The worktrees diverged from `3572aeb`; current has 7 and old `main` 15 unique commits.

## Reconciliation Decisions

| Area | Decision |
| --- | --- |
| Current application and Phase 0-7 planning | Keep the Phase 7 worktree as the code baseline. Its tracked `.planning/phases/` contains the plans/history. Original root context/task/implementation documents, REQUIREMENTS and ROADMAP are already identical to the old tree after LF normalization. Retain them. |
| Old implementation/config edits | Do not bulk merge the 46 modified paths. Review each by behavior; port only changes with a demonstrated gap and a focused test. In particular, do not transplant the old translation or Lark quoted-context patch without target-tree review. |
| PhaseGate | Keep the real `phasegate/` CLI, manifest, pytest evidence plugin, README and tests. It maps 34 scenarios in 14 suites; its structural `inspect` result is not application or VPS acceptance. |
| Runtime evidence | Keep local only: `output/`, `test/runtime/`, `.phasegate/` pilot reports, databases/WAL/SHM, logs, UAT descriptors, raw provider payloads, audit scenes, generated archives and cache directories. Never delete the old evidence during reconciliation. |
| Demo and archive | Exclude `phase-gate-demo/` and `PhaseGate-Demo-v0.1.0.zip`; these are a standalone prototype and generated package, not the real gate. |
| Secrets and deployment access | Exclude live `.env` files, credentials, SSH/BAT files, private keys and documents containing live values. Keep reviewed empty templates. The historical Feishu task brief already exists in both trees; its encoding damage is historical, not a new secret finding. Current requirements live in PROJECT/REQUIREMENTS. |
| Deferred Lark patch | The owner subsequently authorized local repair after PR 8 merge. Ported against the current model/Worker implementation with new failing regressions first; see the [repair record](handoff/PR8-REPAIR-20261024.md). Preserve the old reference patch as provenance. |
| Retired channels | Do not restore Bark, webhook, email or other retired senders. Lark remains the only notification transport. |

Six deployment environment templates are unignored via `.gitignore` exceptions;
`requirements.lock` and `build-requirements.lock` are exact-pinned. The Phase 7
CI/release/deploy workflows target both `master` and `main` where relevant. Runtime
SQLite and test sandbox paths are explicitly ignored. Review candidate paths with
`git status --short --untracked-files=all` before staging.

## Phase 7 Status

The 13:41 English-title defect has a deployed repair: commit `28e7283`
resolved canonical titles before Story publication, was deployed by run
`39921046202`, and Chinese titles/links were confirmed received at approximately
16:36. **The later 10-23 19:41 report was diagnosed read-only on 10-24:** Gemini
returned a server error, the translation route entered cooldown, and 21 new titles
used the documented original-title fallback. The frozen posts remained English
after later translation of ten Stories. Translation uses
`gemini-3.1-flash-lite`; failures retain original text. The old Gemma failure is
not the current translation configuration. Historical reports are retained and
must not be rewritten as if those failures did not occur.

The quote/tool port is now implemented and validated locally. Open gates remain
its exact-build live acceptance, translation provider stability and future receipt,
source health/Podcast/Blog stability, at least 48 healthy hours, and offsite backup
and restore. Read-only VPS verification is separate from local code validation;
no production mutation was made. Preserve the accepted Phase 5 B6 skip.

## Historical PR 8 Handoff Changes And Verification

1. Source health, parser behavior and Podcast/Blog configuration/tests in
   `trendradar/ai_frontier/sources/`, `trendradar/intelligence/runner.py`,
   `trendradar/ops/health.py`, `trendradar/sources/`, `config/config.yaml`, and
   `tests/ai_frontier/`.
2. Installer service-role capture and readiness/test changes in
   `scripts/deploy/install_release.sh` and `tests/deployment/`.
3. Real PhaseGate tool, repository guide and planning/readme updates.
4. Follow-up found and fixed: malformed release archives were rejected only after
   service-role probes; preflight now validates archive members before any service
   probe. The privileged CI selection now includes the added role-capture test.
5. Real archive installation exposed CRLF Shell scripts in the tarball. The builder
   now normalizes only `.sh` and recognized Bash/sh shebangs (including the fixed
   extensionless installer), with correct tar sizes; source and non-shell bytes
   are preserved. See the synthetic CRLF regression in `test_deployment_contracts.py`.

The first broad focused run is recorded as failed: 8 failed, 656 passed and 6
skipped. One failure was the stale CI selection list, six were the archive side-effect
ordering contract, and one Linux installer readiness test exceeded its 30-second
limit while running from `/mnt/c`. After the first two fixes, the WSL-native rerun
passed 142 tests, and installer behavior passed 60 tests. The final WSL-native
Python 3.12 full run passed 1212 tests with 6 skips and 2 dependency warnings
in 559.23 seconds; the earlier 1210-test result predates the two packaging tests.
PhaseGate's own 51 tests passed; inspect confirms 34 scenarios/14 suites,
not business acceptance. See the machine-readable
[validation record](handoff-validation-20261024.json); update it only with results
from the tested source snapshot; document-only edits do not become tested code.
Separate Python 3.12 empty-venv archive installation passed in 72.16 seconds using
a pinned runtime wheelhouse. A prior pip timeout and the CRLF failure remain
recorded. Build-lock installation still uses the pip index/cache; this is not a
claim of a fully offline install. The final archive records `git_dirty=true` and
`clean_candidate=false`; its hash is not a future release identity.

## Review Package

- [Path-by-path audit](handoff/workspace-audit-20261024-review.json): all 525 old changed/new
  files, normalized hashes, comparisons, decisions and secret-scan locations.
- [Validation summary](handoff-validation-20261024.json): commands, results, source
  fingerprints, skips, failures and remaining gates. No synthetic JUnit is claimed.
- [Source binding](handoff/source-fingerprint-final-20261024.json): normalized source
  comparisons with the final Linux full-test snapshot and Git artifact clone.
- [Complete candidate list and proposed commits](handoff/CANDIDATES.md): all pending
  paths, including this review material; no blanket `git add` is authorized.
- [Deferred implementation](handoff/deferred-lark-repair.md): source preservation,
  known contract defects, protected boundaries and live acceptance requirements.
- [Draft PR body](handoff/PR-DRAFT.md): review scope and deployment exclusion.

The audit categorizes files; it does not prove equivalence of differing implementations.
Phase 7 models, durable delivery and guarded deployment supersede old variants.
Preserve current translation-before-publication rather than restoring old anonymous
translation or retired senders. Source parser/health differences have new focused
tests. Differing historical evidence remains historical. The only missing non-demo
files were the six deferred quote/tool files; their code and behavior are now
preserved in the review attachment.

The required pre-commit review was completed and approved on 2026-10-24. The first
three commits are `d1cd72c` (sources), `b8889dc` (deployment) and `464ddd9`
(PhaseGate); the fourth commits this documentation and evidence. The source
fingerprints and JUnit here intentionally retain their pre-commit provenance.
The owner has since merged that handoff as PR #8 and authorized the local repair
record linked above. Preserve these pre-commit historical fingerprints. Bind future
clean archive/install evidence to the next committed repair revision. A successful
clean install is not VPS acceptance; deployment still requires a scoped instruction.
