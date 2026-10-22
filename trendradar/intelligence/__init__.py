"""Unified intelligence data layer."""

from trendradar.intelligence.deduplicate import DeduplicationResult, Deduplicator
from trendradar.intelligence.gemini_wording import (
    GeminiStoryWordingClient,
    build_story_wording_client,
)
from trendradar.intelligence.pipeline import (
    process_content_items,
    process_stories_after_persist_best_effort,
)
from trendradar.intelligence.ranking import (
    RankingConfig,
    RankingEvidence,
    rank_stories,
    score_story,
)
from trendradar.intelligence.storage import (
    ContentObservation,
    IntelligenceStorage,
    SourceRunRecord,
)
from trendradar.intelligence.stories import StoryBatchResult, StoryService

__all__ = [
    "ContentObservation",
    "DeduplicationResult",
    "Deduplicator",
    "GeminiStoryWordingClient",
    "IntelligenceStorage",
    "RankingConfig",
    "RankingEvidence",
    "SourceRunRecord",
    "StoryBatchResult",
    "StoryService",
    "process_content_items",
    "process_stories_after_persist_best_effort",
    "build_story_wording_client",
    "rank_stories",
    "score_story",
]
