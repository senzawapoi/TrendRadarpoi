# Phase 7 Candidate: 2026-10-23

This record belongs to the new candidate branch, not the earlier frozen v6 audit.
Base master: `d5e50ac105165bc009e6fc8304cd8298fc9fbb8c`, merged PR #6.
Branch: `fix/phase7-lark-routing-20261023`. No new candidate commit or production
activation has been accepted yet. The implementation is being frozen for a new PR;
commit-bound Linux/CI evidence will be appended separately without rewriting this
pre-freeze record. Follow [07-06](../../.planning/phases/07-deployment/07-06-PLAN.md).

## Finalize Diagnosis

The original scene `/var/lib/p7-quiesce-fumhoz_h` remains preserved. Five bounded
fresh reproductions of its normal case passed; that alone did not establish a cause.
A directed real-systemd test demonstrated a race: health sampled wall time before
reading files, while active role writers published later heartbeats. Finalize then
rejected these as `future_heartbeat`. The failing directed scene is preserved at
`/var/lib/p7-quiesce-lo0llstn`.

Sampling time after each heartbeat read fixed the identical directed test
(1 passed, 21.35s). Diagnostics now include sanitized health reason codes and exit
status. The historical generic failure lacks enough evidence to prove that this
was its only cause. New regression still rejects genuinely future timestamps.

The subsequent full Linux run exposed another `future_heartbeat` failure in
`/var/lib/p7-quiesce-5iapt3sp` even after moving the wall-clock sample. A read-only
60-second clock probe recorded **two backward UTC jumps: 1.062852247s and
1.107148072s**. The new repair records Linux boot identity plus CLOCK_BOOTTIME in
heartbeats and uses that clock for same-boot freshness. Old UTC-only records retain
strict UTC validation; malformed, cross-boot, future and stale boot clocks fail closed.
UTC timestamps remain audit fields. This addresses an observed clock condition,
without claiming a conclusive cause for the older scene lacking diagnostics.

## Completed Checks

- Local/offsite readiness and finalize regression: 26 passed.
- Entrypoint, settings, AI Frontier and Story wording integration: 114 passed,
  one existing OpenTelemetry deprecation warning.
- Python 3.12 Linux dependency installation: exact locks installed; pip check passed.
- Linux 3.12 CI selection, resource contract, retention and diagnostic focus:
  33 passed. This predates the latest retention review fixes.
- Retention review fixes: Linux 3.12 focus finished with 16 passed/61 deselected,
  including 10 retention cases and affected installer/environment checks. Directory
  deletion is anchored to no-follow descriptors; Windows conservatively skips pruning.
  Scoped re-review passed. Corrupted manifests and changed protection are preserved.
- The initial broader Linux 3.12 run had 100 passed/4 failed: incomplete v7 fixture
  synchronization and stale current-schema assertions. The affected cases passed after
  integration. Final frozen full regression is still required.

These scopes overlap and must not be summed. Model review identified cooldown and
long-input evidence issues; both fixes passed scoped re-review. Instant-delivery
mode normalization and backup-retention fixes also passed scoped re-review.

Windows full regression: **771 passed, 355 skipped**, 48.62s, one existing
OpenTelemetry deprecation warning. The first Linux full regression finished with
**1117 passed, 4 failed, 5 skipped**, 703.88s, three dependency/runtime deprecation
warnings. Two failures were assertions comparing successful schema7 migration
with pre-migration schema6; one was a delayed SQLite checkpoint from an unclosed
harness connection; one was the heartbeat UTC-clock issue described above.
Repair verification is in progress. Windows skips are not Linux evidence.

After the boot-clock repair, Windows full regression: **783 passed, 356 skipped**,
52.14s, one existing OpenTelemetry warning. Changed Python Ruff and known-credential
scan passed. All scoped and final integration reviews passed, including the deployed
keyword resource and restored bilingual configuration/MCP documentation. The new
deployment job installs the exact built archive in an empty Python3.12 venv and
checks its manifest before uploading that same archive.

## Live Provider Probe

Five minimal requests used the documented API key through the same Google endpoint.
No credential, provider error body or user content was persisted.

| Request | Result | Elapsed |
| --- | --- | --- |
| Gemini 3.8 Flash text | HTTP 503, UNAVAILABLE | 5.73s |
| Gemini 3.5 Flash Lite text | HTTP 200, expected reply | 1.09s |
| Gemini 3.1 Flash Lite text | HTTP 200, expected reply | 1.42s |
| Gemma 4 31B text | HTTP 200, expected reply | 25.86s |
| Gemini 3.8 Flash synthetic red image | HTTP 200, correct color | 18.84s |

This verifies individual endpoint availability at the sampled times. It does not
yet verify the final application routing, real Lark delivery or future quota.

A subsequent request through the actual core client encountered a 3.8 Flash
server error and immediately succeeded with 3.5 Flash Lite (expected synthetic
reply, actual model recorded). The independent Gemma translation request received
a server error and returned the original sentence with its number intact. Thus
live inference failover and translation failure preservation were observed;
successful application-level translation was subsequently observed at
2026-10-23T02:52:04Z: Gemma returned Chinese text with the synthetic number31
preserved (20.875s). No real user content was used in these probes.

## VPS Read-only Preflight

Authenticated access through the user-supplied BAT succeeded. Ubuntu host reports
Python 3.12.3, SQLite 3.45.1, one CPU, 1,225,892 kB available memory and
11,709,485,056 bytes free disk. Existing website and proxy services were running.
No TrendRadar units or application roots were present. No target changes were made.

## Open Gates

Complete final integration review and resolve Linux regression failures; run a frozen full suite,
real Linux systemd/install/recovery checks and an empty Python 3.12 archive install.
Then create the new PR without merging, configure protected deployment, and deploy
the validated exact commit/archive. Verify live text/images, new Story receipt,
reconnect and local restore, followed by at least 48 hours of observation.

Local backups only are authorized for this release. Offsite backup and offsite
recovery remain explicitly incomplete. The accepted Phase 5 B6 skip is unchanged.
