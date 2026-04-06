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
    
    def translate_news_items(self, news_items: List[NewsItem], skip_existing: bool = True) -> int:
        """
        批量翻译新闻条目（支持双语翻译）
        
        Args:
            news_items: 新闻条目列表
            skip_existing: 是否跳过已有翻译的条目
            
        Returns:
            成功翻译的数量
        """
        if not self.translation_tools:
            print("[TranslationService] 翻译工具未初始化，跳过翻译")
            return 0
        
        translated_count = 0
        total_processed = 0
        
        for item in news_items:
            # 检测是否为英文标题
            is_english = self.is_english_title(item.title)
            item.is_english = is_english
            
            # 确定源语言和目标语言
            if is_english:
                source_lang, target_lang = "en", "zh"
                translated_field, english_field = "title_translated", "title_english"
            else:
                source_lang, target_lang = "zh", "en"
                translated_field, english_field = "title_english", "title_translated"
            
            # 检查是否需要翻译
            if skip_existing:
                existing_translation = getattr(item, translated_field, "")
                if existing_translation:
                    continue
            
            total_processed += 1
            
            # 翻译标题
            success, translated = self.translate_title(item.title, target_lang)
            
            if success and translated:
                setattr(item, translated_field, translated)
                translated_count += 1
            
            # 翻译摘要（如果存在）
            if hasattr(item, 'summary') and item.summary:
                summary_success, summary_translated = self.translate_text(item.summary, source_lang, target_lang)
                if summary_success and summary_translated:
                    summary_field = "summary_translated" if target_lang == "zh" else "summary_english"
                    setattr(item, summary_field, summary_translated)
            
            # 进度显示（每 10 条或最后一条）
            if total_processed % 10 == 0 or total_processed == len(news_items):
                print(f"\r  翻译进度: {total_processed}/{len(news_items)}", end="", flush=True)
        
        print(f"\n  翻译完成: {translated_count}/{total_processed} 条成功")
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
