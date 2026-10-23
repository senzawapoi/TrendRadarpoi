# Codebase Concerns

**Analysis Date:** 2026-10-23 (workspace reconciliation; no live recheck)

## Tech Debt

**Transitional canonical and legacy paths:**
- Issue: the main crawler and AI Frontier now write canonical `ContentItem` data while retaining their legacy models, databases, filters, reports, and notifications.
- Files: `trendradar/__main__.py`, `trendradar/ai_frontier/`, `trendradar/intelligence/`, `trendradar/sources/`.
- Impact: stage-order or projection changes can make canonical state diverge from user-visible legacy output.
- Fix approach: keep explicit adapter/rollback parity tests, migrate one downstream consumer at a time, and retain observations as audit evidence.

**Large, mixed-responsibility modules:**
- Issue: storage, MCP analytics, notification, HTML rendering, and entry-point modules contain hundreds to thousands of lines.
- Files: `trendradar/storage/local.py`, `trendradar/storage/remote.py`, `mcp_server/tools/analytics.py`, `trendradar/report/html.py`, `trendradar/integrations/feishu/`, `trendradar/__main__.py`.
- Impact: broad regression surface, duplicated local/remote logic, and difficult targeted testing.
- Fix approach: extract stable application/domain services around behavior, not mechanical file splitting.

**Release metadata and installation evidence:**
- Issue: `requirements.lock` and `build-requirements.lock` pin runtime/build tools. The uncommitted translation repair passed local full regression and a Python 3.12 empty-venv archive install; a new exact-commit release artifact and protected deployment are still required. The tested archive explicitly records a dirty source tree.
- Files: `requirements.txt`, `requirements.lock`, `build-requirements.lock`, `pyproject.toml`, `version`.
- Impact: passing source tests or installing a development venv does not prove the published artifact works outside the checkout.
- Fix approach: retain dependency parity tests, verify locked artifact installation and single-source version metadata in scoped future work.

## Known Bugs

**Phase 7 acceptance remains incomplete:**
- Evidence: [current handoff](../../docs/phase7-release-20261023/HANDOFF.md) separates the deployed release from the local title repair. Chinese-title Lark receipt, source-health issues, continuous observation and offsite recovery remain open. The historical repairs below keep their original evidence scope.
- Files: `tests/deployment/test_systemd_contract_linux.py`, deployment installer, health and restore operations.
- Resolved test-environment issue: the dedicated service interpreter now runs from `/var/lib`, retaining `PrivateTmp=yes`; both earlier `203/EXEC` backup cases pass.
- Repaired failure: service UID65534 could not read the root-owned 0600 restore guard during RG-03 rollback confirmation. Service-identity restore/activation, lease renewal and strict-false confirmation pass final v6 regression, including all 11 real quiesce cases; original failure retained.
- Repaired defect: ENV-03 loader now opens CONFIG_PATH before maintenance. Its 48-test Linux follow-up and the later deployment-only regression (466 passed/6 skipped) passed. The earlier 26-pass/1-failure report remains historical evidence.
- Repaired clean-environment finding (2026-10-22): Windows manifests declare tzdata and lock pins 2026.2. Frozen v6 isolated Windows full: 683 passed, 342 explained platform/opt-in skips, two upstream warnings. Global unrelated dependency conflicts remain untouched.
- Repaired clock-step finding: an installer run rejected its fresh controller record after a 1.706797-second wall-clock reversal. New records use same-boot CLOCK_BOOTTIME for the unchanged 15-second lease, retaining PID/start/boot fences and strict legacy UTC behavior. Final Linux full: 1019 passed/6 explained skips/two upstream warnings, exit0.
- Repaired process-helper race (2026-10-23): exiting children can raise FileNotFoundError or ProcessLookupError while reading `/proc`; cleanup can race exit before signalling. Eight regressions now cover these cases without suppressing permission errors. Final-source Linux full passed 1181/6 skipped, including 13 real quiesce/recovery and two backup-unit cases. Retain the original race and service-UID permission-failure scenes.

**Translated-title publication:**
- Observed defect: Chinese legacy HTML coexisted with English canonical/Story titles; the Scheduler froze the post before translation completed.
- Local repair: persist canonical title resolution before publishing Stories and reuse it in reports; pending items cannot enter Story context.
- Remaining risk: historical unregistered Stories outside the feed window are not automatically repaired. Do not rewrite saved payloads or resend delivered posts. Actual localized receipt remains open.

