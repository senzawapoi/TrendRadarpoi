# Translation Repair Validation Follow-up

Date: 2026-10-23. Worktree: `TrendRadarpoi-phase7-fix-20261023`, branch
`fix/phase7-lark-routing-20261023`, base commit `8fc8f82d377c86b8d904c17dc7fb8cdb6421835a`.
This is local repair/validation evidence, not a new deployed release.

## Root Cause And Repair

The original full Linux failure was in the test helper `_alive`, which checked
`/proc/<pid>/stat` existence before reading it. A child exiting between those
operations raised `FileNotFoundError`. A subsequent actual-process run also
captured `ProcessLookupError` when the process disappeared after opening the file.
Both represent a terminated process, not a backup failure.

`tests/deployment/test_offsite_processes.py` now reads directly and handles only
those two exceptions. Cleanup suppresses only `ProcessLookupError` when the child
exits before `SIGKILL`. Permission errors and unexpected failures still propagate;
live and zombie process states retain their previous meaning. Eight regression
cases cover these boundaries. Initial deterministic reproduction failed twice
before the repair; the actual ESRCH failure is also retained.

The existing canonical-title repair remains unchanged: translation precedes Story
publication, pending items are excluded, results persist and legacy reports reuse
them. Raw evidence, ranking inputs, v7 schema and frozen Lark payloads are preserved.
Gemini 3.1 Flash Lite remains the only translation model, with original-text fallback.

## Test Environment Correction

The initial follow-up clone inherited `mktemp` mode 0700. Service UID 65534 could
not read source files, producing import/permission failures in migration and
systemd tests. That attempt ended with 855 passed, 17 failed and 6 skipped after
an intentional interrupt. Its scene and logs remain intact.

The replacement clone's newly created parent uses mode 0755 and performs a real
service-UID source-read/import preflight. Production modes, units, `PrivateTmp`,
`ProtectHome`, installer logic and old failure scenes were not modified. Both
copies normalize CRLF to LF before Linux execution.

## Verification

| Scope | Result |
| --- | --- |
| Final Windows Python 3.10 full | 823 passed, 364 skipped; one existing warning; 53.01s |
| Final Windows process module | 9 passed, 8 Linux-only skips |
| Final Linux translation/publication/process focus | 54 passed, 3 Windows-only skips; 7.24s |
| Linux full before final ESRCH helper amendment | 1180 passed, 6 skipped; two dependency warnings; 807.16s |
| Final Linux full after ESRCH amendment | 1181 passed, 6 skipped; two dependency warnings; 629.47s |
| Python 3.12 empty-venv archive installation | 1 passed; one tarfile warning; 116.71s |

Changed-path Ruff and `git diff --check` passed. The final Linux suite includes
13 real systemd quiesce/recovery cases and two real backup-unit cases. Its six
skips comprise three Windows Job Object cases, two opt-in historical pre-fix
reproductions and the opt-in artifact installation, which passed separately.
Final full-suite evidence: `translation-followup-final-linux312.xml` / `.txt`
and `translation-followup-final-windows.xml` under the output directory below.

The install used Python 3.12.3 and SQLite 3.45.1. Locked runtime/build dependencies,
`pip check`, three entrypoint imports outside the checkout, packaged keyword
resources and offline smoke checks passed without creating a runtime database.
Archive SHA256: `1ec3354cab87966d71cea96da84c618cf0390b85f8d7b35729c197d2f2afb75d`.
All 268 packaged Python, SQL and dependency files matched the Windows worktree
after CRLF normalization. The manifest explicitly records `git_dirty=true` and
`clean_candidate=false`; this is packaging evidence, not an immutable release candidate.

Scopes overlap and must not be summed. Existing historical failures remain failures
of their recorded inputs. A model probe or Chinese HTML still does not prove actual
Chinese-title receipt in Lark.

## Evidence And Next Step

Evidence files are retained under ignored `output/phase7-release-20261023/` with
the `translation-followup-` prefix. Keep the original `translation-fix-*` reports.
Linux scenes:

- `/var/lib/trendradar-title-followup-20261023.aKYcAs`: deterministic pre-fix reproduction.
- `/var/lib/trendradar-title-followup-20261023.mdVwEt`: service-UID permission failure.
- `/var/lib/trendradar-title-followup-20261023.YNZE7b`: corrected environment, full/focused
  results and empty-venv artifact installation. `final-focus.*` preserves the actual
  ESRCH failure; `final-esrch-focus.*` contains the final focused pass.

No commit, push, production restart, database mutation, Gemini request or Lark send
was performed in this follow-up. Publishing needs a new exact-commit artifact and
protected deployment, with the Scheduler held for historical backlog inspection
and first collection. Do not rewrite saved batches or resend delivered English posts.
Confirm new Chinese titles through actual recipient receipt after deployment.
Source-health/Podcast/Blog work, 48-hour observation and offsite recovery remain
separate open work. Resume via [HANDOFF.md](HANDOFF.md).
