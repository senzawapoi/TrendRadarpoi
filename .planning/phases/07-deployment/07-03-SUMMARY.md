# 07-03 Summary

Implemented reproducible-release and backup tooling:

- `scripts/deploy/build_release.py` creates a deterministic source archive and
  excludes runtime databases, output, test runtime, caches and secrets.
- `scripts/deploy/create_manifest.py` records commit/diff state, package,
  Python/SQLite evidence, dependency hashes, schema range and artifact digest.
- `scripts/deploy/preflight.py` records host facts without provider calls.
- `.github/workflows/phase7-ci.yml` runs pinned-action offline CI, tests, Ruff,
  compile checks and artifact evidence; it does not run a long-lived Bot.
- `.github/workflows/phase7-release.yml` provides a manual/tag-triggered
  release-candidate artifact path; it does not deploy or hold production
  credentials.
- `trendradar.ops.backup` uses SQLite Online Backup API, integrity/foreign-key
  checks, checksums and atomic snapshot directories.
- AI Frontier compatibility storage now uses the configured SQLite synchronous
  policy and has explicit `migrate`/`check` support; production roles can refuse
  an unprepared AI Frontier database.

Evidence: source artifact content audit passed; local multi-database
backup/restore and activation tests passed. GitHub execution, Linux install and
remote restic transfer remain unverified.

