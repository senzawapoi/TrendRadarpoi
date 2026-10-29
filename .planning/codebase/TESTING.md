# Testing Patterns

**Analysis Date:** 2026-09-12 (execution guidance reconciled 2026-10-24)

## Test Framework

**Runner:**
- pytest, available in the current environment but not declared in `pyproject.toml` or `requirements.txt`.
- Config: none; pytest uses default discovery.

**Assertion Library:**
- Native Python `assert` statements and `pytest.raises`.

**Run Commands:**
Use Ubuntu WSL/Linux and a native filesystem checkout for routine regression.
Production targets Python 3.12; retain Python 3.10 compatibility in CI. Existing
Windows UAT evidence is historical, not a requirement to repeat native Windows tests.

```bash
python -m pytest tests -q
python -m pytest tests/ai -q
python -m pytest tests/ai_frontier -v
python -m pytest tests/intelligence -q
python -m pytest tests/integrations/feishu -q
python -m pytest tests/baseline -q
python -m ruff check <changed-python-paths>
```

The current handoff run passed 1212 tests with 6 skips under WSL Python 3.12;
separate empty-venv archive installation passed after CRLF packaging repair.
See the [validation record](../../docs/handoff-validation-20261024.json) for scope,
source fingerprints and remaining gates. The old-tree tool/quote patch is
[preserved separately](../../docs/handoff/deferred-lark-repair.md), not part of that run.

## Test File Organization

**Location:**
- Tests are grouped under `tests/ai/`, `tests/ai_frontier/`, `tests/intelligence/`,
  `tests/integrations/feishu/`, `tests/research/`, `tests/deployment/` and `tests/baseline/`.
- Main orchestration, unified/legacy SQLite, Story, Security, Gemini, Assistant, and Feishu have focused
  offline coverage; most notification providers, MCP behavior, live providers, and S3 parity remain
  largely untested.

**Naming:**
- Files use `test_<module>.py`; functions use `test_<behavior>()`.

**Structure:**
```text
tests/
├── ai/
│   ├── conftest.py
│   ├── test_gemini_client.py
│   ├── test_assistant.py
│   ├── test_retrieval.py
│   └── test_tools.py
├── ai_frontier/
│   ├── test_<source>.py
│   ├── test_fetcher.py
│   ├── test_storage.py
│   ├── test_detector.py
│   ├── test_renderer.py
│   └── test_main.py
├── intelligence/
│   ├── test_models.py
│   ├── test_normalization.py
│   ├── test_adapters.py
│   ├── test_deduplicate.py
│   ├── test_storage.py
│   ├── test_integration.py
│   └── test_backfill.py
├── integrations/feishu/
│   ├── test_handler.py
│   ├── test_idempotency.py
│   ├── test_client.py
│   └── test_delivery.py
└── baseline/
    ├── test_entrypoints.py
    └── test_storage_compatibility.py
```

## Test Structure

**Suite Organization:**
```python
def _item(source="arxiv", url="https://u1"):
    return AIItem(source=source, source_name=source, title="t", url=url)


def test_dedupe_items_by_source_and_url():
    out = dedupe_items([_item(url="https://u1"), _item(url="https://u1")])
    assert len(out) == 1
```

**Patterns:**
- Small factory helpers create focused domain records.
- Each test exercises one behavior with direct assertions.
- Temporary SQLite databases use the pytest `tmp_path` fixture.
- Network parsers are tested with embedded representative payloads instead of live requests.

## Mocking

**Framework:**
- pytest `monkeypatch`; occasional lightweight fake callables/classes.

**Patterns:**
```python
def test_resolve_prefers_env(monkeypatch):
    monkeypatch.setenv("BARK_URL", "https://example.invalid/key/")
    assert resolve_value()
```

**What to Mock:**
- HTTP responses, environment variables, provider clients, wall-clock boundaries, and notification delivery.

**What NOT to Mock:**
- Pure parsers, deduplication/ranking functions, SQLite schema/upsert behavior, and domain serialization.

## Fixtures and Factories

**Test Data:**
```python
@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "ai.db"
```

**Location:**
- Fixtures are usually local to test modules; `tests/ai/conftest.py` provides shared seeded
  intelligence storage for Assistant tests.
- Keep provider samples in the test file until duplication justifies a `tests/fixtures/` directory.

## Coverage

**Requirements:**
- No target or coverage gate is configured.
- Phase closeout counts and commands are recorded in [the baseline](../../docs/baseline.md);
  [Phase 5 verification](../phases/05-feishu-assistant/VERIFICATION.md) distinguishes offline
  coverage from live acceptance. The existing warning is an upstream OpenTelemetry deprecation.

**View Coverage:**
```powershell
# Coverage tooling is not declared; add it before establishing a coverage command/gate.
```

## Test Types

