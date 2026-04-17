"""AI 前沿资讯聚合子系统

独立聚合 ArXiv/Reddit/HackerNews/GitHub Trending/X(nitter) 五大源，
复用 TranslationService + notification senders，独立存储与推送。
"""

from trendradar.ai_frontier.sources.base import AIItem, AISource, SourceType

__all__ = ["AIItem", "AISource", "SourceType"]
