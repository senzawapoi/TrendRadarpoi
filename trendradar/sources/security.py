"""Source adapters for CISA KEV, NVD CVE 2.0, and security RSS feeds."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from trendradar.ai_frontier._http import make_session, request_with_retry
from trendradar.core.models import ContentItem, normalize_text
from trendradar.crawler.rss.fetcher import RSSFeedConfig, RSSFetcher
from trendradar.domains.security.collector import (
    CISA_KEV_URL,
    NVD_CVE_API_URL,
    SecurityRecord,
    parse_cisa_catalog,
    parse_nvd_page,
    security_record_from_rss,
)
from trendradar.sources.base import SourceAdapter
from trendradar.storage.base import RSSItem
from trendradar.utils.logging import log

# Default significance rules for NVD (used only when ``significance.enabled`` is true
# and no explicit ``rules`` are configured). NVD publishes several hundred CVEs a day;
# these keep AI-stack issues of high severity and critical issues in widely deployed
# platforms. CISA KEV entries are collected separately and are never filtered here.
DEFAULT_NVD_RULES: tuple[dict[str, Any], ...] = (
    {
        "name": "ai_stack",
        "min_cvss": 8.0,
        "keywords": (
            "LLM", "large language model", "AI agent", "model context protocol", "MCP server",
            "retrieval-augmented", "LangChain", "LangGraph", "Langflow", "LlamaIndex",
            "llama.cpp", "Ollama", "vLLM", "SGLang", "LMDeploy", "Xinference", "LocalAI",
            "GPT4All", "PrivateGPT", "PyTorch", "TensorFlow", "Keras", "Hugging Face",
            "huggingface", "safetensors", "ONNX Runtime", "OpenVINO", "DeepSpeed", "Megatron",
            "NVIDIA", "CUDA Toolkit", "TensorRT", "Triton Inference Server", "ComfyUI",
            "Stable Diffusion", "Open WebUI", "open-webui", "AnythingLLM", "LobeChat",
            "LibreChat", "Dify", "Flowise", "n8n", "MLflow", "Kubeflow", "BentoML", "KServe",
            "Gradio", "Streamlit", "Chainlit", "JupyterLab", "Jupyter Notebook", "Jupyter Server",
            "Milvus", "Qdrant", "Weaviate", "ChromaDB", "LiteLLM", "AutoGen", "CrewAI", "Agno",
            "Semantic Kernel", "OpenAI", "Anthropic", "Claude Code", "Google Gemini",
            "Gemini CLI", "GitHub Copilot", "Microsoft Copilot", "Copilot Studio",
            "PaddlePaddle", "MindSpore", "Label Studio",
        ),
    },
    {
        "name": "major_platform",
        "min_cvss": 9.0,
        # Product names, not words that CVE descriptions mention in passing ("on Windows").
        "keywords": (
            "Microsoft Windows", "Windows Server", "Microsoft Exchange", "Exchange Server",
            "SharePoint", "Microsoft Office", "Microsoft Outlook", "Azure", "Hyper-V",
            "Active Directory", "Apple iOS", "iPadOS", "macOS", "Safari", "WebKit",
            "Google Chrome", "Chromium", "Mozilla Firefox", "Linux kernel", "OpenSSL", "OpenSSH",
            "glibc", "sudo", "systemd", "Cisco", "Fortinet", "FortiOS", "FortiGate", "FortiWeb",
            "FortiManager", "Palo Alto Networks", "PAN-OS", "Ivanti", "VMware", "ESXi", "vCenter",
            "Citrix", "NetScaler", "Juniper", "Junos", "BIG-IP", "SonicWall", "Kubernetes",
            "Docker Engine", "Docker Desktop", "containerd", "runc", "Apache HTTP Server",
            "Apache Tomcat", "Apache Struts", "Log4j", "nginx", "Jenkins", "GitLab",
            "GitHub Enterprise Server", "Atlassian", "Confluence", "Jira", "Oracle WebLogic",
            "Oracle Database", "SAP NetWeaver", "Redis", "PostgreSQL", "MySQL", "Elasticsearch",
            "Grafana", "Zimbra", "Veeam", "MOVEit", "Cloudflare", "AWS", "Google Cloud",
        ),
    },
)


def _keyword_regex(keywords: Iterable[str]) -> re.Pattern[str] | None:
    parts = []
    for keyword in sorted({normalize_text(item) for item in keywords if normalize_text(item)},
                          key=len, reverse=True):
        # Letter/digit boundaries avoid matching "Ray" in "X-ray" style substrings while
        # still allowing punctuation such as "llama.cpp" and "PAN-OS".
        parts.append(rf"(?<![A-Za-z0-9]){re.escape(keyword)}(?![A-Za-z0-9])")
    return re.compile("|".join(parts), re.IGNORECASE) if parts else None


@dataclass(frozen=True)
class NvdSignificanceRule:
    name: str
    min_cvss: float
    pattern: re.Pattern[str] | None
    include_unscored: bool = False


class NvdSignificanceFilter:
    """Keep only NVD records that match a configured interest rule."""

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        values = config if isinstance(config, Mapping) else {}
        self.enabled = _as_bool(values.get("enabled"), False)
        self.keep_known_exploited = _as_bool(values.get("keep_known_exploited"), True)
        raw_rules = values.get("rules")
        if not isinstance(raw_rules, list | tuple) or not raw_rules:
            raw_rules = DEFAULT_NVD_RULES
        rules = []
        for index, raw in enumerate(raw_rules[:20]):
            if not isinstance(raw, Mapping):
                continue
            keywords = raw.get("keywords")
            if isinstance(keywords, str):
                keywords = keywords.split(",")
            pattern = _keyword_regex(keywords) if isinstance(keywords, Iterable) else None
            rules.append(NvdSignificanceRule(
                name=normalize_text(raw.get("name")) or f"rule_{index + 1}",
                min_cvss=_bounded_float(raw.get("min_cvss"), 9.0, maximum=10.0),
                # A rule without keywords applies to every product.
                pattern=pattern,
                include_unscored=_as_bool(raw.get("include_unscored"), False),
            ))
        self.rules = tuple(rules)
        # Vendors often publish many CVEs for one product at once; keep the highest-scored
        # few per matched keyword in each run (0 = unlimited).
        try:
            cap = int(values.get("max_per_keyword", 0))
        except (TypeError, ValueError):
            cap = 0
        self.max_per_keyword = max(0, min(1000, cap))

    def match(self, record: SecurityRecord) -> tuple[str, str] | None:
        """Return ``(rule name, matched keyword)`` or ``None`` when not kept."""
        if not self.enabled:
            return "filter_disabled", ""
        if self.keep_known_exploited and record.known_exploited:
            return "known_exploited", ""
        text = " ".join(
            normalize_text(value)
            for value in (record.title, record.summary, record.vendor, record.product)
            if value
        )
        for rule in self.rules:
            score = record.cvss_score
            if score is None and not rule.include_unscored:
                continue
            if score is not None and score < rule.min_cvss:
                continue
            if rule.pattern is None:
                return rule.name, ""
            found = rule.pattern.search(text)
            if found:
                return rule.name, found.group(0)
        return None

    def reason(self, record: SecurityRecord) -> str | None:
        """Return the matching rule name, or ``None`` when the record is not kept."""
        matched = self.match(record)
        return matched[0] if matched else None

    def cap(
        self, matches: list[tuple[SecurityRecord, str, str]],
    ) -> list[tuple[SecurityRecord, str, str]]:
        """Apply ``max_per_keyword`` by CVSS score while preserving source order."""
        if self.max_per_keyword <= 0:
            return matches
        ranked = sorted(
            range(len(matches)), key=lambda index: -(matches[index][0].cvss_score or 0.0)
        )
        counts: dict[str, int] = {}
        keep = set()
        for index in ranked:
            keyword = matches[index][2].casefold()
            if not keyword:
                keep.add(index)
            elif counts.get(keyword, 0) < self.max_per_keyword:
                counts[keyword] = counts.get(keyword, 0) + 1
                keep.add(index)
        return [match for index, match in enumerate(matches) if index in keep]


def _positive_int(value: Any, default: int, *, maximum: int | None = None) -> int:
    try:
        result = max(1, int(value))
    except (TypeError, ValueError):
        result = default
    return min(result, maximum) if maximum is not None else result


def _bounded_count(value: Any, default: int, *, maximum: int) -> int:
    """Resolve a bounded item count; zero/invalid values use the safe default."""
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    if result <= 0:
        result = default
    return min(result, maximum)


def _bounded_float(value: Any, default: float, *, maximum: float) -> float:
    try:
        result = max(0.0, float(value))
    except (TypeError, ValueError):
        result = default
    return min(result, maximum)


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = normalize_text(value).casefold()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    return default


class CisaKevAdapter(SourceAdapter[SecurityRecord]):
    domain = "security"
    adapter_id = "security:cisa-kev"

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        values = config if isinstance(config, Mapping) else {}
        self.enabled = _as_bool(values.get("enabled"), True)
        self.url = normalize_text(values.get("url")) or CISA_KEV_URL
        self.timeout = _positive_int(values.get("timeout"), 30, maximum=120)
        self.max_items = _bounded_count(values.get("max_items"), 500, maximum=5000)
        self.proxy_url = normalize_text(values.get("proxy_url"))
        super().__init__()

    async def fetch(self) -> list[SecurityRecord]:
        if not self.enabled:
            return []
        async with make_session(total_timeout=self.timeout, max_per_host=2) as session:
            response = await request_with_retry(
                session,
                "GET",
                self.url,
                label="CISA KEV",
                max_attempts=2,
                timeout=self.timeout,
                proxy=self.proxy_url or None,
            )
            if response is None:
                raise RuntimeError("CISA KEV request failed")
            if response.status != 200:
                status = response.status
                response.release()
                raise RuntimeError(f"CISA KEV returned HTTP {status}")
            try:
                payload = await response.json(content_type=None)
            finally:
                response.release()
        records = parse_cisa_catalog(payload, source_url=self.url)
        return sorted(
            records,
            key=lambda record: (
                record.published_at or datetime.min.replace(tzinfo=timezone.utc),
                record.external_id,
            ),
            reverse=True,
        )[: self.max_items]

    def normalize(self, raw: SecurityRecord, *, collected_at: datetime) -> ContentItem:
        return raw.to_content_item(collected_at=collected_at)


class NvdCveAdapter(SourceAdapter[SecurityRecord]):
    domain = "security"
    adapter_id = "security:nvd"

    def __init__(
        self,
        config: Mapping[str, Any] | None = None,
        *,
        now: datetime | None = None,
        api_key: str = "",
    ) -> None:
        values = config if isinstance(config, Mapping) else {}
        self.enabled = _as_bool(values.get("enabled"), True)
        self.url = normalize_text(values.get("url")) or NVD_CVE_API_URL
        self.timeout = _positive_int(values.get("timeout"), 30, maximum=120)
        self.lookback_hours = _positive_int(values.get("lookback_hours"), 48, maximum=2880)
        self.results_per_page = _positive_int(
            values.get("results_per_page"), 100, maximum=2000
        )
        self.max_pages = _positive_int(values.get("max_pages"), 2, maximum=20)
        self.max_items = _positive_int(values.get("max_items"), 200, maximum=10000)
        self.request_interval = _bounded_float(
            values.get("request_interval_seconds"),
            0.6 if api_key else 6.0,
            maximum=60.0,
        )
        self.proxy_url = normalize_text(values.get("proxy_url"))
        # "modified" (default) follows NVD lastMod dates and also re-reports old CVEs;
        # "published" only covers CVEs first published inside the lookback window.
        date_field = normalize_text(values.get("date_field")).casefold() or "modified"
        if date_field not in {"modified", "published"}:
            log.warning("Invalid NVD date_field; using modified", date_field=date_field[:40])
            date_field = "modified"
        self.date_field = date_field
        self.significance = NvdSignificanceFilter(
            values.get("significance") if isinstance(values.get("significance"), Mapping)
            else None
        )
        timestamp = now or datetime.now(tz=timezone.utc)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("NVD reference time must be timezone-aware")
        self.now = timestamp.astimezone(timezone.utc)
        self.api_key = normalize_text(api_key)
        super().__init__()

    def _params(self, start_index: int) -> dict[str, Any]:
        start = self.now - timedelta(hours=self.lookback_hours)
        prefix = "pub" if self.date_field == "published" else "lastMod"
        return {
            f"{prefix}StartDate": start.isoformat(timespec="milliseconds"),
            f"{prefix}EndDate": self.now.isoformat(timespec="milliseconds"),
            "resultsPerPage": self.results_per_page,
            "startIndex": start_index,
        }

    async def fetch(self) -> list[SecurityRecord]:
        if not self.enabled:
            return []
        headers = {"apiKey": self.api_key} if self.api_key else None
        matches: list[tuple[SecurityRecord, str, str]] = []
        scanned = 0
        start_index = 0
        async with make_session(total_timeout=self.timeout, max_per_host=1) as session:
            for page in range(self.max_pages):
                response = await request_with_retry(
                    session,
                    "GET",
                    self.url,
                    params=self._params(start_index),
                    headers=headers,
                    proxy=self.proxy_url or None,
                    label="NVD CVE 2.0",
                    max_attempts=2,
                    timeout=self.timeout,
                )
                if response is None:
                    raise RuntimeError("NVD request failed")
                if response.status != 200:
                    status = response.status
                    response.release()
                    raise RuntimeError(f"NVD returned HTTP {status}")
                try:
                    payload = await response.json(content_type=None)
                finally:
                    response.release()
                page_records, total, returned_start, returned_count = parse_nvd_page(payload)
                scanned += len(page_records)
                for record in page_records:
                    matched = self.significance.match(record)
                    if matched is not None:
                        matches.append((record, *matched))
                # With the filter on, read every page so the per-keyword cap ranks the
                # whole window; max_pages still bounds the requests.
                if not self.significance.enabled and len(matches) >= self.max_items:
                    break
                step = returned_count or len(page_records)
                next_index = returned_start + step
                if step <= 0 or next_index >= total:
                    break
                start_index = next_index
                if page + 1 < self.max_pages and self.request_interval:
                    await asyncio.sleep(self.request_interval)
        kept = self.significance.cap(matches)[: self.max_items]
        if self.significance.enabled:
            reasons: dict[str, int] = {}
            for _record, rule, _keyword in kept:
                reasons[rule] = reasons.get(rule, 0) + 1
            log.info(
                "NVD significance filter",
                scanned=scanned,
                matched=len(matches),
                kept=len(kept),
                reasons=",".join(f"{name}={count}" for name, count in sorted(reasons.items())),
            )
        return [record for record, _rule, _keyword in kept]

    def normalize(self, raw: SecurityRecord, *, collected_at: datetime) -> ContentItem:
        return raw.to_content_item(collected_at=collected_at)


class SecurityRSSAdapter(SourceAdapter[RSSItem]):
    domain = "security"

    def __init__(self, feed: RSSFeedConfig, **fetcher_options: object) -> None:
        self.feed = feed
        self.adapter_id = f"security:rss:{feed.id}"
        self.fetcher = RSSFetcher(feeds=[feed], **fetcher_options)
        super().__init__()

    async def fetch(self) -> list[RSSItem]:
        result = await self.fetcher.async_fetch_all(max_workers=1)
        if self.feed.id in result.failed_ids:
            raise RuntimeError(f"security RSS fetch failed: {self.feed.id}")
        items = result.items.get(self.feed.id, [])
        filtered, _ = self.fetcher._filter_by_freshness(items, self.feed)
        return filtered

    def normalize(self, raw: RSSItem, *, collected_at: datetime) -> ContentItem:
        return security_record_from_rss(raw).to_content_item(collected_at=collected_at)


__all__ = ["CisaKevAdapter", "NvdCveAdapter", "SecurityRSSAdapter"]
