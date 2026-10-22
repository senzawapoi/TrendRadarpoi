# 07-04 Summary

Implemented the operator-facing deployment and recovery material:

- `docs/deployment.md` covers layout, secrets, role operation, release,
  snapshot, isolated restore and guard handling.
- `docs/phase7-acceptance.md` records offline evidence and the VPS acceptance
  form without claiming live success.
- `docs/README.md` links the runbook and separates offline readiness from VPS
  deployment.
- `maintenance enter/status/clear` provides a persistent restore guard; health
  reports `maintenance` while it is active.

Evidence: documentation, maintenance, and multi-database restore tests passed.
Operator execution on a disposable Linux target, real restore timing, RPO/RTO,
restic transfer, and continuous runtime acceptance are still open.

