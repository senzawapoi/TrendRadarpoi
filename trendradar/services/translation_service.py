"""
翻译服务模块

提供英文新闻标题的自动翻译功能，在数据抓取阶段集成。
支持检测英文标题并调用翻译 API 进行翻译。
"""

import re

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from trendradar.core.exceptions import TranslationError
from trendradar.storage.base import NewsData, NewsItem
from trendradar.utils.logging import log


class TranslationService:
    """翻译服务类"""

    def __init__(self, gemini_api_key: str | None = None):
        """
        初始化翻译服务

        Args:
            gemini_api_key: Google Gemini API 密钥（可选）
        """
        self.gemini_api_key = gemini_api_key
        self.translation_tools = None
        self._init_translation_tools()

    def _init_translation_tools(self):
        """初始化翻译工具"""
        try:
            from mcp_server.tools.translation import TranslationTools
            self.translation_tools = TranslationTools(
                default_source="en",
                default_target="zh",
                gemini_api_key=self.gemini_api_key
            )
            log.info("翻译工具初始化成功")
        except Exception as e:
            log.warning("翻译工具初始化失败", error=str(e))
            self.translation_tools = None

    def is_english_title(self, title: str) -> bool:
        """
        检测标题是否为英文

        判断规则：
        1. 包含中文字符 -> 不是英文
        2. 包含日文字符 -> 不是英文
        3. 包含韩文字符 -> 不是英文
        4. 其他情况认为是英文（需要翻译）

        Args:
            title: 待检测的标题

        Returns:
            bool: 是否为英文标题
        """
        if not title.strip():
            return False

        # 检测中文字符
        if re.search(r'[\u4e00-\u9fff]', title):
            return False

        # 检测日文字符（平假名、片假名）
        if re.search(r'[\u3040-\u309f\u30a0-\u30ff]', title):
            return False

        # 检测韩文字符
        if re.search(r'[\uac00-\ud7af]', title):
            return False

        # 其他情况认为是英文
        return True

    def translate_text(self, text: str, source_lang: str, target_lang: str) -> tuple[bool, str]:
        """
        翻译文本（指定源语言和目标语言）

        Args:
            text: 待翻译的文本
            source_lang: 源语言代码
            target_lang: 目标语言代码

        Returns:
            (success, translated_text) 元组
        """
        if not self.translation_tools:
            return False, ""

        result = self.translation_tools.translate_text(text, source=source_lang, target=target_lang)

        if result.get("success"):
            return True, result.get("translated_text", "")
        else:
            error_msg = result.get("error", {}).get("message", "翻译失败")
            log.warning("翻译失败", error=error_msg)
            return False, ""

    def translate_title(self, title: str, target_lang: str = "zh") -> tuple[bool, str]:
        """
        翻译单个标题

        Args:
            title: 待翻译的标题
            target_lang: 目标语言 ("zh" 或 "en")

        Returns:
            (success, translated_text) 元组
        """
        if not self.translation_tools:
            return False, ""

        # 自动检测源语言
        source_lang = "en" if self.is_english_title(title) else "zh"

        # 如果目标语言与源语言相同，不需要翻译
        if source_lang == target_lang:
            return True, title

        result = self.translation_tools.translate_text(title, source=source_lang, target=target_lang)

        if result.get("success"):
            return True, result.get("translated_text", "")
        else:
            error_msg = result.get("error", {}).get("message", "翻译失败")
            log.warning("翻译失败", error=error_msg)
            return False, ""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def _gemini_call(self, prompt: str) -> str:
        """
        调用 Gemini API 进行翻译（带重试的内部方法）。

        基于: python-resilience skill — Exponential backoff with jitter
        """
        from mcp_server.tools.translation import TranslationTools

        tools: TranslationTools = self.translation_tools
        if tools.gemini_client:
            resp = tools.gemini_client.models.generate_content(
                model="gemini-2.0-flash", contents=prompt
            )
            return resp.text.strip()
        elif tools.gemini_model:
            resp = tools.gemini_model.generate_content(prompt)
            return resp.text.strip()
        else:
            raise TranslationError(
                "Gemini 客户端未初始化", source_lang="en", target_lang="zh"
            )

    def batch_translate_titles(self, titles: list[str], source_lang: str = "en", target_lang: str = "zh", batch_size: int = 15) -> list[str]:
        """
        批量翻译标题（多个标题合并为一次 API 调用）

        Args:
            titles: 待翻译标题列表
            source_lang: 源语言
            target_lang: 目标语言
            batch_size: 每批大小

        Returns:
            翻译结果列表（与输入等长，失败项为空字符串）
        """
        if not titles:
            return []

        results = [""] * len(titles)

        import re as _re

        for start in range(0, len(titles), batch_size):
            batch = titles[start:start + batch_size]
            numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(batch))

            prompt = f"Translate each numbered line below to Chinese. Return ONLY the translations, one per line, keep the same numbering format (e.g. '1. ...'). Do not add any explanation:\n\n{numbered}"

            parsed_count = 0
            try:
                translated_text = self._gemini_call(prompt)

                if translated_text:
                    lines = [ln.strip() for ln in translated_text.strip().split("\n") if ln.strip()]

                    # 尝试按编号解析（支持 1. 1) 1、 1: 1- 1） 1．等格式）
                    for line in lines:
                        m = _re.match(r'^(\d+)\s*[.\)\uff0e\u3001:\-\uff09]\s*(.+)', line)
                        if m:
                            idx = int(m.group(1)) - 1
                            if 0 <= idx < len(batch):
                                results[start + idx] = m.group(2).strip()
                                parsed_count += 1

                    # 如果编号解析失败，按行顺序匹配
                    if parsed_count < len(batch) // 2:
                        non_empty = [ln for ln in lines if ln]
                        # 去掉可能的编号前缀
                        cleaned = []
                        for ln in non_empty:
                            c = _re.sub(r'^\d+\s*[.\)\uff0e\u3001:\-\uff09]\s*', '', ln).strip()
                            cleaned.append(c if c else ln)
                        if len(cleaned) == len(batch):
                            for i, trans in enumerate(cleaned):
                                results[start + i] = trans
                            parsed_count = len(batch)
                            log.debug(f"编号解析失败，按行顺序匹配 {len(batch)} 条")

                    log.info(f"批量翻译批次 {start+1}-{start+len(batch)}: 解析 {parsed_count}/{len(batch)} 条")

            except Exception as e:
                log.warning("批量翻译异常", error=str(e))

            # 回退：对解析失败的条目逐条翻译
            failed_in_batch = [i for i in range(len(batch)) if not results[start + i]]
            if failed_in_batch:
                log.info(f"回退逐条翻译 {len(failed_in_batch)} 条...")
                for i in failed_in_batch:
                    success, translated = self.translate_title(batch[i], target_lang)
                    if success and translated:
                        results[start + i] = translated

        return results

    def translate_news_items(self, news_items: list[NewsItem], skip_existing: bool = True) -> int:
        """
        批量翻译新闻条目（仅翻译英文→中文，跳过中文标题）

        Args:
            news_items: 新闻条目列表
            skip_existing: 是否跳过已有翻译的条目

        Returns:
            成功翻译的数量
        """
        if not self.translation_tools:
            log.warning("翻译工具未初始化，跳过翻译")
            return 0

        # 分类：收集需要翻译的英文标题
        en_indices = []  # (index_in_news_items,)
        en_titles = []
        skipped_zh = 0

        for i, item in enumerate(news_items):
            is_english = self.is_english_title(item.title)
            item.is_english = is_english

            if not is_english:
                skipped_zh += 1
                continue

            if skip_existing and getattr(item, "title_translated", ""):
                continue

            en_indices.append(i)
            en_titles.append(item.title)

        if skipped_zh > 0:
            log.debug(f"跳过 {skipped_zh} 条中文标题（无需翻译）")

        if not en_titles:
            log.info("无需翻译的英文标题")
            return 0

        log.info(f"批量翻译 {len(en_titles)} 条英文标题...")
        translations = self.batch_translate_titles(en_titles)

        translated_count = 0
        for idx, trans in zip(en_indices, translations, strict=False):
            if trans:
                news_items[idx].title_translated = trans
                translated_count += 1

        log.success(f"翻译完成: {translated_count}/{len(en_titles)} 条成功")
        return translated_count

    def translate_news_data(self, news_data: NewsData, skip_existing: bool = True) -> int:
        """
        翻译 NewsData 中的所有新闻条目

        Args:
            news_data: NewsData 对象
            skip_existing: 是否跳过已有翻译的条目

        Returns:
            成功翻译的数量
        """
        total_translated = 0

        for _, news_list in news_data.items.items():
            translated = self.translate_news_items(news_list, skip_existing)
            total_translated += translated

        return total_translated