**Static-analysis baseline fails:**
- Symptoms: full-tree Ruff has legacy violations; scoped checks passed at Phase 5 closeout.
  Re-run the command below for a current count rather than relying on an older snapshot.
- Files: notably `mcp_server/services/`, `mcp_server/tools/`, and legacy report/storage modules.
- Trigger: `python -m ruff check trendradar mcp_server tests`.
- Workaround: run Ruff on changed files as a ratcheted baseline; do not bury feature work in a repository-wide style rewrite.

## Security Considerations

**Assistant capability boundary:**
- Risk: future transports could bypass `AssistantService` or add generic tools that weaken Phase 4's local-read-only contract.
- Files: `trendradar/ai/assistant.py`, `trendradar/ai/tools.py`, and `trendradar/integrations/feishu/`.
- Current mitigation: immutable static schemas, principal-scoped sessions, exact permissions, bounded
  results, server-built citations, and a three-call turn limit are covered by offline tests.
- Recommendations: keep Feishu and other interfaces thin; never register file, shell, dynamic
  import, crawler, arbitrary URL, MCP-dispatch, or unbounded network capabilities.

**MCP capability exposure:**
- Risk: MCP includes config inspection, storage sync, and crawl-triggering tools without application-level authentication.
- Files: `mcp_server/server.py`, `mcp_server/tools/system.py`, `mcp_server/tools/storage_sync.py`.
- Current mitigation: Docker Compose binds published ports to loopback and stdio is local by design.
- Recommendations: preserve loopback/private binding, add authentication before remote HTTP exposure, minimize tool grants, and avoid returning tracebacks to untrusted callers.

**Feishu live acceptance and SDK coupling:**
- Risk: real tenant permissions, bot membership, image handling and long-connection behavior are
  not proven by offline fixtures; the bridge relies on private hooks in pinned `lark-oapi==1.7.3`.
- Files: `trendradar/integrations/feishu/client.py`, `handler.py`, `media.py`, and `transport.py`.
- Current mitigation: opt-in runner, deny-by-default identity/chat checks before payload/media/provider
  access, bounded queue/images/reconnects, durable duplicate suppression and delivery checkpoints.
- Recommendations: preserve recorded text/image/reconnect evidence, finish remaining acceptance and revalidate every SDK upgrade.
  Provider acceptance followed by a crash before local persistence remains an uncertain-outcome
  window; local idempotency does not guarantee external exactly-once model calls or sends.

**Optional research and process boundaries:**
- Risk: installed upstream tools, envelopes and network behavior may diverge from offline fixtures.
- Files: `trendradar/research/`, `trendradar/ai/tools.py`.
- Current mitigation: opt-in ResearchGateway with five named capabilities, bounded inputs/output/timeouts, isolated GitHub credentials and no model-selected shell/executable.
- Recommendations: retain allowlist and failure-isolation tests; verify each upstream route before enabling it on the VPS. Offsite subprocess tests pass in the final Linux suite after the helper repair. Real offsite acceptance remains separate.

## Performance Bottlenecks

**Synchronous main pipeline:**
- Problem: collection, translation, storage and rendering are sequential/blocking stages; first-pass translation now covers all fresh AI Story candidates, beyond the report cap.
- Files: `trendradar/__main__.py`, `trendradar/crawler/fetcher.py`, `trendradar/ai_frontier/__main__.py`.
- Cause: requests plus explicit sleeps and monolithic orchestration.
- Improvement path: retain bounded concurrency only at I/O fan-out boundaries; measure memory and provider limits before parallelizing Gemini or push calls.

**Whole-collection in-memory processing:**
- Problem: ranking, rendering, and MCP analytics load broad result sets and build large dictionaries/strings.
- Files: `trendradar/core/analyzer.py`, `mcp_server/tools/analytics.py`, `trendradar/report/html.py`.
- Cause: batch-oriented data flow without pagination or streaming.
- Improvement path: the Assistant already uses bounded SQLite windows and persisted Story ranking;
  apply equivalent bounds before extending broad legacy analytics.

## Fragile Areas

**SQLite compatibility and partitioning:**
- Files: `trendradar/storage/schema.sql`, `trendradar/storage/rss_schema.sql`, `trendradar/storage/local.py`, `trendradar/ai_frontier/storage.py`, `trendradar/intelligence/storage.py`.
- Why fragile: date-partitioned news/RSS, long-lived AI Frontier, and canonical intelligence databases coexist with different identity and reader contracts.
- Safe modification: use versioned migrations, preserve old schemas/readers, back up databases, and test canonical plus legacy behavior together.
- Test coverage: legacy schemas and additive unified migrations through v7 are covered. Local restore has recorded evidence; S3 parity and offsite recovery remain separate gaps.

