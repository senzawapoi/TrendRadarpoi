"""Deterministic reader-interest filter for instant Story delivery.

The filter only decides whether a persisted Story is pushed to Lark. Filtered Stories stay
in the unified database, reports and Assistant retrieval; they are registered for the
target without a batch so they are neither resent nor counted as delivery backlog.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

# Broad first pass of the AI-focused reader profile (software, hardware, business and
# policy). It is intentionally wide; narrow it in configuration after observing output.
DEFAULT_DOMAINS: tuple[str, ...] = ("ai", "security")
DEFAULT_SOURCES: tuple[str, ...] = (
    "rss:TechCrunch AI",
    "rss:Hugging Face Blog",
    "rss:DeepMind Blog",
    "rss:TLDR AI",
    "rss:Nvdia",
)
DEFAULT_KEYWORDS: tuple[str, ...] = (
    # Models, products and techniques.
    "AI", "A.I.", "AGI", "artificial intelligence", "LLM", "LLMs", "large language model",
    "generative AI", "GenAI", "machine learning", "deep learning", "neural network",
    "foundation model", "multimodal", "chatbot", "AI agent", "AI agents", "agentic",
    "fine-tuning", "diffusion model", "reasoning model", "open-weight", "open weights",
    "人工智能", "大模型", "模型", "智能体", "生成式", "多模态", "机器学习", "深度学习",
    "神经网络", "具身智能", "AIGC",
    # AI companies and products.
    "OpenAI", "ChatGPT", "GPT", "Sora", "Codex", "Anthropic", "Claude", "DeepMind",
    "Gemini", "Gemma", "Llama", "Mistral", "xAI", "Grok", "Perplexity", "Hugging Face",
    "Cohere", "DeepSeek", "Qwen", "Kimi", "Moonshot", "Zhipu", "MiniMax", "Baichuan",
    "Stability AI", "Midjourney", "Copilot", "Cursor", "Microsoft", "Google", "Alphabet",
    "Meta", "Apple Intelligence", "Amazon", "AWS", "Azure", "Salesforce", "Palantir",
    "深度求索", "通义", "千问", "豆包", "文心", "混元", "月之暗面", "智谱", "百川", "商汤",
    "科大讯飞", "字节跳动", "阿里巴巴", "阿里云", "百度", "腾讯", "微软", "谷歌", "亚马逊",
    # Chips, compute and infrastructure.
    "Nvidia", "CUDA", "GPU", "GPUs", "TPU", "NPU", "AMD", "Intel", "TSMC", "ASML", "HBM",
    "SK Hynix", "Micron", "Broadcom", "Qualcomm", "Arm Holdings", "semiconductor",
    "semiconductors", "chipmaker", "chipmakers", "AI chip", "AI chips", "foundry", "wafer",
    "lithography", "EUV", "data center", "data centers", "datacenter", "supercomputer",
    "hyperscaler", "Stargate", "CoreWeave",
    "英伟达", "黄仁勋", "芯片", "半导体", "晶圆", "光刻", "显卡", "算力", "智算", "台积电",
    "中芯", "昇腾", "寒武纪", "海光", "摩尔线程", "壁仞", "存储芯片", "数据中心", "服务器",
    # Robotics and autonomy.
    "robot", "robots", "robotics", "humanoid", "autonomous driving", "self-driving",
    "robotaxi", "Waymo", "机器人", "人形机器人", "自动驾驶", "无人驾驶", "智驾",
    # Policy, regulation and capital.
    "export control", "export controls", "Entity List", "AI Act", "AI safety",
    "AI regulation", "出口管制", "实体清单", "AI监管", "算法备案",
)


def _text_tuple(values: Any, default: tuple[str, ...], *, limit: int = 500) -> tuple[str, ...]:
    if values is None:
        return default
    if isinstance(values, str):
        values = values.split(",")
    if not isinstance(values, Iterable) or isinstance(values, Mapping):
        return default
    cleaned = []
    for value in values:
        text = " ".join(str(value).split())
        if text and len(text) <= 120 and text not in cleaned:
            cleaned.append(text)
    return tuple(cleaned[:limit])


def _enabled(value: Any) -> bool:
    return value is True or (
        isinstance(value, str) and value.strip().lower() in {"true", "1", "yes", "on"}
    )


@lru_cache(maxsize=16)
def _keyword_pattern(keywords: tuple[str, ...]) -> re.Pattern[str] | None:
    parts = []
    # Longest first so the reported reason is the most specific keyword.
    for keyword in sorted(keywords, key=len, reverse=True):
        escaped = re.escape(keyword)
        if keyword.isascii():
            # ASCII terms need explicit letter/digit boundaries: CJK characters count
            # as word characters for \b, so "AI芯片" would otherwise not match "AI".
            escaped = rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])"
        parts.append(escaped)
    return re.compile("|".join(parts), re.IGNORECASE) if parts else None


@dataclass(frozen=True, slots=True)
class StoryInterestFilter:
    """Push a Story when its domain, a source or its text matches the reader profile."""

    enabled: bool = False
    domains: tuple[str, ...] = DEFAULT_DOMAINS
    sources: tuple[str, ...] = DEFAULT_SOURCES
    exclude_sources: tuple[str, ...] = ()
    keywords: tuple[str, ...] = DEFAULT_KEYWORDS

    @classmethod
    def from_mapping(cls, value: Any) -> StoryInterestFilter:
        if isinstance(value, StoryInterestFilter):
            return value
        raw = value if isinstance(value, Mapping) else {}
        return cls(
            enabled=_enabled(raw.get("enabled", False)),
            domains=tuple(item.lower() for item in _text_tuple(raw.get("domains"), DEFAULT_DOMAINS)),
            sources=_text_tuple(raw.get("sources"), DEFAULT_SOURCES),
            exclude_sources=_text_tuple(raw.get("exclude_sources"), ()),
            keywords=_text_tuple(raw.get("keywords"), DEFAULT_KEYWORDS, limit=2000),
        )

    def decide(
        self, *, domain: str, sources: Iterable[str], texts: Iterable[str],
    ) -> str | None:
        """Return why a Story is pushed, or ``None`` when it is held back."""
        if not self.enabled:
            return "filter_disabled"
        source_set = {str(source) for source in sources if source}
        if source_set and source_set <= set(self.exclude_sources):
            return None
        if str(domain).lower() in self.domains:
            return f"domain:{str(domain).lower()}"
        for source in sorted(source_set & set(self.sources)):
            return f"source:{source}"
        pattern = _keyword_pattern(self.keywords)
        if pattern is not None:
            for text in texts:
                match = pattern.search(str(text or ""))
                if match:
                    return f"keyword:{match.group(0)}"
        return None


__all__ = ["DEFAULT_DOMAINS", "DEFAULT_KEYWORDS", "DEFAULT_SOURCES", "StoryInterestFilter"]
