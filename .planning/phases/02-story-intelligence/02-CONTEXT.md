# Phase 2 Context: Story Intelligence

## Boundary

Phase 2 converts canonical `ContentItem` records into stable, explainable event intelligence:

`ContentItem -> Cluster -> Story -> Ranking -> Importance -> Story report`

This path extends local `intelligence.db` and runs best effort beside existing news, RSS, AI
Frontier, report, MCP, and notification behavior. It does not replace legacy outputs in place.

## Locked Decisions

- Cluster, Story, Ranking, and Importance are all Phase 2 deliverables; Story cannot be deferred.
- Clustering uses deterministic time, normalized title/token, entity-keyword, and tag signals.
- Different entities or weakly related events stay separate; unmatched items form single-item Stories.
- Story identity and membership are stable and idempotent when later sources arrive.
- Every Story retains all canonical items and their source observations as evidence.
- Importance combines source diversity, source reliability, activity/growth, recency, and configured
  user-interest matches, with component scores and readable reasons persisted.
- Gemini is optional wording enhancement only. Identity, membership, fallback title/summary, and
  ranking must work offline and remain deterministic.
- Phase 2 adds versioned tables to `intelligence.db`; it does not alter the three legacy schemas.
- Story reporting is additive and local. Existing reports and notifications continue unchanged.
- Processing failures are logged and do not fail acquisition or trigger another upstream fetch.

## Out of Scope

Security sources, shared Gemini client restructuring, chat/session/tool calling, Feishu WebSocket,
Agent-Reach, vector storage, S3 synchronization of `intelligence.db`, and replacement of legacy
reports or notifications remain outside this phase.
