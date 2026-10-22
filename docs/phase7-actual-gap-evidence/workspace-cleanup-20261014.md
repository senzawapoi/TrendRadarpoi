# Workspace Cleanup Checkpoint

Date: 2026-10-14 (Asia/Shanghai). Branch `main`, 42 commits ahead of
`origin/main`, HEAD `5a427aba5ded0c9c9c9e050413dcb41f17fa0e23`; dirty work retained.
This record documents a safe handoff, not Phase 7 completion or a release.

## Direct Checks During Cleanup

| Check | Observed result |
| --- | --- |
| Windows process names: Python, pytest, Ruff and WSL helpers | No matching processes at the inventory checkpoint |
| WSL `ps` for Python/pytest/restic/uv | No matching processes |
| `systemctl list-units --all --no-pager --no-legend 'trendradar-p7-*'` | No matching units |
| `python -B -m ruff check --no-cache trendradar/ops scripts/deploy tests/deployment trendradar/integrations/feishu/__main__.py` | Exit 0, all checks passed |
| Python AST parsing over those scopes | 35 files passed |
| `yaml.safe_load` for `phase7-*.yml` | Three mappings parsed; not Actions schema/execution validation |
| Separate `bash -n` for installer, Linux smoke, release smoke and fixed entry | All four exit 0 |
| Relative Markdown targets across edited docs and agent guides | 57 targets exist |
| GSD state YAML frontmatter and `git -c core.safecrlf=false diff --check` | Passed; state remains `in_progress` |
| `python -B -m trendradar.ops backup activate --help` | Exit 0; no `--deployment-rollback` argument |
| RG-03 actual systemd quiesce test | `tests/deployment/test_systemd_quiesce_linux.py` absent |
| Cache inventory excluding protected state | 18 ignored Python cache directories plus `.ruff_cache/`; no root `.pytest_cache/` |
| Historical source digest comparison | 11 of 49 paths differ from the 06:37:16 UTC snapshot |

No full pytest regression, RG-04 install or CI run was started during cleanup.
No source implementation was changed by cleanup. Historical verification
remains separate. Agent guides retain their existing 46/71 lines; no history
was appended to those rule documents.

## Documentation Changes

Fourteen files were updated or created, with no moves or deletions:

- `docs/README.md`
- `docs/deployment.md`
- `docs/phase7-acceptance.md`
- `docs/phase7-remediation.md`
- `docs/phase7-actual-gap-evidence/README.md`
- `docs/phase7-actual-gap-evidence/HANDOFF.md`
- `docs/phase7-actual-gap-evidence/workspace-cleanup-20261014.md`
- `.planning/PROJECT.md`
- `.planning/STATE.md`
- `.planning/codebase/CONCERNS.md`
- `.planning/codebase/STACK.md`
- `.planning/codebase/TESTING.md`
- `.planning/phases/07-deployment/07-05-PLAN.md`
- `.planning/phases/07-deployment/07-VERIFICATION.md`

Baseline, intelligence, research, code-review, Phase 1-6 and Phase 5 live records,
root README entry points, agent guides, sandbox and historical conductor/source
plans were assessed without edits. Their existing handoff pointers remain valid.

## Retained New Evidence

[Archived Linux reproduction](pre-fix-linux.json) records F-01/F-04: two tests
passed by asserting that the immutable old artifact fails the intended contracts.
The archive SHA256 is
`e759ee1b5d8efc9e524a773435e0a281a7d9de558c633cd2561fc43e8578130a`.
F-01 substitutes only a real archived health probe for the root-controlled
installer; F-04 performs an actual root restore and service-UID reads.

[Restore durability](restore-durability-20261014.json) records 8 failed/6 passed
before repair, Linux durability 20 passed afterward, and Windows combined
restore 38 passed/5 POSIX skips. Its earlier Linux combined run of 37 passed
predates six added cases. These overlapping scopes are not cumulative.

The preceding parent checkpoint also ran 12 Windows offsite/process tests
successfully, including suspended-process failures before/after Job assignment.
The historical [cleanup log](cleanup-verification-20261014.txt) retains the
101/120/24-test checkpoint and earlier systemd failure/rerun history.

## Agent Checkpoints

Both agents reached completed status and were closed. Their reports are
checkpoint evidence, not a parent rerun of the integrated worktree.

| Agent/task | Reported checks | Unfinished boundary |
| --- | --- | --- |
| Hypatia, RG-01/RG-02 | 122 passed in 36.49s; scoped Ruff, AST, Bash and whitespace passed | RG-03 researched only; no file/test/unit created |
| Erdos, installer/maintenance | Initial 7 failed/8 passed; later 35 passed/1 harness failure; corrected entry and no-snapshot rollback 3 passed; simulated timer success 1 passed; marker durability 6 passed; schema confirmation 7 passed; role guards 42 passed | Snapshot rollback CLI/API absent; complete installer suite not rerun |

The one harness failure came from putting `PYTHONDONTWRITEBYTECODE` in restricted
configuration; the agent removed that fixture mistake and reran affected checks.
Do not combine these counts: the scopes overlap and intervening edits differ.

## Preserved Assets And Next Step

Keep `output/`, `test/runtime/` and their DB/WAL/SHM, images and logs; all
uncommitted code, source plans, GSD history, audit archives and Linux toolchains.
No credentials, live business providers, production services, commit, push or
deployment were used. No global memory files were edited.

Cache removal was previously rejected by automatic approval review with
`blocked by policy`; this cleanup did not retry or use another removal tool.

Start with the missing guarded deployment rollback API, then the integrated
installer tests, actual systemd quiesce test, RG-04 installation and privileged
CI. Finish all 28 case records before final regression and source-hash freeze.
G1/G2 remain incomplete; G3/V-01..06 are NOT_RUN/BLOCKED. Phase 5 B6 retains its
accepted skipped branch; C3 real interruption and C4 receipt confirmation remain
open. See [handoff](HANDOFF.md) for the ordered continuation.

Confidence: high for inspected workspace state; unknown for production operation.
