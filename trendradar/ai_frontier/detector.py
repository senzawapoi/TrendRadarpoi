"""AI 前沿增量检测 + 分数过滤

基于 storage.upsert_items 返回的 new_items 做进一步筛选：
- 按源类型应用不同的最低分数阈值
- 按分数排序
- 截断为最多 N 条（推送友好）
"""

from __future__ import annotations

from trendradar.ai_frontier.sources.base import AIItem, SourceType
from trendradar.utils.logging import log


def _source_threshold(push_cfg: dict, source: SourceType) -> int:
    """根据源类型取对应的最低分数阈值"""
    mapping: dict[SourceType, str] = {
        "hackernews": "min_score_hackernews",
        "reddit": "min_score_reddit",
        "github": "min_stars_github",
        "arxiv": "min_score_arxiv",  # 默认 0
        "x": "min_score_x",  # 默认 0
    }
    key = mapping.get(source, "min_score_default")
    return int(push_cfg.get(key, 0))


def filter_new_for_push(
    new_items: list[AIItem],
    push_cfg: dict,
) -> list[AIItem]:
    """对新增条目按阈值过滤 + 按分数降序 + 截断"""
    if not new_items:
        return []

    filtered: list[AIItem] = []
    for item in new_items:
        threshold = _source_threshold(push_cfg, item.source)
        if threshold > 0 and item.score < threshold:
            continue
        filtered.append(item)

    # 综合排序：分数降序，其次发布时间降序
    filtered.sort(
        key=lambda i: (i.score, i.published_at.timestamp() if i.published_at else 0),
        reverse=True,
    )

    max_items = int(push_cfg.get("max_items_per_push", 30) or 30)
    truncated = filtered[:max_items]

    log.info(
        f"推送过滤: 原 {len(new_items)} → 阈值过滤 {len(filtered)} → 截断 {len(truncated)}"
    )
    return truncated


def group_by_source(items: list[AIItem]) -> dict[str, list[AIItem]]:
    """按源分组，返回有序字典：arxiv/reddit/hackernews/github/x"""
    groups: dict[str, list[AIItem]] = {
        "arxiv": [],
        "reddit": [],
        "hackernews": [],
        "github": [],
        "x": [],
    }
    for item in items:
        if item.source in groups:
            groups[item.source].append(item)

    # 清理空分组
    return {k: v for k, v in groups.items() if v}
