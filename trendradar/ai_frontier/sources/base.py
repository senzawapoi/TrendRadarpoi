"""AI 前沿数据源基类与数据模型"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

SourceType = Literal["arxiv", "reddit", "hackernews", "github", "x", "podcast", "blog"]


@dataclass
class AIItem:
    """AI 前沿资讯条目"""

    source: SourceType
    source_name: str  # e.g. "r/MachineLearning", "ArXiv cs.AI"
    title: str
    url: str
    published_at: datetime | None = None
    score: int = 0  # HN points / Reddit upvotes / GitHub stars
    author: str = ""
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    title_translated: str = ""  # 翻译回填（英文→中文）
    is_new: bool = False  # detector 标记

    def unique_key(self) -> tuple[str, str]:
        """去重键：(source, url)"""
        return (self.source, self.url)

    def to_dict(self) -> dict:
        """序列化为 dict（用于 JSON/存储）"""
        return {
            "source": self.source,
            "source_name": self.source_name,
            "title": self.title,
            "url": self.url,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "score": self.score,
            "author": self.author,
            "summary": self.summary,
            "tags": self.tags,
            "title_translated": self.title_translated,
            "is_new": self.is_new,
        }


class AISource(ABC):
    """AI 前沿数据源抽象基类"""

    source_type: SourceType = "arxiv"  # 子类覆盖

    def __init__(self, config: dict) -> None:
        self.config = config
        self.enabled = config.get("enabled", True)

    @abstractmethod
    async def fetch(self) -> list[AIItem]:
        """异步抓取本源的条目列表"""
        ...

    @property
    def name(self) -> str:
        """数据源可读名称"""
        return self.source_type
