# Workspace Cleanup After Rollback Repair

Checkpoint: 2026-10-14, Asia/Shanghai. This reconciles current documentation
after RG-03 repair and the remaining assertion report. It supersedes earlier
cleanup resume instructions, without modifying their evidence or hashes.
Phase 7 07-05 remains in progress; no acceptance gate is closed.

## Verified State

- Worktree is dirty on `main`, 42 commits ahead of `origin/main`; HEAD is
  `5a427aba5ded0c9c9c9e050413dcb41f17fa0e23`. HEAD does not identify these edits.
- Hypatia and Erdos finished and were closed. Their implementation/test files
  are frozen for this handoff; no known test session remains running.
- Read-only Windows inspection found no Python/pytest/Ruff process. Ubuntu WSL
  inspection found no pytest/test-owned process, no `trendradar-p7-test-*` unit
  and no matching `/run/systemd/system` unit file. The probe excluded itself
  and its ancestors; no process termination was needed.
  A final post-check inspection at 2026-10-14T09:06:05Z again found no relevant
  Windows process or matching systemd test unit.
- `output/`, `test/runtime/`, `dist/`, original failure directories and both
  isolated Linux toolchains remain retained. No credentials were read.
- No commit, push, deployment, live Lark/Gemini/source/restic call, database
  reset or cache deletion was performed by this cleanup.

## Evidence Reconciliation

The historical RG-03 9-pass/1-failure result was caused by service confirmation
reading a root-owned 0600 restore guard. Automatic restore/activation now use
the service identity; rollback renews the controller lease and confirmation
requires an explicit false business boundary. The repaired real-systemd restart
node passed; expired-lease/rollback/confirmation passed 29 and restore/crash
scope passed 43. These overlapping, previously executed results are in
[repair evidence](rg03-rollback-fix-20261014.json). Full current-module regression
remains open.

The remaining Linux assertion module reported **26 passed, 1 failed** in
30.90s (agent session 63299). **ENV-03 remains open:** the trusted loader checks
YAML existence without reading it. Root without DAC bypass cannot read a
mode-000 file, yet the fixed entry reaches its isolated migration helper.
The full installer separately checks readability as the service identity;
this is not evidence of a deployed-VPS failure. The enabled failing test and
its exact source hash are in [assertion evidence](remaining-assertions-20261014.json).

Cleanup executed only bounded checks:

| Check | Result and boundary |
| --- | --- |
| Windows frozen `test_remaining_gap_assertions.py` | 16 passed, 11 Linux-root skips, 9.14s; direct parent output |
| Linux `test_ci_acceptance_scope.py` | 18 passed, 2.69s; target paths exist; sudo/operations stubbed; not GitHub execution |
| Scoped Ruff, eight Python paths, `--no-cache` | Passed |
| Source AST, JSON, workflow/Bash and active documentation links | Passed; counts below |
| Full Windows/Linux/systemd regression | Not run during cleanup |

The [source inventory](cleanup-source-sha256-20261014-post-rollback.json) records
74 inputs, including 40 Python files, at 2026-10-14T09:01:35.9030620Z.
Nine paths are new or changed since the earlier 72-input cleanup snapshot.
This identifies cleanup inputs; it is not a final release manifest or evidence
that a clean candidate exists. Historical snapshots remain unchanged.

## File Inventory And Actions

All ten top-level `docs/*.md` files were enumerated and assessed against the
affected code/status. Root guides and scattered Markdown were also inventoried.
Original briefs and historical records remain in place.

| Files | Action |
| --- | --- |
| `docs/README.md`, `deployment.md` | Align current status, repaired RG-03 and remaining gates |
| `docs/phase7-acceptance.md`, `phase7-remediation.md` | Distinguish repair evidence, CI wiring and ENV-03 failure from acceptance |
| Evidence `README.md`, `HANDOFF.md`, `case-matrix.md` | One resume order; preserve failure provenance; remove invented HEALTH-04 gate |
| `.planning/PROJECT.md`, `STATE.md` | Record frozen agents and ENV-03-first resume |
| `.planning/codebase/CONCERNS.md`, `TESTING.md` | Replace stale root-cause/CI claims and map new tests |
| `.planning/phases/07-deployment/07-05-PLAN.md`, `07-VERIFICATION.md` | Reconcile incomplete current verification |
| `remaining-assertions-20261014.json`, new source inventory, this record | Preserve reported/direct evidence and source identity |
| `docs/baseline.md`, `code-review.md`, `intelligence.md`, `phase1-6-fix-audit.md`, `phase5-live-acceptance.md`, `research.md` | No changes needed for this deployment-status reconciliation |
| Root READMEs, original requirement/Phase 7 plan documents, `conductor/` history | Preserve content; current status is reached through documentation navigation |
| `AGENTS.md`, `CLAUDE.md` | Existing rules remain valid; 46/71 lines and 4,144/4,804 bytes; no history added |
| Prior evidence JSON/logs/cleanup Markdown and Linux fault directories | Preserve as historical snapshots |
| Production code, workflow and tests | No edits by this cleanup; retain prior agent/parent changes |

## Cache Retention

Read-only inventory reconfirmed 19 ignored `__pycache__` directories outside
protected state and `.ruff_cache/`; no root `.pytest_cache/` exists. Earlier
recursive cache deletion was rejected by automatic approval review with
`blocked by policy`. This cleanup did not retry deletion or use an alternative
tool to bypass the rejection. Cached files are separate from runtime state.

## Resume

1. Repair ENV-03 actual readability before fixed-entry maintenance; rerun the
   failing Linux node and affected parser/entry tests with sanitized errors.
2. Complete PERM-01/04 and GUARD-01/02/05/06/07 positive-path and journal/schema/FK
   assertion mapping. HEALTH-04 multiple-pending and extra installer-metadata
   faults are not required by the supplied plan.
3. Freeze implementation, then execute final Windows/Linux/systemd regression
   and refresh release evidence. Retain a real GitHub run; local wiring is not CI.
4. Clean RG-04 production candidate remains BLOCKED without an authorized
   committed revision. V-01..06 remain NOT_RUN/BLOCKED pending target inputs.

G1/G2 remain incomplete. G3/VPS operation is unverified. Phase 5 B6
non-whitelisted testing remains an accepted skip; C3 real interruption and C4
recipient confirmation remain open. Do not infer gate closure from test totals.

## Final Validation

Non-writing checks passed: all 74 source hashes match; 40 Python inputs parse
with AST; eight evidence JSON files parse; 77 local links in 16 active documents
resolve; three workflow files parse and their 17 Bash run blocks pass syntax;
four shell entry/scripts pass `bash -n`. No bytecode or tool cache was written.

The matrix has 28 unique rows: 17 scoped PASS, one FAIL (ENV-03), nine BLOCKED
and one NOT_RUN. These are draft assertion statuses, not completion percentages
or final-regression results. `git diff --check` exited 0 with 46 existing
line-ending warnings and no other messages. Root agent guides were unchanged,
so their net growth is zero.

Confidence: high for direct checks and source review; Linux supplemental pytest
is explicitly agent-reported; production operation is unknown.
