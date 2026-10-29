# Phase 7 Remediation Record

This record covers the offline follow-up plan dated 2026-10-13 and the
2026-10-14 actual-gap checkpoint. It does not
claim VPS installation, GitHub Actions execution, remote restic access, live
restore, Lark delivery, or 48-hour operation.

| Item | Offline implementation | Evidence |
| --- | --- | --- |
| P7-R01 | Release package installs the project into its own venv; archive and manifest boundaries are checked | build_release.py, create_manifest.py, release_smoke.sh |
| P7-R02 | Installer stages and persistent transaction record | install_release.sh |
| P7-R03 | Pre-resume snapshot rollback; post-resume failures retain maintenance protection | install_release.sh, deployment.md |
| P7-R04 | One checked-out revision builds one artifact; fixed host-key input | phase7-deploy.yml |
| P7-R05 | Bounded restic process tree and redacted manifest-bound receipt | offsite_backup.py, test_offsite_backup.py |
| P7-R06 | Separate snapshot/upload ages and explicit readiness gate | health.py, test_health.py |
| P7-R07 | Durable multi-database restore journal and recovery status | backup.py, test_restore_recovery.py |
| P7-R08 | Linux/systemd validation scripts and isolated lifecycle checks | v6 Linux full; 11 quiesce/2 backup-unit passes; VPS pending |
| P7-R09 | Runbook and evidence records updated | this document and phase7-acceptance.md |
| P7-R10 | Target environment acceptance | pending host, GitHub Environment and backup credentials |

The table preserves the earlier offline checkpoint, not current release status.
Resume from the [2026-10-23 handoff](phase7-release-20261023/HANDOFF.md).
The historical [actual-gap handoff](phase7-actual-gap-evidence/HANDOFF.md) covers
trusted environment loading, role/source readiness, UID/mode
preservation and transaction guards have new implementation and scoped tests.
Earlier cleanup checks passed 101 Windows tests with 25 platform skips,
120 Linux tests with one Windows-only skip, and a separate 24-test Linux
restore/permissions/systemd scope. Both backup-unit cases now pass with the
interpreter outside `PrivateTmp`; their earlier `203/EXEC` failure is retained
as historical evidence. Fake-restic timeout/descendant tests run on both systems.
Final v6 regression and per-case audit now close the authorized local work:
Windows 683 passed/342 skipped, Linux 1019 passed/6 skipped, two upstream
warnings each, all exit 0. Separate dirty installation passes (1 test).
27 scenarios PASS; RG-04 clean candidate remains BLOCKED. G1 PASS, G2 blocked,
G3/CI/target evidence open. These historical subsets are not final counts.

The latest [workspace checkpoint](phase7-actual-gap-evidence/workspace-cleanup-20261014-post-rollback.md)
adds retained Linux F-01/F-04 reproduction, restore-journal fsync/metadata and
interruption repairs, literal workflow/archive validation, and pinned build tools.
The guarded `backup activate --deployment-rollback` API is now connected and
the Bash installer suite previously passed 57 tests. The historical RG-03
9-pass/1-failure result was traced to service confirmation reading a root-owned
guard. Service-identity restore/activation, bounded lease renewal and strict
business-boundary validation now have
[focused passing evidence](phase7-actual-gap-evidence/rg03-rollback-fix-20261014.json).
The privileged CI scope is wired and its 18 local tests pass; this is not a
GitHub run. P7-R02/R03 now have final local assertion mapping and regression;
this does not accept their behavior on the production target. RG-04 dirty
installation passed; clean candidate and target acceptance remain open.

The remaining Linux assertion scope originally reported 26 passed/1 failed
on ENV-03. The loader now reads `CONFIG_PATH` before invoking the helper; its
48-test follow-up passed, followed by 466 passed/6 skipped in deployment-only
regression. Historical failures remain unchanged. The 2026-10-22 handoff work
adds H1-A..D assertions (22 focused passes), declares/pins Windows tzdata and
uses same-boot boottime controller leases with the unchanged 15-second bound.
Final v6 source/archive hashes match. See the
[final report](phase7-actual-gap-evidence/verification-20261022.md).

The installer recovery marker is updated atomically at every transaction stage
before the per-transaction archive record. It remains present for failed or
interrupted releases and is removed only after the readiness gate succeeds.

The current offline scope uses temporary databases and fake restic output. It
does not use real credentials, model providers, Lark tenants, GitHub deploys,
VPS services or production databases.

Required values for the live stage are the deployment host, port, user, path,
protected host public key, SSH key, GitHub Environment approval, runtime
configuration, backup repository/password access, and an isolated restore
target. Their names may be configured later; their values do not belong in
this repository.
