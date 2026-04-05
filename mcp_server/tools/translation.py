"""
新闻翻译工具

提供英文新闻标题和内容的中文翻译功能。
支持多种翻译 API：MyMemory、Lingva、Google Gemini
"""

import requests
from typing import List, Dict, Optional, Union
from ..utils.errors import MCPError


class TranslationTools:
    """新闻翻译工具类"""
    
    # 免费翻译 API 列表（按优先级排序）
    TRANSLATION_APIS = [
        {
            "name": "MyMemory",
            "url": "https://api.mymemory.translated.net/get",
            "method": "GET",
            "params": lambda q, source, target: {"q": q, "langpair": f"{source}|{target}"},
            "response_path": ["responseData", "translatedText"],
            "max_length": 500
        },
        {
            "name": "Lingva",
            "url": "https://lingva.ml/api/v1/{source}/{target}/{q}",
            "method": "GET",
            "params": None,  # URL 路径参数
            "response_path": ["translation"],
            "max_length": 500
        }
    ]
    
    def __init__(
        self, 
        default_source: str = "en", 
        default_target: str = "zh",
        gemini_api_key: Optional[str] = AIzaSyDoPYCP3M9aRY3ecaOjO_zPP1Nw3iTUXYg
    ):
        """
        初始化翻译工具
        
        Args:
            default_source: 默认源语言（如 'en' 表示英语）
            default_target: 默认目标语言（如 'zh' 表示中文）
            gemini_api_key: Google Gemini API 密钥（可选）
        """
        self.default_source = default_source
        self.default_target = default_target
        self.gemini_api_key = gemini_api_key
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "TrendRadar/1.0 Translation Service"
        })
        
        # 初始化 Gemini 客户端（如果提供了 API 密钥）
        self.gemini_model = None
        self.gemini_client = None
        if gemini_api_key:
            try:
                # 优先尝试新的 google.genai 包
                try:
                    from google import genai
                    self.gemini_client = genai.Client(api_key=gemini_api_key)
                    print("[Translation] Google Gemini API (新 SDK) 已初始化")
                except (ImportError, AttributeError):
                    # 回退到旧的 google.generativeai 包
                    import google.generativeai as genai
                    genai.configure(api_key=gemini_api_key)
                    self.gemini_model = genai.GenerativeModel('gemini-pro')
                    print("[Translation] Google Gemini API (旧 SDK) 已初始化")
            except ImportError:
                print("[Translation] 警告：google-genai 未安装，Gemini 功能不可用")
            except Exception as e:
                print(f"[Translation] 警告：Gemini API 初始化失败：{e}")
    
    def translate_text(
        self,
        text: str,
        source: Optional[str] = None,
        target: Optional[str] = None,
        use_cache: bool = True
    ) -> Dict:
        """
        翻译单段文本
        
        Args:
            text: 待翻译的文本
            source: 源语言代码（如 'en'），默认使用配置值
            target: 目标语言代码（如 'zh'），默认使用配置值
            use_cache: 是否使用缓存
            
        Returns:
            翻译结果字典：
            {
                "success": True,
                "original_text": "原文",
                "translated_text": "译文",
                "source_lang": "en",
                "target_lang": "zh",
                "api_used": "MyMemory"
            }
        """
        if not text or not text.strip():
            return {
                "success": False,
                "error": {
                    "code": "EMPTY_TEXT",
                    "message": "待翻译文本不能为空"
                }
            }
        
        source = source or self.default_source
        target = target or self.default_target
        
        # 检查是否需要翻译（避免相同语言）
        if source == target:
            return {
                "success": True,
                "original_text": text,
                "translated_text": text,
                "source_lang": source,
                "target_lang": target,
                "note": "源语言和目标语言相同，未进行翻译"
            }
        
        # 优先尝试 Gemini API（如果已配置）
        if self.gemini_client or self.gemini_model:
            try:
                result = self._translate_with_gemini(text, source, target)
                if result and result.get("success"):
                    return result
            except Exception as e:
                print(f"[Translation] Gemini 失败：{e}")
        
        # 尝试多个免费翻译 API
        for api_config in self.TRANSLATION_APIS:
            try:
                result = self._call_translation_api(api_config, text, source, target)
                if result and result.get("success"):
                    return result
            except Exception as e:
                print(f"[Translation] {api_config['name']} 失败：{e}")
                continue
        
        return {
            "success": False,
            "error": {
                "code": "TRANSLATION_FAILED",
                "message": "所有翻译 API 均失败，请稍后重试"
            }
        }
    
    def _call_translation_api(
        self,
        api_config: Dict,
        text: str,
        source: str,
        target: str
    ) -> Optional[Dict]:
        """
        调用单个翻译 API
        
        Args:
            api_config: API 配置
            text: 待翻译文本
            source: 源语言
            target: 目标语言
            
        Returns:
            翻译结果或 None
        """
        # 截断过长的文本
        max_length = api_config.get("max_length", 500)
        if len(text) > max_length:
            text = text[:max_length] + "..."
        
        url = api_config["url"]
        method = api_config["method"]
        
        # 处理 URL 路径参数（如 Lingva）
        if api_config["params"] is None:
            from urllib.parse import quote
            url = url.format(
                source=source,
                target=target,
                q=quote(text)
            )
            response = self.session.get(url, timeout=10)
        else:
            # 处理查询参数（如 MyMemory）
            params = api_config["params"](text, source, target)
            if method == "GET":
                response = self.session.get(url, params=params, timeout=10)
            else:
                response = self.session.post(url, data=params, timeout=10)
        
        response.raise_for_status()
        data = response.json()
        
        # 提取翻译结果
        translated = data
        for key in api_config["response_path"]:
            if isinstance(translated, dict):
                translated = translated.get(key)
            else:
                break
        
        if not translated:
            return None
        
        return {
            "success": True,
            "original_text": text,
            "translated_text": translated,
            "source_lang": source,
            "target_lang": target,
            "api_used": api_config["name"]
        }
    
    def _translate_with_gemini(
        self,
        text: str,
        source: str,
        target: str
    ) -> Optional[Dict]:
        """
        使用 Google Gemini API 进行翻译
        
        Args:
            text: 待翻译文本
            source: 源语言代码
            target: 目标语言代码
            
        Returns:
            翻译结果或 None
        """
        if not self.gemini_client and not self.gemini_model:
            return None
        
        # 构建翻译提示
        language_map = {
            "en": "英语",
            "zh": "中文",
            "ja": "日语",
            "ko": "韩语",
            "fr": "法语",
            "de": "德语",
            "es": "西班牙语",
            "pt": "葡萄牙语",
            "ru": "俄语",
            "it": "意大利语"
        }
        
        source_lang = language_map.get(source, source)
        target_lang = language_map.get(target, target)
        
        prompt = f"""请将以下{source_lang}文本翻译成{target_lang}。只返回翻译结果，不要添加任何解释或其他内容：

{text}"""
        
        try:
            # 使用新 SDK
            if self.gemini_client:
                response = self.gemini_client.models.generate_content(
                    model='gemini-2.0-flash',
                    contents=prompt
                )
                translated = response.text.strip()
            # 使用旧 SDK
            elif self.gemini_model:
                response = self.gemini_model.generate_content(prompt)
                translated = response.text.strip()
            else:
                return None
            
            if not translated:
                return None
            
            return {
                "success": True,
                "original_text": text,
                "translated_text": translated,
                "source_lang": source,
                "target_lang": target,
                "api_used": "Google Gemini"
            }
        except Exception as e:
            print(f"[Translation] Gemini API 错误：{e}")
            return None
    
    def translate_news_list(
        self,
        news_list: List[Dict],
        fields: Optional[List[str]] = None,
        source: Optional[str] = None,
        target: Optional[str] = None,
        skip_if_chinese: bool = True
    ) -> Dict:
        """
        批量翻译新闻列表
        
        Args:
            news_list: 新闻列表
            fields: 需要翻译的字段，默认 ['title', 'summary']
            source: 源语言
            target: 目标语言
            skip_if_chinese: 是否跳过已包含中文的内容
            
        Returns:
            翻译后的新闻列表和统计信息
        """
        if not news_list:
            return {
                "success": True,
                "translated_news": [],
                "total": 0,
                "translated_count": 0
            }
        
        fields = fields or ["title", "summary"]
        source = source or self.default_source
        target = target or self.default_target
        
        translated_news = []
        translated_count = 0
        
        for news in news_list:
            translated_item = news.copy()
            item_translated = False
            
            for field in fields:
                if field not in news or not news[field]:
                    continue
                
                text = news[field]
                
                # 如果跳过中文且检测到中文字符
                if skip_if_chinese and self._contains_chinese(text):
                    continue
                
                # 翻译
                result = self.translate_text(text, source, target)
                if result.get("success"):
                    translated_item[f"{field}_translated"] = result["translated_text"]
                    item_translated = True
            
            if item_translated:
                translated_count += 1
            
            translated_news.append(translated_item)
        
        return {
            "success": True,
            "translated_news": translated_news,
            "total": len(news_list),
            "translated_count": translated_count,
            "source_lang": source,
            "target_lang": target
        }
    
    def _contains_chinese(self, text: str) -> bool:
        """检测文本是否包含中文字符"""
        if not text:
            return False
        
        for char in text:
            if '\u4e00' <= char <= '\u9fff':
                return True
        return False
    
    def detect_language(self, text: str) -> str:
        """
        简单检测文本语言
        
        Args:
            text: 待检测文本
            
        Returns:
            语言代码（'zh', 'en', 或 'unknown'）
        """
        if not text:
            return "unknown"
        
        chinese_chars = 0
        total_chars = min(len(text), 100)  # 只检查前 100 个字符
        
        for char in text[:total_chars]:
            if '\u4e00' <= char <= '\u9fff':
                chinese_chars += 1
        
        # 如果中文字符占比超过 20%，认为是中文
        if chinese_chars / total_chars > 0.2:
            return "zh"
        
        # 简单判断为英文（实际应用中可使用更精确的检测）
        return "en"
