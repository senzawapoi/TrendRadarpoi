# Phase 7 Current Handoff

Owner scope amendment (2026-10-29): temporarily suspend Reddit and X/Nitter; retain their definitions and history. Remove only their required-source entries in the external production configuration, keep all other readiness requirements, and reintroduce both sources only after access is verified. See [source suspension plan](../plans/2026-10-29-temporary-source-suspension.md). This decision permits controlled recovery; it does not establish recovery success.

Updated 2026-10-29 (Asia/Shanghai). Application repair `a20f2d8` is committed,
pushed and merged via PR 9. Its initial deployment readiness failure is retained
in the [historical deployment checkpoint](../handoff/DEPLOY-A20F2D8-20261028.md).
Current operational evidence and active work are in local
`output/DEPLOY-CONTINUATION-20261028.md`; re-read that file and live units before
acting. Historical maintenance snapshots must not be treated as current state.
Full Phase 7 acceptance remains open.

## Workspace And Release

- Recovery worktree: `C:/Users/DELL/Desktop/TrendRadarpoi-deploy-checkpoint-20261027`,
  branch `fix/phase7-source-scope-20261029`, based on PR 10 merge `31ce870`.
- The original repair, handoff and dirty workspaces remain retained.
- PR 9 merged as `241cefb`; its tree equals `a20f2d8`. PR 7 remains OPEN on the
  Phase 7 branch, with base master. Do not merge it automatically.
- Original application CI run `40089562197` passed all four jobs. Deployment run
  `40493521142` validated the exact clean archive, then failed readiness on VPS.
- The original failed transaction crossed the business boundary; retain its archive
  and follow current operational evidence. Automatic database rollback is forbidden.
- Recovery controller changes are published in PR 10. Permission fix `19f4f14` passed
  1504 Linux checks / 6 skips and all four CI jobs. Sequencing fix `5a46399` passed
  160 focused checks, 1517 canonical tests / 6 skips and four CI jobs. Read the latest local
  `output/DEPLOY-CONTINUATION-20261028.md` before operating production. Historical
  runtime details below are snapshots, not a live-status API.

## Translation Defect And Deployed Repair

The five English headlines reported by the owner matched completed batch
`24919e617da1985b94338dfacbe393d0`. The post was sent at 05:41:58.939 UTC;
RSS translation finished at 05:42:44.290 UTC. Chinese HTML did not establish
Chinese Story delivery: canonical records, Stories and the frozen post lacked
translated titles at that time. This was the pre-fix production failure, not the
current status.

Commit `28e7283` resolves canonical titles before Story publication.
`pending` items cannot enter clustering context; atomic metadata updates preserve
raw evidence and observation counts. Successful results survive restart, and
legacy reports reuse the same result. AI Frontier resolves all fresh Story
candidates, including those beyond the HTML limit. Story display uses localized
titles while original ranking input and identities remain stable.

