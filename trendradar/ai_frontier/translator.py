"""AI 前沿翻译集成

复用 trendradar.services.translation_service.TranslationService.batch_translate_titles
将英文标题批量翻译为中文，回写到 AIItem.title_translated。
"""

from __future__ import annotations

import re

from trendradar.ai_frontier.sources.base import AIItem
from trendradar.utils.logging import log

# 中文/日文/韩文检测（命中则视为非英文，无需翻译）
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]")


def is_english_title(title: str) -> bool:
    """判断标题是否为英文（无 CJK 字符）"""
    if not title or not title.strip():
        return False
    return not _CJK_PATTERN.search(title)


def translate_items(
    items: list[AIItem],
    gemini_api_key: str | None,
    batch_size: int = 15,
) -> int:
    """对 items 中的英文标题做批量翻译，回写 title_translated。

    Args:
        items: 条目列表
        gemini_api_key: Gemini API Key（None/空串则跳过翻译）
        batch_size: 每批翻译数量

    Returns:
        成功翻译的条目数
    """
    if not gemini_api_key:
        log.info("未配置 GEMINI_API_KEY，跳过 AI 前沿翻译")
        return 0

    # 筛选英文标题且未翻译的条目
    en_indices: list[int] = []
    en_titles: list[str] = []
    for i, item in enumerate(items):
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
        from trendradar.services.translation_service import TranslationService
    except Exception as e:
        log.warning("TranslationService 导入失败", error=str(e))
        return 0

    try:
        service = TranslationService(gemini_api_key=gemini_api_key)
        if not service.translation_tools:
            log.warning("翻译工具未初始化")
            return 0
    except Exception as e:
        log.warning("TranslationService 构造失败", error=str(e))
        return 0

    try:
        translations = service.batch_translate_titles(en_titles, batch_size=batch_size)
    except Exception as e:
        log.warning("批量翻译失败", error=str(e))
        return 0

    translated_count = 0
    for idx, trans in zip(en_indices, translations, strict=False):
        if trans:
            items[idx].title_translated = trans
            translated_count += 1

    log.success(f"AI 前沿翻译完成：{translated_count}/{len(en_titles)}")
    return translated_count