**Unit Tests:**
- Source parsing, canonical/Story models, normalization, adapters, deduplication, storage/migrations,
  clustering/ranking, security analysis, Gemini, translation, Session, retrieval, citations, tools,
  rendering, and push helpers.

**Integration Tests:**
- Canonical and legacy SQLite schema/upsert round trips use real temporary databases.
- Main/AI adapter selection, rollback, storage degradation, projection, Story/Security processing,
  Assistant tool loops, provider fallback, and backfill are covered without live network calls.
- Feishu tests exercise real core services with fake providers, official SDK request builders,
  event leases/restarts, session ownership, bounded images, reconnect cooldown and daily checkpoints.
- Deployment tests use real temporary SQLite, abrupt subprocess termination,
  fake-restic process trees, and Linux UID/lock checks. Backup-unit tests execute
  under real systemd with `PrivateTmp=yes`; use the retained `/var/lib` toolchain.
  Installer control-flow fixtures simulate pip/venv/systemctl and are not
  artifact-install evidence. Import their harness with relative package imports.
  `test_release_install_linux.py` is opt-in with
  `TRENDRADAR_P7_ARTIFACT_INSTALL=true`; it passed using a dirty artifact, including
  locked installation, `pip check` and outside-checkout smoke. Archived pre-fix
  F-01/F-04 tests ran under `TRENDRADAR_P7_PRE_FIX=true`; keep them separate
  from current-source acceptance. `test_systemd_quiesce_linux.py` uses real
  services/timers and UID 65534, with simulated dependency setup. Its historical
  9-pass/1-failure result was traced to a root-owned restore guard; repaired
  service-identity and expired-lease nodes pass. The 2026-10-22 lease/rollback/
  full real-systemd module focus passes 118 tests. `test_remaining_gap_assertions.py`
  uses actual fixed entry, service UID
  and role subprocesses; its initial Linux agent run returned 26 passed/1 failed
  on unreadable YAML preflight. The repaired loader then passed 48 focused
  Linux tests; deployment-only regression finished 466 passed/6 skipped.
  Historical results do not replace final full-project regression. H1-A..D
  additions passed 22 Linux tests on 2026-10-22. Frozen v6 final full runs:
  Windows 683 passed/342 skipped, Linux 1019 passed/6 skipped, two explained
  upstream warnings each, exit0. Separate real dirty installation: 1 passed.
  Full Linux includes 11 actual systemd quiesce and 2 backup-unit passes;
  installation is separate from mocked installer dependency setup. All 301
  source/resource hashes and archive members match. The final per-case audit
  is 27 PASS/1 BLOCKED (clean candidate); every skip is mapped in
  docs/phase7-actual-gap-evidence/skip-audit-v6-20261022.json. No active test
  session; repeat only after relevant changes. No GitHub/VPS acceptance implied.
- No live provider contract tests or notification/MCP end-to-end suite exists.

**E2E Tests:**
- Not used.

## Common Patterns

**Async Testing:**
```python
def test_fetch_all_isolates_source_failures():
    async def run():
        return await fetch_all([ok_source, failing_source])

    assert len(asyncio.run(run())) == 1
```

**Error Testing:**
```python
def test_abstract_source_cannot_be_created():
    with pytest.raises(TypeError):
        AISource({})
```

## Remaining Expansion

- Retain conversion and compatibility tests whenever legacy models, schemas, entrypoints, or source adapters change.
- Retain Story/Security/Gemini/Assistant bounds, migration, authorization, and deterministic fallback
  coverage whenever core services or transports change.
- Preserve Feishu validation, identities, duplicate suppression, sessions, media,
  recovery and delivery coverage. Selected Windows tenant tests have separate
  [live evidence](../phases/05-feishu-assistant/05-LIVE-UAT.md); skipped/pending
  scenarios remain scoped to that record. VPS observations and the local translation
  repair are tracked separately in the current handoff.
- Retain the existing ResearchGateway allowlist/timeout tests and no-shell boundary.
- Phase 7 CI defines pytest, scoped Ruff, dependency checks, artifact building
  and a privileged Linux/systemd job. Follow the [current handoff](../../docs/phase7-release-20261023/HANDOFF.md)
  for recorded deployment and repair validation. The `/proc` test-helper race is
  fixed with eight regression cases. Final Windows: 823 passed/364 skipped; Linux
  Python 3.12: 1181 passed/6 skipped, including 13 real systemd quiesce/recovery
  and two backup-unit cases. Separate empty-venv archive installation: one pass.
  This validates the uncommitted repair locally, not a released artifact or tenant.
- The guarded deployment-rollback API and historical 57-test Bash installer
  suite have passing evidence. The new rollback/readiness/quiesce/assertion
  modules are included in privileged CI; 18 local wiring tests pass, including
  path existence. These are historical scopes; new revisions need their own final
  regression. Local wiring tests alone do not establish GitHub execution.

---

*Testing analysis: 2026-09-12; expansion/status reconciled 2026-10-14.*
