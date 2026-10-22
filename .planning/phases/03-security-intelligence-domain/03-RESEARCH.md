# Phase 3 Research

**Scope:** Add actionable vulnerability intelligence without weakening Phase 1-2 compatibility.

**Delegation note:** Two research agents were launched twice. Both pairs remained running without
returning a result through the bounded waits and explicit finalization requests, so all four were
closed. The findings below come from direct code inspection and live official endpoint checks on
2026-09-04.

## Existing Contracts

- `SourceAdapter` and `AdapterRunner` already provide bounded concurrency, per-item normalization
  isolation, passive health, and `source_runs` persistence.
- `ContentItem` already carries arbitrary JSON-safe metadata, but `SUPPORTED_DOMAINS` must add
  `security`.
- `Deduplicator`, `StoryService`, `rank_stories`, and `IntelligenceStorage` are reusable. Exact CVE
  identifiers need a strong clustering/context rule because the ordinary 24-hour/title heuristic
  cannot reliably join an old CVE with later KEV or news evidence.
- Existing reports and three legacy schemas are compatibility authorities. Security output should
  therefore be additive and use existing observation evidence.

## Official Source Contracts

### CISA KEV

- Catalog: `https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json`
- Live response was HTTP 200 and exposed catalog metadata plus vulnerability fields:
  `cveID`, `vendorProject`, `product`, `vulnerabilityName`, `dateAdded`, `shortDescription`,
  `requiredAction`, `dueDate`, `knownRansomwareCampaignUse`, `notes`, and `cwes`.
- Fetch the bounded JSON document once per run. Reject a non-object/non-list contract, isolate bad
  entries during Normalize, and preserve catalog version/date in record metadata.

### NVD CVE API 2.0

- Endpoint/docs: `https://services.nvd.nist.gov/rest/json/cves/2.0` and
  `https://nvd.nist.gov/developers/vulnerabilities`.
- Live response exposed `resultsPerPage`, `startIndex`, `totalResults`, and `vulnerabilities[].cve`
  with `id`, `published`, `lastModified`, `descriptions`, `metrics`, `weaknesses`, and `references`.
- Query a bounded last-modified window, paginate with `startIndex`/`resultsPerPage`, cap pages and
  items, and optionally send the `apiKey` header. Prefer CVSS v4, then v3.1, v3.0, and v2 data.

### Security RSS

- Reuse the existing RSS parser/fetcher and one-adapter-per-feed convention, but normalize to
  `security:rss:<feed-id>` and extract CVE identifiers from title plus summary.
- The official CISA advisory feed at
  `https://www.cisa.gov/cybersecurity-advisories/all.xml` returned HTTP 200 with RSS XML during
  research. Feed lists remain user-configurable and fixture-tested without live network calls.

## Implementation Guidance

- Use canonical NVD detail URLs for official CVE records so CISA and NVD observations share one
  canonical content identity while preserving their original URLs in observation metadata.
- Treat `CVE-YYYY-NNNN...` case-insensitively as a strong identifier. Add only this exact pattern
  to cross-window clustering/context lookup; do not broaden fuzzy cross-source matching.
- Keep generic Importance as input evidence, then compute a deterministic security score from
  severity/CVSS, KEV status, action/due date, and the base Story score. Persist components/reasons.
- Build freshness from latest `source_runs`: current state, last attempt, last successful or
  degraded fetch, age, stale flag, and bounded error summary.
- No dependency is needed: the repository already has `aiohttp`, `feedparser`, and its shared
  normalization/reporting primitives.

## Risks

- NVD rate limits or schema variations: optional key, bounded pagination, tolerant metric parsing,
  explicit error status, and fixtures for missing metric families.
- Snapshot catalogs can inflate activity: store all canonical evidence but derive/report only a
  configured recent/actionable set per run.
- One article may mention multiple CVEs: retain every identifier in metadata; clustering may join
  related evidence through any exact shared CVE, while explicit conflicting single-CVE records
  stay separate.

