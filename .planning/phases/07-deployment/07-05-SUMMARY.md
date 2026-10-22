# 07-05 Local Remediation Summary

Date: 2026-10-22, Asia/Shanghai. Authorized local work is complete; the overall
deployment plan remains open for clean-candidate and target acceptance.

## Delivered

- Completed H1-A..D: six real role entrypoints after valid completion,
  crash-generated pending fences, public maintenance clear and dual-database/
  release identity invariants. Their focused 22-pass result is retained and
  assertions are mapped to final execution.
- Declared/pinned Windows tzdata and repaired UTC-step-sensitive controller
  leases with same-boot CLOCK_BOOTTIME, retaining the 15-second bound,
  PID/start/boot/release checks and strict legacy-record behavior.
- Corrected test-only diagnostic/heartbeat/modern lease fixtures without
  changing production readiness rules, weakening assertions or expanding skips.
- Bound all 28 original scenarios to reviewed assertions and final JUnit.

## Final Evidence

Dirty main, HEAD `5a427aba5ded0c9c9c9e050413dcb41f17fa0e23`.
The v6 manifest binds 301 source/resource files plus 12 separate constraints.
All source hashes and corresponding installed archive members match.

| Scope | Result | Exit |
| --- | --- | --- |
| Isolated Windows full tests | 683 passed, 342 skipped, 2 warnings, 46.20s | 0 |
| Isolated Linux full tests | 1019 passed, 6 skipped, 2 warnings, 1060.42s | 0 |
| Separate actual empty-venv dirty install | 1 passed, 41.23s | 0 |

Linux full includes 11 real systemd quiesce and 2 backup-unit cases with actual
service UID65534 and PrivateTmp. Every skip and warning is explained. Eight
changed Python paths pass Ruff; 253 ASTs pass. No test session is active.
Overlapping counts must not be added.

## Open Gates

27 PASS, 1 BLOCKED: RG-04 requires an authorized clean committed candidate.
G1 PASS; G2 BLOCKED; G3/V-01..06 NOT_RUN/BLOCKED. Real GitHub execution,
DEPL-01..05 target/operations evidence, 48 hours/two daily windows and Phase5
C3/C4 remain open. B6 non-whitelisted branch remains an accepted skip.

No commit, push, workflow execution, production deployment, real provider or
remote restic action. Runtime state, failures, caches and toolchains retained.

Full commands, artifact SHA, provenance, limits and next actions:
[final report](../../../docs/phase7-actual-gap-evidence/verification-20261022.md),
[case results](../../../docs/phase7-actual-gap-evidence/case-results-20261022.json),
[handoff](../../../docs/phase7-actual-gap-evidence/HANDOFF.md).