The owner later confirmed that newly generated Chinese titles and links arrived in
Lark after deployment run `39921046202`. Translation stays on
`gemini-3.1-flash-lite`; failures retain original text.
At 19:41 on 10-23, the owner reported further untranslated Yahoo Finance and other
headlines. Read-only inspection now links 21 English headlines across the 19:41
and 19:42 frozen posts to `GEMINI_SERVER_ERROR` followed by `GEMINI_COOLDOWN` at
11:36:53 UTC. The collector logged 21 terminal fallbacks before Story publication.
Ten corresponding Stories had later translated metadata when inspected; eleven
still retained fallback metadata. Later recollection does not update sent messages.
No publication-race recurrence is evidenced here. Provider reliability and future
Chinese-title receipt remain live acceptance work; historical batches must stay frozen.
The median/average regression guard is narrow, not a general semantic guarantee.
Schema remains v7, with no new dependency or changes to saved delivery snapshots.
See [translation contract](../intelligence.md#title-translation-before-publication)
and [deployment procedure](../deployment.md#title-translation-release).

## Historical Verification Of The Repair

| Scope | Recorded result |
| --- | --- |
| Final Windows Python 3.10 full | 823 passed, 364 skipped; one existing warning; 53.01s |
| Final Linux Python 3.12 full | 1181 passed, 6 skipped; two dependency warnings; 629.47s |
| Final Linux translation/publication/process focus | 54 passed, 3 Windows-only skips; 7.24s |
| Python 3.12 empty-venv archive installation | 1 passed; one tarfile warning; 116.71s |
| Changed Python Ruff / diff whitespace | Passed |

The process-helper race is fixed with eight regression cases. Direct `/proc` reads
handle a process disappearing before or during the read; cleanup tolerates exit
before signalling, while permission errors still fail. Final Linux validation
includes 13 real systemd quiesce/recovery cases and two backup-unit cases. Six skips
are three Windows-only cases, two historical opt-in reproductions and the separately
passed installation test. Scopes overlap; do not sum their counts.

The archive installation verified pinned dependencies, `pip check`, imports outside
the checkout, packaged resources and offline smoke checks. All 268 packaged Python,
SQL and dependency files match the worktree after CRLF normalization. Its manifest
records `git_dirty=true`, `clean_candidate=false`; it is not a committed release.

Earlier failures remain retained: the original full run stopped after 470 passes
at the `/proc` race; the first copy had CRLF installer failures; a follow-up copy
had service-UID permission failures because its parent was mode 0700. Only the new
test directory permissions were corrected. Production permissions and installer
logic were unchanged. See [follow-up evidence](TRANSLATION-FOLLOWUP.md).

## Resume Order

1. Resume from this branch and the local operational continuation. Re-read active
   work, transaction archives and unit states before any production action.
2. Continue the recorded operation, not an old recovery command. Use fixed trusted
   entries; never forge controller identity or remove pending records.
3. Require exact-release readiness/finalization, live heartbeat checks and unchanged
   historical-message fingerprints. Then perform real quote/tool and new-title UAT.
4. Keep source stability, long collector lock starvation, Podcast/Blog recovery,
   resource observation, 48 healthy hours and offsite backup/recovery separately open.
   Preserve the accepted B6 skip.

Earlier records include VPS text/image replies, Story receipt, reconnect and local
restore checks. Those observations do not close the translated-title gate or prove
current live health. Phase 7 overall acceptance remains open.

## Evidence And Retention

The ignored directory `output/phase7-release-20261023/` retains `ACCEPTANCE.md`,
`REVIEW-20261023.md`, `UPDATE-8fc8f82.md`, `TRANSLATION-REPAIR-20261023.md`,
`translation-fix-windows.xml` and `translation-fix-linux312-{full,focused,crlf}`
XML/log files. These are local audit evidence, not bundled release resources.
The `translation-followup-*` reports add final Windows/Linux, process, reproduction
and artifact-install results; `TRANSLATION-FOLLOWUP.md` records their conclusions.
This tracked handoff keeps evidence discoverable without committing runtime data.

Retain `.superpowers/sdd/07-06-PLAN/progress.md`, original worktree/UAT files and
both Linux scenes `/var/lib/trendradar-title-20261023.irC26N` and
`/var/lib/trendradar-title-20261023.5lf2Jh`, plus the follow-up scenes listed in
[TRANSLATION-FOLLOWUP.md](TRANSLATION-FOLLOWUP.md). Preserve database WAL/SHM, reports,
credentials and historical deployment/restore transactions. Only verified ignored
Python, pytest and Ruff caches are disposable.

## Workspace Cleanup

The 2026-10-23 cleanup reconciled current guides and archived the former planning
state without changing the 14 existing repair Python files (SHA256 checked).
It identified 38 ignored cache directories, 437 files, 5,210,948 bytes, outside
protected runtime/evidence paths. Automatic approval review rejected deletion
with `blocked by policy`; no caches were removed or alternate deletion attempted.
Documentation links and diff whitespace were checked. No application test rerun,
provider call, live restart or deployment was needed for these documentation edits.

## Source Scope Candidate Validation (2026-10-29)

Configuration candidate `8a7ef3c` changes only the Reddit/X enabled booleans.
Source/health checks: 114 passed. Git-blob-verified native Linux installer/input
checks: 177 passed. CI run `40816038495`: four jobs passed. Native canonical
regression: 1516 passed, 1 failed, 6 skipped; the all-writers systemd fixture hit
SQLite `unable to open database file`. Its unchanged isolated rerun passed, but
root cause remains unresolved and the original failure is retained. This is not
a fully green local regression. PR 11 remains DRAFT / OPEN; do not auto-merge.
See local `output/source-scope-validation-20261029.json` for exact evidence.
