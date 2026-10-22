"""Unified domain models and normalization contracts."""

from trendradar.core.models.compatibility import (
    ai_item_from_content,
    content_from_ai_item,
    content_from_news_item,
    content_from_rss_item,
    news_item_from_content,
    rss_item_from_content,
)
from trendradar.core.models.content import ContentItem, deterministic_content_id
from trendradar.core.models.normalization import (
    canonicalize_url,
    normalize_datetime,
    normalize_identity_title,
    normalize_tags,
    normalize_text,
)
from trendradar.core.models.story import (
    Cluster,
    ImportanceBreakdown,
    Story,
    deterministic_cluster_id,
    deterministic_story_id,
)

__all__ = [
    "ContentItem",
    "Cluster",
    "ImportanceBreakdown",
    "Story",
    "ai_item_from_content",
    "canonicalize_url",
    "content_from_ai_item",
    "content_from_news_item",
    "content_from_rss_item",
    "deterministic_content_id",
    "deterministic_cluster_id",
    "deterministic_story_id",
    "news_item_from_content",
    "normalize_datetime",
    "normalize_identity_title",
    "normalize_tags",
    "normalize_text",
    "rss_item_from_content",
]
