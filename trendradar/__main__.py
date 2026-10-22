#!/usr/bin/env python3
"""
TrendRadar 主程序
集成双语翻译功能，使用项目原有架构
支持热榜平台 + RSS 订阅双路数据抓取
"""

import sys
from collections.abc import Mapping
from contextlib import suppress
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from trendradar.core.locking import LockUnavailable, runtime_locks  # noqa: E402
from trendradar.core.settings import load_settings  # noqa: E402
from trendradar.ops.maintenance import read_guard  # noqa: E402
from trendradar.utils.logging import get_run_id, log  # noqa: E402


def _run_security_best_effort(
    *,
    intelligence_enabled: bool,
    intelligence_storage: object | None,
    security_config: object,
    collected_at: datetime,
    nvd_api_key: str | None,
    wording_client: object | None,
    narrative_analyzer: object | None = None,
) -> object | None:
    """Run the additive security pipeline once, without affecting legacy output."""
    if (
        not intelligence_enabled
        or intelligence_storage is None
        or not isinstance(security_config, Mapping)
        or not security_config.get("enabled", True)
    ):
        return None
    try:
        from trendradar.domains.security.collector import run_security_pipeline

        if nvd_api_key is None:
            from trendradar.core.settings import load_settings

            nvd_api_key = load_settings().nvd_api_key

        summary = run_security_pipeline(
            security_config,
            storage=intelligence_storage,
            collected_at=collected_at,
            nvd_api_key=nvd_api_key,
            wording_client=wording_client,
            narrative_analyzer=narrative_analyzer,
        )
        log.info(
            "安全情报处理完成",
            data_refreshed=summary.data_refreshed,
            persistence_succeeded=summary.persistence_succeeded,
            stories=summary.stories_analyzed,
            report=str(summary.report_path or "未生成"),
            errors=len(summary.errors),
        )
        return summary
    except Exception as exc:
        log.error("安全情报处理失败，旧链路继续", error=str(exc))
        return None


def _convert_rss_items_to_list(rss_data, ctx) -> list[dict]:
    """
    将 RSS 条目转换为列表格式，并应用新鲜度过滤
    （复刻原始 NewsAnalyzer._convert_rss_items_to_list）
    """
    from trendradar.utils.time import is_within_days

    rss_items = []
    filtered_count = 0

    rss_config = ctx.rss_config
    freshness_config = rss_config.get("FRESHNESS_FILTER", {})
    freshness_enabled = freshness_config.get("ENABLED", True)
    default_max_age_days = freshness_config.get("MAX_AGE_DAYS", 3)
    timezone = ctx.timezone

    feed_max_age_map = {}
    for feed_cfg in ctx.rss_feeds:
        feed_id = feed_cfg.get("id", "")
        max_age = feed_cfg.get("max_age_days")
        if max_age is not None:
            with suppress(ValueError, TypeError):
                feed_max_age_map[feed_id] = int(max_age)

    for feed_id, items in rss_data.items.items():
        max_days = feed_max_age_map.get(feed_id, default_max_age_days)

        for item in items:
            if freshness_enabled and max_days > 0:
                if item.published_at and not is_within_days(item.published_at, max_days, timezone):
                    filtered_count += 1
                    continue

            rss_items.append({
                "title": item.title,
                "feed_id": feed_id,
                "feed_name": rss_data.id_to_name.get(feed_id, feed_id),
                "url": item.url,
                "published_at": item.published_at,
                "summary": item.summary,
                "author": item.author,
                "_canonical_content_id": getattr(item, "_canonical_content_id", ""),
            })

    if filtered_count > 0:
        log.info(f"新鲜度过滤：跳过 {filtered_count} 篇超过指定天数的旧文章", feed_id=feed_id)

    return rss_items


def _apply_translations_to_rss_items(rss_items_list, news_items):
    """
    将翻译结果应用到 rss_items_list
    英文标题 → 替换为中文翻译（原文可通过链接查看）
    中文标题 → 保持不变
    """
    for i, item in enumerate(news_items):
        if i >= len(rss_items_list):
            break
        if item.is_english and item.title_translated:
            rss_items_list[i]["title"] = item.title_translated


