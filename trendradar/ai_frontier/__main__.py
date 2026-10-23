"""AI 前沿资讯聚合入口

使用：
    python -m trendradar.ai_frontier [--config path/to/config.yaml]

环境变量：
    GEMINI_API_KEY   —— Gemini 翻译 API Key（可选）

流程：
    1. 加载 config（config/config.yaml 的 ai_frontier 节点）
    2. 并发抓取 7 类源
    3. 去重 + 新鲜度过滤
    4. 写入 SQLite，得到 new_items
    5. 分数过滤 + 截断
    6. 批量翻译英文标题为中文
    7. 保存 HTML 报告
    8. Story 由独立 Lark Scheduler 投递
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import sys
from datetime import datetime, timezone
from pathlib import Path

from trendradar.ai import build_gemini_client
from trendradar.ai.analyzer import DailyDigestAnalyzer, NarrativeLimits
from trendradar.ai.translator import build_translation_client
from trendradar.ai_frontier.detector import filter_new_for_push
from trendradar.ai_frontier.fetcher import fetch_and_process
from trendradar.ai_frontier.renderer import save_html_report
from trendradar.ai_frontier.storage import AIFrontierStorage
from trendradar.ai_frontier.translator import translate_items
from trendradar.core.locking import LockUnavailable, runtime_locks
from trendradar.core.settings import load_settings, load_yaml_config
from trendradar.intelligence.gemini_wording import build_story_wording_client
from trendradar.intelligence.integration import open_intelligence_storage
from trendradar.intelligence.translation import CanonicalTitleTranslator
from trendradar.ops.maintenance import read_guard
from trendradar.services.translation_service import TranslationService
from trendradar.utils.logging import log

DEFAULT_CONFIG_PATH = "config/config.yaml"


def load_ai_frontier_config(config_path: str | Path = DEFAULT_CONFIG_PATH) -> dict:
    """从 YAML 加载 ai_frontier 配置节点。不存在则返回默认值"""
    path = Path(config_path)
    if not path.exists():
        log.warning(f"配置文件不存在: {path}，使用默认配置")
        return _default_config()

    try:
        data = load_yaml_config(path)
    except Exception as e:
        log.warning(f"配置文件解析失败: {e}，使用默认配置")
        return _default_config()

    cfg = data.get("ai_frontier") or {}
    # 覆盖默认值
    merged = _default_config()
    _deep_merge(merged, cfg)
    return merged


def _default_config() -> dict:
    return {
        "enabled": True,
        "freshness_hours": 24,
        "translate": True,
        "push": {
            "min_score_hackernews": 50,
            "min_score_reddit": 30,
            "min_stars_github": 100,
            "min_score_podcast": 0,
            "min_score_blog": 0,
            "max_items_per_push": 30,
        },
        "sources": {
            "arxiv": {"enabled": True},
            "reddit": {"enabled": True},
            "hackernews": {"enabled": True},
            "github_trending": {"enabled": True},
            "x_nitter": {"enabled": True},
            "youtube_podcast": {
                "enabled": True,
                "feeds": [
                    {"name": "Latent Space", "url": "https://www.youtube.com/@LatentSpacePod"},
                    {
                        "name": "Training Data",
                        "url": "https://www.youtube.com/playlist?list=PLOhHNjZItNnMm5tdW61JpnyxeYH5NDDx8",
                    },
                    {"name": "No Priors", "url": "https://www.youtube.com/@NoPriorsPodcast"},
                    {"name": "Unsupervised Learning", "url": "https://www.youtube.com/@RedpointAI"},
                    {
                        "name": "The MAD Podcast with Matt Turck",
                        "url": "https://www.youtube.com/@DataDrivenNYC",
                    },
                    {
                        "name": "AI & I by Every",
                        "url": "https://www.youtube.com/playlist?list=PLuMcoKK9mKgHtW_o9h5sGO2vXrffKHwJL",
                    },
                ],
                "max_items_per_feed": 5,
            },
            "official_blog": {
                "enabled": True,
                "sites": [
                    {
                        "name": "Anthropic Engineering",
                        "url": "https://www.anthropic.com/engineering",
                        "include_patterns": ["anthropic.com/engineering"],
                    },
                    {
                        "name": "Claude Blog",
                        "url": "https://claude.com/blog",
                        "include_patterns": ["claude.com/blog"],
                    },
                ],
                "max_items_per_site": 10,
            },
        },
    }


def _deep_merge(base: dict, override: dict) -> None:
    """递归合并 override 到 base"""
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v




def _open_frontier_storage(settings):
    """Open the AI Frontier store with the deployment database policy."""
    parameters = inspect.signature(AIFrontierStorage).parameters
    kwargs = {}
    if "synchronous" in parameters:
        kwargs["synchronous"] = settings.intelligence_sqlite_synchronous
    if "allow_create" in parameters:
        kwargs["allow_create"] = not settings.intelligence_require_existing
    if "allow_migrate" in parameters:
        kwargs["allow_migrate"] = not settings.intelligence_require_existing
    return AIFrontierStorage(settings.ai_frontier_database_path, **kwargs)


async def _run(config_path: str) -> int:
    settings = load_settings(config_path, fallback_to_empty=True)
    cfg = load_ai_frontier_config(config_path)

    if not cfg.get("enabled", True):
        log.info("AI 前沿已禁用（config.ai_frontier.enabled=false）")
        return 0

    log.start("AI 前沿聚合开始")
    run_start = datetime.now(tz=timezone.utc).isoformat()

    gemini_client = build_gemini_client(settings)
    translation_service = TranslationService(
        gemini_api_key="", gemini_client=build_translation_client(settings)
    )

    intelligence_storage = open_intelligence_storage(
        settings.intelligence_enabled,
        settings.intelligence_database_path,
        story_config=settings.intelligence_story_config,
        require_existing=settings.intelligence_require_existing,
        synchronous=settings.intelligence_sqlite_synchronous,
    )
    story_wording_client = (
        build_story_wording_client(
            settings,
            story_config=settings.intelligence_story_config,
            gemini_client=gemini_client,
        )
        if intelligence_storage is not None
        else None
    )
    digest_analyzer = None
    if gemini_client is not None and intelligence_storage is not None:
        try:
            story_config = settings.intelligence_story_config
            report_config = story_config.get("report")
            report_config = report_config if isinstance(report_config, dict) else {}
            digest_config = report_config.get("digest")
            digest_config = digest_config if isinstance(digest_config, dict) else {}
            digest_analyzer = DailyDigestAnalyzer(
                gemini_client,
                limits=NarrativeLimits.from_mapping(digest_config),
            )
        except Exception as exc:
            log.warning("Daily digest analyzer unavailable", error_type=type(exc).__name__)

    # 1. 抓取 + 去重 + 新鲜度
    try:
        parameters = inspect.signature(fetch_and_process).parameters
        if "use_adapters" in parameters:
            fetch_options = {
                "use_adapters": settings.intelligence_enabled,
                "intelligence_storage": intelligence_storage,
                "story_wording_client": story_wording_client,
                "digest_analyzer": digest_analyzer,
                "title_translator": CanonicalTitleTranslator(
                    translation_service.batch_translate_titles
                    if cfg.get("translate", True) and translation_service.translation_tools else None
                ),
            }
            fetch_options = {
                key: value
                for key, value in fetch_options.items()
                if key in parameters
            }
            items = await fetch_and_process(cfg, **fetch_options)
        else:
            items = await fetch_and_process(cfg)
    finally:
        if intelligence_storage is not None:
            intelligence_storage.close()
    if not items:
        log.warning("本次无抓取结果")
        return 0

    # 2. 写入 SQLite，得到新增条目
    with _open_frontier_storage(settings) as storage:
        new_items, _ = storage.upsert_items(items)
        log.info(f"数据库新增 {len(new_items)} 条")

    # 3. 分数过滤 + 排序 + 截断
    push_cfg = cfg.get("push") or {}
    to_push = filter_new_for_push(new_items, push_cfg)

    # 4. 翻译
    translated = 0
    if cfg.get("translate", True):
        translate_items(
            to_push,
            gemini_api_key=None,
            translation_service=translation_service,
            gemini_client=gemini_client,
        )
        translated = sum(bool(item.title_translated) for item in to_push)
        log.info(f"翻译条目 {translated}")

    # 5. HTML 报告
    try:
        save_html_report(to_push, output_dir="output/ai_frontier")
    except Exception as e:
        log.warning("保存 HTML 失败", error=str(e))


    log.success(f"AI 前沿任务完成 (start={run_start})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="TrendRadar AI Frontier Crawler")
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help="配置文件路径（默认 config/config.yaml）",
    )
    args = parser.parse_args()

    try:
        settings = load_settings(args.config, fallback_to_empty=True)
        if read_guard(settings.intelligence_database_path) is not None:
            log.warning("AI Frontier collection blocked by persistent maintenance guard")
            return 0
        with runtime_locks(settings.intelligence_database_path, "collector"):
            return asyncio.run(_run(args.config))
    except LockUnavailable as exc:
        log.warning(
            "AI Frontier collection skipped because another collector is active",
            error=str(exc),
        )
        return 0
    except KeyboardInterrupt:
        log.warning("用户中断")
        return 130
    except Exception as e:
        log.error("AI 前沿运行错误", error=str(e))
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
