# coding=utf-8
"""
翻译服务模块

提供英文新闻标题的自动翻译功能，在数据抓取阶段集成。
支持检测英文标题并调用翻译 API 进行翻译。
"""

import re
from typing import Dict, List, Optional, Tuple
from trendradar.storage.base import NewsItem, NewsData


class TranslationService:
    """翻译服务类"""
    
    def __init__(self, gemini_api_key: Optional[str] = None):
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
            print("[TranslationService] 翻译工具初始化成功")
        except Exception as e:
            print(f"[TranslationService] 翻译工具初始化失败：{e}")
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
        if not title or not title.strip():
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
    
    def translate_text(self, text: str, source_lang: str, target_lang: str) -> Tuple[bool, str]:
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
            print(f"[TranslationService] 翻译失败：{error_msg}")
            return False, ""
    
    def translate_title(self, title: str, target_lang: str = "zh") -> Tuple[bool, str]:
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
            print(f"[TranslationService] 翻译失败：{error_msg}")
            return False, ""
    
    def batch_translate_titles(self, titles: List[str], source_lang: str = "en", target_lang: str = "zh", batch_size: int = 15) -> List[str]:
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
        
        for start in range(0, len(titles), batch_size):
            batch = titles[start:start + batch_size]
            numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(batch))
            
            prompt = f"Translate each numbered line below to Chinese. Return ONLY the translations, one per line, with the same numbering. Do not add any explanation:\n\n{numbered}"
            
            try:
                tools = self.translation_tools
                translated_text = None
                if tools.gemini_client:
                    resp = tools.gemini_client.models.generate_content(
                        model='gemini-2.0-flash', contents=prompt
                    )
                    translated_text = resp.text.strip()
                elif tools.gemini_model:
                    resp = tools.gemini_model.generate_content(prompt)
                    translated_text = resp.text.strip()
                
                if translated_text:
                    import re as _re
                    lines = translated_text.strip().split("\n")
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        m = _re.match(r'^(\d+)[.\)\uff0e]\s*(.+)', line)
                        if m:
                            idx = int(m.group(1)) - 1
                            if 0 <= idx < len(batch):
                                results[start + idx] = m.group(2).strip()
            except Exception as e:
                print(f"[TranslationService] 批量翻译失败: {e}")
                # fallback: translate individually
                for i, title in enumerate(batch):
                    success, translated = self.translate_title(title, target_lang)
                    if success and translated:
                        results[start + i] = translated
        
        return results

    def translate_news_items(self, news_items: List[NewsItem], skip_existing: bool = True) -> int:
        """
        批量翻译新闻条目（仅翻译英文→中文，跳过中文标题）
        
        Args:
            news_items: 新闻条目列表
            skip_existing: 是否跳过已有翻译的条目
            
        Returns:
            成功翻译的数量
        """
        if not self.translation_tools:
            print("[TranslationService] 翻译工具未初始化，跳过翻译")
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
            print(f"  跳过 {skipped_zh} 条中文标题（无需翻译）")
        
        if not en_titles:
            print(f"  无需翻译的英文标题")
            return 0
        
        print(f"  批量翻译 {len(en_titles)} 条英文标题...")
        translations = self.batch_translate_titles(en_titles)
        
        translated_count = 0
        for idx, trans in zip(en_indices, translations):
            if trans:
                news_items[idx].title_translated = trans
                translated_count += 1
        
        print(f"  翻译完成: {translated_count}/{len(en_titles)} 条成功")
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
        
        for source_id, news_list in news_data.items.items():
            translated = self.translate_news_items(news_list, skip_existing)
            total_translated += translated
        
        return total_translated
