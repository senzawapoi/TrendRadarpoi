"""AI 前沿翻译集成

复用 trendradar.services.translation_service.TranslationService.batch_translate_titles
将英文标题批量翻译为中文，回写到 AIItem.title_translated。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from trendradar.ai_frontier.sources.base import AIItem
from trendradar.services.translation_service import TranslationService
from trendradar.utils.logging import log

if TYPE_CHECKING:
    from trendradar.ai.client import GeminiClient

# 中文/日文/韩文检测（命中则视为非英文，无需翻译）
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]")


def is_english_title(title: str) -> bool:
    """判断标题是否为英文（无 CJK 字符）"""
    if not title or not title.strip():
        return False
    return not _CJK_PATTERN.search(title)


def translate_items(
    items: list[AIItem],
    gemini_api_key: str | None = None,
    batch_size: int = 15,
    *,
    translation_service: TranslationService | None = None,
    gemini_client: GeminiClient | None = None,
) -> int:
    """对 items 中的英文标题做批量翻译，回写 title_translated。

    Args:
        items: 条目列表
        gemini_api_key: Explicit legacy Gemini key. Runtime entry points should inject a shared
            core client instead.
        batch_size: 每批翻译数量
        translation_service: Optional shared compatibility facade.
        gemini_client: Optional shared core client used when a facade was not supplied.

    Returns:
        成功翻译的条目数
    """
    groups: dict[str, list[AIItem]] = {}
    for index, item in enumerate(items):
        canonical_id = str(getattr(item, "_canonical_content_id", f"legacy:{index}"))
        groups.setdefault(canonical_id, []).append(item)
    representatives: list[AIItem] = []
    for group in groups.values():
        representative = group[0]
        existing = next((item for item in group if item.title_translated), None)
        if existing is not None:
            representative.title_translated = existing.title_translated
        representatives.append(representative)

    # 筛选英文标题且未翻译的 canonical 代表条目
    en_indices: list[int] = []
    en_titles: list[str] = []
    for i, item in enumerate(representatives):
        if not is_english_title(item.title):
            continue
        if item.title_translated:
            continue
        en_indices.append(i)
        en_titles.append(item.title)

    if not en_titles:
        log.info("无需翻译的条目")
        return 0

    log.info(f"AI 前沿翻译：{len(en_titles)} 条英文标题")

    try:
        service = translation_service or TranslationService(
            gemini_api_key=gemini_api_key,
            gemini_client=gemini_client,
        )
        if not service.translation_tools:
            log.warning("翻译工具未初始化")
            return 0
    except Exception as exc:
        log.warning("TranslationService 构造失败", error_type=type(exc).__name__)
        return 0

    try:
        translations = service.batch_translate_titles(en_titles, batch_size=batch_size)
    except Exception as exc:
        log.warning("批量翻译失败", error_type=type(exc).__name__)
        return 0

    translated_count = 0
    for idx, trans in zip(en_indices, translations, strict=False):
        if trans:
            representatives[idx].title_translated = trans
            translated_count += 1

    for group in groups.values():
        translated = group[0].title_translated
        for item in group:
            item.title_translated = translated

    log.success(f"AI 前沿翻译完成：{translated_count}/{len(en_titles)}")
    return translated_count