**Incremental notification behavior:**
- Files: `trendradar/intelligence/pipeline.py`, `trendradar/intelligence/translation.py`, `trendradar/integrations/feishu/instant.py`.
- Why fragile: first-crawl detection, translated title write-back, grouping, and push suppression depend on stage ordering and persisted state.
- Safe modification: capture current behavior with characterization tests before extracting pipeline stages.
- Test coverage: pending publication, metadata rollback, ranking, report reuse and saved-retry invariants have focused coverage; live translated-title receipt remains open.

**HTML and provider payload rendering:**
- Files: `trendradar/report/html.py`, `trendradar/integrations/feishu/post.py`, `trendradar/integrations/feishu/instant.py`.
- Why fragile: HTML and Lark native posts have different escaping, chunking and immutable-snapshot contracts.
- Safe modification: retain native-post/link-label fixtures and unchanged retry payloads; provider acceptance still needs recipient evidence.

## Scaling Limits

**Small VPS runtime:**
- Current capacity: the task target is one CPU core and about 1.87 GB RAM.
- Limit: concurrent Feishu sessions, Gemini calls, research subprocesses/services, and large in-memory analytics can exhaust memory or stall one event loop.
- Scaling path: use bounded queues/semaphores, SQLite WAL with short transactions, strict context/result limits, and separate failure domains before adding infrastructure.

**GitHub Actions persistence:**
- Current capacity: production uses VPS SQLite and hourly local snapshots; manual Actions diagnostics may still use mutable caches.
- Limit: caches are not a transactional database backup and can expire or restore stale state.
- Scaling path: configure and verify offsite storage separately; local backups and Actions caches do not protect against host loss.

## Dependencies at Risk

**Public scraping endpoints:**
- Risk: Nitter instances, YouTube handle pages, GitHub/official blog markup, and NewsNow can change, throttle, or disappear.
- Impact: source-level gaps and malformed entries.
- Migration plan: keep source isolation, fixtures for known markup, configurable endpoints, timeouts, and graceful empty-result reporting.

**Locked dependencies and artifact verification:**
- Risk: runtime/build lock files exist, but a passing development install does not establish a clean artifact install or current CI execution.
- Impact: checkout-relative imports or packaging omissions can still break an installed release.
- Migration plan: preserve earlier install and deployed artifact evidence; repeat exact-commit install/manifest checks for the next repair release.

## Remaining Milestone Features

**Feishu production acceptance:**
- Problem: Windows and VPS have separate text/image/recovery/receipt evidence. Chinese-title delivery remains open and B6 retains its accepted skipped branch; do not turn these into a blanket pass.
- Blocks: claiming full live or Linux production acceptance. Research is implemented offline and remains opt-in; its live providers require separate verification.

**Research, deployment, and release gates:**
- Problem: recorded deployment predates the locally validated translation repair. Its release and localized receipt, source health, 48-hour observation and offsite recovery remain open. Research providers remain independently opt-in.
- Blocks: full Phase 7 acceptance; follow the current 07-06 handoff.

## Test Coverage Gaps

**Main crawler and storage:**
- What's not tested: complete live hot/RSS orchestration, local/S3 parity, incremental report selection, and provider delivery.
- Risk: later consumer migration can silently change current reports and push behavior even when canonical tests pass.
- Priority: high; extend characterization tests before replacing any legacy reader.

**MCP and Lark delivery:**
- What's not tested: tool contracts, HTTP transport security, provider payload limits, partial sends, and error redaction.
- Risk: regressions reach external clients/providers without CI detection.
- Priority: high before wider MCP exposure or changes to Lark payload contracts; retain SDK fixtures and separate live acceptance.

**CI quality gates:**
- Remaining boundary: Phase 7 has recorded GitHub deployment evidence, but root/systemd fixtures still require privileged execution. A green unprivileged run does not cover them or establish comprehensive security scanning.
- Risk: a green unprivileged run can omit required Linux/systemd acceptance.
- Priority: add isolated execution of privileged cases and retain real CI evidence before release acceptance.

---

*Concerns reconciled: 2026-10-23; recorded deployment is not a current live health check.*
