# Phase 2 Research

**Scope:** Cluster canonical `ContentItem` records into stable, explainable Stories and
rank them without changing the legacy acquisition or reporting contracts.

**Research note:** The delegated research pass completed with a `REVISE` recommendation and was
closed. Its generated artifact is not present in the workspace, so this document records the
locally verified research against the Phase 1 code and the locked Phase 2 context.

## Clustering

Use a pure, deterministic `cluster_items(items, config)` function. Sort inputs by
`(event_time, id)` before processing, where `event_time` is `published_time` or
`collected_at`. Tokenize normalized NFKC titles using Unicode word runs, retain tokens of
at least two characters, and add normalized tags and configured entity keywords as signals.

Generate candidates only within a bounded time window (recommended 24 hours). Two items
may join a cluster when they share an entity keyword or tag and have a title-token Jaccard
score at least 0.35, or when title similarity is at least 0.70 with compatible entities.
Use a stricter merge guard for unrelated entities: if both items have non-empty entity sets
and their intersections are empty, do not merge on title similarity alone. Keep connected
components through a union-find pass, then order clusters by earliest event time and the
lexicographically smallest member ID. An item with no match is a valid singleton cluster.

These rules use only the standard library and keep comparisons bounded by the time bucket;
they are suitable for the small SQLite batches and low-memory VPS described by the project.
Thresholds belong in configuration or a frozen defaults object, not scattered through the
parser.

## Stable Stories

Story identity must not depend on arrival order. For a multi-item cluster, derive an identity
from a deterministic signature of its logical evidence: sorted stable ContentItem IDs,
normalized entity/tag keys, and a deterministic event date bucket. For incremental updates,
look up existing stories by candidate member overlap before creating a new identity. If a new
item matches exactly one existing story under the same clustering rules, retain that story ID
and add membership. If it matches none, create a singleton; if it ambiguously matches more
than one, leave the stories separate and record the item as a new singleton.

Persist immutable `story_id` values and unique `(story_id, content_item_id)` memberships.
Never rewrite an existing ID because a later source arrives. Recompute display fields and
scores from the complete member set, while preserving the ID and prior membership. Process
items in sorted order and use stable ID tie-breakers so repeated runs and reversed input order
produce the same result. Source observations remain evidence through their canonical item;
do not duplicate observations into Story tables unless a report query needs a read-only join.

## Storage V2

Keep `IntelligenceStorage` as the only SQL owner. On opening a Phase 1 database, run a short
forward migration inside a transaction: inspect `PRAGMA user_version`, create the new tables
and indexes with `IF NOT EXISTS`, then set version 2. Refuse downgrades and preserve all v1
tables. The existing WAL, foreign-key, five-second busy timeout, and `BEGIN IMMEDIATE`
transaction settings remain applicable.

Recommended tables are `clusters` (deterministic cluster signature and timestamps), `stories`
(stable ID, title, summary, domain, tags, event time, importance, reasons JSON, generator
version, created/updated timestamps), and `story_members` (story ID, content item ID, ordinal,
first/last seen timestamps, unique pair). A unique story signature can make initial creation
idempotent, but member overlap must be resolved before insertion for incremental updates.
Expose typed methods such as `list_stories`, `get_story`, `upsert_story_batch`, and
`replace_story_memberships` or an equivalent single-batch API. One complete derived batch,
including memberships and ranking fields, must commit atomically; wording/network work must
occur before the transaction. Any failure rolls back derived rows and is caught by the caller.

## Generation And Ranking

The deterministic generator should select the earliest/highest-quality member title as a base,
remove repeated source prefixes, and produce a stable summary from the first non-empty member
content plus a source-count sentence. It must return a usable Story with no external service.
An optional injected Gemini wording client may rewrite only `title` and `summary`; validate
non-empty strings, retain the deterministic values on timeout/error, and never allow the client
to choose identity, members, importance, or source evidence. Core modules must not import
`mcp_server`.

Importance should be a pure function with persisted components and human-readable reasons.
Recommended normalized components are: source diversity (unique logical sources), configured
source reliability, activity/growth (new members and observation count), recency decay, and
configured user-interest token/tag matches. Combine them with explicit weights summing to 1.0,
clamp to a documented range, and use `(importance DESC, event_time DESC, story_id ASC)` as the
complete ordering key. Missing configuration gets deterministic defaults and never raises.

## Integration And Tests

Call the Story service after `persist_adapter_results_best_effort()` has attempted canonical
persistence, passing its canonical items/result. Do not call adapters again. Catch and log all
Story derivation/storage errors so NewsNow, RSS, AI Frontier, legacy SQLite, reports,
notifications, and MCP continue. `INTELLIGENCE_ENABLED=false` bypasses the new path entirely.

Backfill should invoke the same service after each chronological canonical batch, preserve
inclusive date filtering, `--include`, corrupt-database skipping, and `--dry-run`. Dry-run
must use in-memory storage and repeated runs must not add rows.

Tests should cover title/entity/tag/time clustering, singleton and cross-source behavior,
reversed input order, stable IDs and memberships across incremental batches, schema v1 to v2
migration and rollback, atomic membership failure, fallback generation with a failing wording
client, ranking components/reasons/tie-breakers, report escaping/evidence links, runtime
failure isolation/no-refetch, rollback mode, and idempotent backfill. Run the full existing
suite in addition to focused Phase 2 tests.

## Defaults And Risks

Use a 24-hour clustering window, title Jaccard 0.35 for shared entity/tag matches, similarity
0.70 with compatible entities, fuzzy story matching only within the same domain/time bucket,
and a maximum batch comparison size or time buckets to avoid quadratic growth. Keep all
thresholds versioned in Story metadata so later tuning does not silently change historical
interpretation. The principal risks are ambiguous cross-event titles, accidental story splits
when source order changes, and a derived-write exception leaking into legacy acquisition;
stable sorting, conservative entity guards, atomic writes, and a best-effort integration
boundary address those risks.

## RESEARCH COMPLETE