def _apply_translations_to_hot_results(results, hot_news_items):
    """
    将翻译结果应用到热榜 results dict
    英文标题 → 替换为中文翻译
    中文标题 → 保持不变
    """
    item_map = {}
    for item in hot_news_items:
        key = (item.source_id, item.title)
        item_map[key] = item

    new_results = {}
    for source_id, titles_data in results.items():
        new_titles_data = {}
        for title, data in titles_data.items():
            key = (source_id, title)
            item = item_map.get(key)
            if item and item.is_english and item.title_translated:
                new_titles_data[item.title_translated] = data
            else:
                new_titles_data[title] = data
        new_results[source_id] = new_titles_data
    return new_results


def _run_main():
    """主函数"""
    intelligence_storage = None
    try:
        from trendradar.ai import build_gemini_client
        from trendradar.ai.analyzer import (
            DailyDigestAnalyzer,
            NarrativeLimits,
            SecurityNarrativeAnalyzer,
        )
        from trendradar.context import AppContext
        from trendradar.core import load_config
        from trendradar.core.settings import load_settings
        from trendradar.crawler.fetcher import DataFetcher
        from trendradar.crawler.rss import RSSFeedConfig, RSSFetcher
        from trendradar.intelligence.gemini_wording import build_story_wording_client
        from trendradar.intelligence.integration import (
            fetch_newsnow_with_adapters,
            fetch_rss_with_adapters,
            open_intelligence_storage,
        )
        from trendradar.intelligence.translation import translate_news_items_canonically
        from trendradar.services.translation_service import TranslationService
        from trendradar.storage.base import (
            NewsItem,
            convert_crawl_results_to_news_data,
            convert_news_data_to_results,
        )

        log.start(f"TrendRadar 双语版本启动 (run_id={get_run_id()})")

        # 加载配置 & 创建上下文
        config = load_config()
        ctx = AppContext(config)
        log.success("配置加载成功")

        # 初始化翻译服务
        settings = load_settings(fallback_to_empty=True)
        gemini_client = build_gemini_client(settings)
        translator = TranslationService(gemini_client=gemini_client)
        if translator.translation_tools:
            log.success("Gemini 双语翻译服务就绪")
        else:
            log.warning("翻译服务未初始化，将使用单语模式")

        # 初始化存储管理器
        storage_manager = ctx.get_storage_manager()
        intelligence_config = config.get("INTELLIGENCE", {})
        intelligence_enabled = intelligence_config.get("ENABLED", True)
        intelligence_storage = open_intelligence_storage(
            intelligence_enabled,
            settings.intelligence_database_path,
            story_config=intelligence_config.get("STORY"),
            require_existing=settings.intelligence_require_existing,
            synchronous=settings.intelligence_sqlite_synchronous,
        )
        story_wording_client = (
            build_story_wording_client(
                settings,
                story_config=intelligence_config.get("STORY"),
                gemini_client=gemini_client,
            )
            if intelligence_storage is not None
            else None
        )
        digest_analyzer = None
        security_narrative_analyzer = None
        if gemini_client is not None and intelligence_storage is not None:
            try:
                story_config = intelligence_config.get("STORY")
                story_config = story_config if isinstance(story_config, Mapping) else {}
                report_config = story_config.get("report")
                report_config = report_config if isinstance(report_config, Mapping) else {}
                digest_config = report_config.get("digest")
                digest_config = digest_config if isinstance(digest_config, Mapping) else {}
                digest_analyzer = DailyDigestAnalyzer(
                    gemini_client,
                    limits=NarrativeLimits.from_mapping(digest_config),
                )
            except Exception as exc:
                log.warning("Daily digest analyzer unavailable", error_type=type(exc).__name__)
            try:
                security_config = intelligence_config.get("SECURITY")
                security_config = (
                    security_config if isinstance(security_config, Mapping) else {}
                )
                narrative_config = security_config.get("narrative")
                narrative_config = (
                    narrative_config if isinstance(narrative_config, Mapping) else {}
                )
                security_narrative_analyzer = SecurityNarrativeAnalyzer(
                    gemini_client,
                    limits=NarrativeLimits.from_mapping(
                        narrative_config,
                        default_output_chars=4000,
                    ),
                )
            except Exception as exc:
                log.warning(
                    "Security narrative analyzer unavailable",
                    error_type=type(exc).__name__,
                )
        request_interval = config.get("REQUEST_INTERVAL", 100)
        proxy_url = config.get("PROXY_URL", "")
        translated_count = 0
        canonical_translation_cache = {}
        total_hot_titles = 0

        # 读取报告模式（daily / current / incremental）
        report_mode = config.get("REPORT_MODE", "current")
        log.info(f"报告模式: {report_mode}", mode=report_mode)

        # ================================================================
        # A. 热榜数据抓取
        # ================================================================
        results = {}
        id_to_name = {}
        failed_ids = []
        hot_stats = []
        new_titles = None

        platforms = ctx.platforms
        if platforms:
            log.info("开始热榜数据抓取", platforms=len(platforms), platform_names=[p.get('name', p['id']) for p in platforms])

            ids = []
            for p in platforms:
                if "name" in p:
                    ids.append((p["id"], p["name"]))
                else:
                    ids.append(p["id"])

            Path("output").mkdir(parents=True, exist_ok=True)
            data_fetcher = DataFetcher(proxy_url=proxy_url)
            crawl_time = ctx.get_time_display()
            crawl_date = ctx.format_date()
            if intelligence_enabled:
                hot_news_data = fetch_newsnow_with_adapters(
                    platforms,
                    fetcher=data_fetcher,
                    request_interval_ms=request_interval,
                    crawl_date=crawl_date,
                    crawl_time=crawl_time,
                    collected_at=ctx.get_time(),
                    storage=intelligence_storage,
                    story_wording_client=story_wording_client,
                    digest_analyzer=digest_analyzer,
                )
                results, id_to_name, _title_info = convert_news_data_to_results(hot_news_data)
                failed_ids = hot_news_data.failed_ids
            else:
                results, id_to_name, failed_ids = data_fetcher.crawl_websites(
                    ids, request_interval
                )
                hot_news_data = convert_crawl_results_to_news_data(
                    results, id_to_name, failed_ids, crawl_time, crawl_date
                )

            total_hot_titles = sum(len(titles) for titles in results.values())
            log.success("热榜抓取完成", total_titles=total_hot_titles, failed=len(failed_ids))

            # 转换并保存热榜数据 → output/news/
            # 翻译热榜数据
            if translator.translation_tools and hot_news_data.items:
                hot_news_items = []
                for _source_id, items_list in hot_news_data.items.items():
                    hot_news_items.extend(items_list)

                if hot_news_items:
                    log.info("翻译热榜数据", count=len(hot_news_items))
                    hot_translated = translate_news_items_canonically(
                        hot_news_items,
                        lambda items: translator.translate_news_items(
                            items,
                            skip_existing=False,
                        ),
                        cache=canonical_translation_cache,
                    )
                    translated_count += hot_translated
                    log.success("热榜翻译完成", translated=hot_translated, total=len(hot_news_items))

                    # 回写翻译到 results dict，使 HTML/推送显示双语
                    results = _apply_translations_to_hot_results(results, hot_news_items)

            storage_manager.save_news_data(hot_news_data)

            # 保存标题到 TXT（用于分析）
            if config.get("STORAGE", {}).get("FORMATS", {}).get("TXT", True):
                ctx.save_titles(results, id_to_name, failed_ids)

            # 检测新增标题
            platform_ids = [p["id"] for p in platforms]
            new_titles = ctx.detect_new_titles(platform_ids)

            # 词频统计（热榜）
            try:
                word_groups, filter_words, global_filters = ctx.load_frequency_words()
                title_info, _, _ = ctx.read_today_titles(platform_ids, quiet=True)
                hot_stats, _ = ctx.count_frequency(
                    results, word_groups, filter_words, id_to_name,
                    title_info=title_info, new_titles=new_titles,
                    mode=report_mode, global_filters=global_filters, quiet=False,
                )
            except (FileNotFoundError, ImportError) as e:
                log.warning("热榜词频统计跳过", error=str(e))
        else:
            log.warning("未配置热榜平台，跳过热榜抓取")

        # ================================================================
        # B. RSS 数据抓取
        # ================================================================
        rss_items_list = []
        rss_stats = None
        rss_new_stats = None
        total_rss_items = 0
        rss_data = None

        if ctx.rss_enabled:
            log.info("开始 RSS 数据抓取")

            rss_feeds = ctx.rss_feeds
            if not rss_feeds:
                from trendradar.core.settings import load_settings

                raw_config = load_settings().as_dict()
                rss_feeds = raw_config.get('rss', {}).get('feeds', [])

            feeds = []
            for feed_config in rss_feeds:
                max_age_days_raw = feed_config.get("max_age_days")
                max_age_days = None
                if max_age_days_raw is not None:
                    try:
                        max_age_days = int(max_age_days_raw)
                        if max_age_days < 0:
                            max_age_days = None
                    except (ValueError, TypeError):
                        max_age_days = None

                feed = RSSFeedConfig(
                    id=feed_config.get("id", ""),
                    name=feed_config.get("name", ""),
                    url=feed_config.get("url", ""),
                    max_items=feed_config.get("max_items", 50),
                    enabled=feed_config.get("enabled", True),
                    max_age_days=max_age_days,
                )
                if feed.id and feed.url and feed.enabled:
                    feeds.append(feed)

            if feeds:
                log.info("RSS 源配置", feed_count=len(feeds), feeds=[f"{f.name} ({f.id})" for f in feeds])
                for feed in feeds:
                    log.debug(f"  - {feed.name} ({feed.id})")

                rss_config = ctx.rss_config
                fetcher = RSSFetcher(
                    feeds=feeds,
                    request_interval=rss_config.get("REQUEST_INTERVAL", 2000),
                    timeout=rss_config.get("TIMEOUT", 15),
                    use_proxy=rss_config.get("USE_PROXY", False),
                    proxy_url=rss_config.get("PROXY_URL", ""),
                    timezone=ctx.timezone,
                )
                if intelligence_enabled:
                    rss_data = fetch_rss_with_adapters(
                        feeds,
                        max_concurrency=5,
                        crawl_date=ctx.format_date(),
                        crawl_time=ctx.get_time_display(),
                        collected_at=ctx.get_time(),
                        storage=intelligence_storage,
                        story_wording_client=story_wording_client,
                        digest_analyzer=digest_analyzer,
                        request_interval=rss_config.get("REQUEST_INTERVAL", 2000),
                        timeout=rss_config.get("TIMEOUT", 15),
                        use_proxy=rss_config.get("USE_PROXY", False),
                        proxy_url=rss_config.get("PROXY_URL", ""),
                        timezone=ctx.timezone,
                    )
                else:
                    rss_data = fetcher.fetch_all()

                if rss_data and rss_data.items:
                    total_rss_items = sum(len(items) for items in rss_data.items.values())
                    log.success("RSS 数据抓取成功", total_items=total_rss_items)

                    # 保存 RSS 数据 → output/rss/
                    if storage_manager.save_rss_data(rss_data):
                        log.success("RSS 数据已保存到 output/rss/")

                    # 转换为列表格式
                    rss_items_list = _convert_rss_items_to_list(rss_data, ctx)
                    log.info("过滤后 RSS 条目", count=len(rss_items_list))

                    # 翻译 RSS 数据
                    rss_news_items = []
                    if translator.translation_tools and rss_items_list:
                        for i, rss_item in enumerate(rss_items_list, 1):
                            news_item = NewsItem(
                                title=rss_item["title"],
                                source_id=rss_item["feed_id"],
                                source_name=rss_item["feed_name"],
                                rank=i,
                                url=rss_item.get("url", ""),
                                summary=rss_item.get("summary", ""),
                                crawl_time=rss_data.crawl_time,
                            )
                            rss_news_items.append(news_item)
                            canonical_id = rss_item.get("_canonical_content_id")
                            if canonical_id:
                                news_item._canonical_content_id = canonical_id

                        log.info("翻译 RSS 数据", count=len(rss_news_items))
                        rss_translated = translate_news_items_canonically(
                            rss_news_items,
                            lambda items: translator.translate_news_items(
                                items,
                                skip_existing=False,
                            ),
                            cache=canonical_translation_cache,
                        )
                        translated_count += rss_translated
                        log.success("RSS 翻译完成", translated=rss_translated, total=len(rss_news_items))

                        # 回写翻译到 rss_items_list，使 HTML/推送显示双语
                        _apply_translations_to_rss_items(rss_items_list, rss_news_items)

                    # 检测新增 RSS 条目
                    rss_new_items_list = None
                    new_items_dict = storage_manager.detect_new_rss_items(rss_data)
                    if new_items_dict:
                        from trendradar.storage.base import RSSData as _RSSData
                        new_rss = _RSSData(
                            date=rss_data.date,
                            crawl_time=rss_data.crawl_time,
                            items=new_items_dict,
                            id_to_name=rss_data.id_to_name,
                            failed_ids=[],
                        )
                        rss_new_items_list = _convert_rss_items_to_list(new_rss, ctx)
                        if rss_new_items_list:
                            # 从已翻译的 rss_items_list 回写翻译到新增列表
                            translated_map = {item.get("url", ""): item.get("title", "") for item in rss_items_list if item.get("url")}
                            for new_item in rss_new_items_list:
                                url = new_item.get("url", "")
                                if url and url in translated_map:
                                    new_item["title"] = translated_map[url]
                            log.info("检测到 RSS 新增条目", count=len(rss_new_items_list))

                    # RSS 关键词统计
                    try:
                        from trendradar.core.analyzer import count_rss_frequency
                        word_groups, filter_words, global_filters = ctx.load_frequency_words()
                        max_news_per_keyword = config.get("MAX_NEWS_PER_KEYWORD", 0)
                        sort_by_position_first = config.get("SORT_BY_POSITION_FIRST", False)

                        if rss_items_list:
                            rss_stats, _ = count_rss_frequency(
                                rss_items=rss_items_list,
                                word_groups=word_groups,
                                filter_words=filter_words,
                                global_filters=global_filters,
                                new_items=rss_new_items_list,
                                max_news_per_keyword=max_news_per_keyword,
                                sort_by_position_first=sort_by_position_first,
                                timezone=ctx.timezone,
                                rank_threshold=ctx.rank_threshold,
                                quiet=False,
                            )
                        if rss_new_items_list:
                            rss_new_stats, _ = count_rss_frequency(
                                rss_items=rss_new_items_list,
                                word_groups=word_groups,
                                filter_words=filter_words,
                                global_filters=global_filters,
                                new_items=rss_new_items_list,
                                max_news_per_keyword=max_news_per_keyword,
                                sort_by_position_first=sort_by_position_first,
                                timezone=ctx.timezone,
                                rank_threshold=ctx.rank_threshold,
                                quiet=True,
                            )
                    except (FileNotFoundError, ImportError) as e:
                        log.warning("RSS 关键词统计跳过", error=str(e))
                else:
                    log.warning("RSS 数据抓取失败")
            else:
                log.warning("RSS 未启用，跳过 RSS 抓取")

        # ================================================================
        # C. 安全情报（独立、增量、失败隔离）
        # ================================================================
        _run_security_best_effort(
            intelligence_enabled=intelligence_enabled,
            intelligence_storage=intelligence_storage,
            security_config=intelligence_config.get("SECURITY", {}),
            collected_at=ctx.get_time(),
            nvd_api_key=settings.nvd_api_key,
            wording_client=story_wording_client,
            narrative_analyzer=security_narrative_analyzer,
        )

        # ================================================================
        # D. 生成 HTML 报告 + 发送通知
        # ================================================================
        # incremental 模式优化：按源分组 + RSS 只显示新增
        if report_mode == "incremental" and not storage_manager.is_first_crawl_today():
            # 热榜按平台分组（复用已有函数）
            if hot_stats:
                from trendradar.core.analyzer import convert_keyword_stats_to_platform_stats
                hot_stats = convert_keyword_stats_to_platform_stats(
                    hot_stats, ctx.weight_config, ctx.rank_threshold
                )

            # RSS 只显示新增，按订阅源分组
            if rss_new_stats:
                source_map = {}
                for stat in rss_new_stats:
                    for t in stat.get("titles", []):
                        src = t.get("source_name", "未知")
                        source_map.setdefault(src, []).append(t)
                rss_stats = [
                    {"word": src, "count": len(titles), "position": i, "titles": titles, "percentage": 0}
                    for i, (src, titles) in enumerate(source_map.items())
                ]
            else:
                rss_stats = None
            rss_new_stats = None  # 去掉"RSS 本次新增"区块

        total_all = total_hot_titles + len(rss_items_list)
        all_failed = failed_ids + (rss_data.failed_ids if rss_data else [])
        all_id_to_name = {**id_to_name}
        if rss_data:
            all_id_to_name.update(rss_data.id_to_name)

        # 生成 HTML 报告 → output/index.html
        log.info("生成 HTML 报告")
        html_file = ctx.generate_html(
            stats=hot_stats,
            total_titles=total_all,
            failed_ids=all_failed,
            new_titles=new_titles,
            id_to_name=all_id_to_name,
            mode=report_mode,
            is_daily_summary=True,
            rss_items=rss_stats,
            rss_new_items=rss_new_stats,
        )
        if html_file:
            log.success("HTML 报告已生成", file=html_file)

        # 发送通知
        log.info("发送通知")
        # 增量模式：如果没有新增标题且非首次抓取，跳过通知
        skip_notification = False
        if report_mode == "incremental":
            has_hot_new = bool(new_titles and any(new_titles.values()))
            has_rss_new = bool(rss_new_stats)
            is_first = storage_manager.is_first_crawl_today()
            if not is_first and not has_hot_new and not has_rss_new:
                skip_notification = True
                log.info("增量模式：无新增内容，跳过通知")

        report_data = ctx.prepare_report(
            stats=hot_stats,
            failed_ids=all_failed,
            new_titles=new_titles,
            id_to_name=all_id_to_name,
            mode=report_mode,
        )
        dispatcher = ctx.create_notification_dispatcher()

        if skip_notification:
            notify_results = {}
        else:
            notify_results = dispatcher.dispatch_all(
                report_data=report_data,
                report_type="热点新闻分析",
                mode=report_mode,
                html_file_path=html_file,
                rss_items=rss_stats,
                rss_new_items=rss_new_stats,
            )

        if notify_results:
            for channel, success in notify_results.items():
                log.info("通知发送结果", channel=channel, success=success)
        else:
            log.warning("未配置通知渠道或无内容推送")

        # 清理资源
        ctx.cleanup()
        if intelligence_storage is not None:
            intelligence_storage.close()
            intelligence_storage = None

        log.success("TrendRadar 运行完成！")
        log.info("运行统计", hot_titles=total_hot_titles, rss_items=len(rss_items_list), translated=translated_count, report_file=html_file or "未生成")
        return True

    except Exception as e:
        if intelligence_storage is not None:
            intelligence_storage.close()
        log.error("运行错误", error=str(e))
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run one main collection while holding the shared collector lock."""
    settings = load_settings(fallback_to_empty=True)
    if read_guard(settings.intelligence_database_path) is not None:
        log.warning("TrendRadar collection blocked by persistent maintenance guard")
        return False
    try:
        with runtime_locks(settings.intelligence_database_path, "collector"):
            return _run_main()
    except LockUnavailable as exc:
        log.warning(
            "TrendRadar collection skipped because another collector is active",
            error=str(exc),
        )
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
