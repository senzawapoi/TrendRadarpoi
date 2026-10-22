# Phase 7 Resume Checkpoint

Recorded 2026-10-15, Asia/Shanghai. This is a resume record, not acceptance.

- HEAD: `5a427aba5ded0c9c9c9e050413dcb41f17fa0e23`, dirty `main`, 42 ahead
  of the local `origin/main` record; no fetch performed.
- [Baseline inventory](resume-inputs-20261015.json): 290 production, deployment,
  configuration and test inputs, including untracked files. No credentials or
  runtime databases included.
- Direct inspection: ENV-03 loader opens CONFIG_PATH before executing the
  maintenance helper. Historical [repair evidence](env03-readability-fix-20261014.json)
  records 48 passed, exit 0.
- Historical deployment command terminated with 466 passed, 6 skipped,
  exit 0 in 1083.62s. Parent read that terminal output; it is not current
  full-project evidence and must not be added to overlapping test counts.
- Direct preflight: Windows Python 3.10.11 / SQLite 3.40.1; Ubuntu root,
  systemd, Python 3.10.22 / SQLite 3.53.1. No pytest process found. WSL reports
  its localhost proxy forwarding notice; no provider connectivity tested.
- H1-A..D remain: six-entry positive acceptance after public completion,
  crash-generated pending fences, public clear success, dual-database and
  release identity checks. Strengthen tests first; repair production only
  for an observed contract failure.
- H2 focused tests, H3 frozen full Windows/Linux runs plus dirty installation,
  and H4 case mapping remain to execute.
- External gates: clean committed candidate, actual GitHub run, V-01..06,
  Phase 5 C3/C4. B6 accepted skip remains an exception.

Preserve all dirty work, audit/failed-run evidence, Linux toolchains, output
and test/runtime. No commit/push/deploy, real provider/restic or cache deletion.
