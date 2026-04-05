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
    
    def translate_title(self, title: str) -> Tuple[bool, str]:
        """
        翻译单个标题
        
        Args:
            title: 待翻译的标题
            
        Returns:
            (success, translated_text) 元组
        """
        if not self.translation_tools:
            return False, ""
        
        result = self.translation_tools.translate_text(title)
        
        if result.get("success"):
            return True, result.get("translated_text", "")
        else:
            error_msg = result.get("error", {}).get("message", "翻译失败")
            print(f"[TranslationService] 翻译失败：{error_msg}")
            return False, ""
    
    def translate_news_items(self, news_items: List[NewsItem], skip_existing: bool = True) -> int:
        """
        批量翻译新闻条目
        
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
        total_english = 0
        
        for item in news_items:
            # 如果已有翻译且要求跳过，则跳过
            if skip_existing and item.title_translated:
                continue
            
            # 检测是否为英文标题
            is_english = self.is_english_title(item.title)
            item.is_english = is_english
            
            if not is_english:
                # 非英文标题，不需要翻译
                continue
            
            total_english += 1
            
            # 翻译标题
            success, translated = self.translate_title(item.title)
            
            if success and translated:
                item.title_translated = translated
                translated_count += 1
                print(f"[TranslationService] 翻译：'{item.title[:30]}...' -> '{translated[:30]}...'")
            else:
                # 翻译失败但标记为英文，下次重试
                print(f"[TranslationService] 翻译失败：'{item.title[:30]}...'")
        
        print(f"[TranslationService] 翻译完成：共 {total_english} 条英文标题，成功翻译 {translated_count} 条")
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
