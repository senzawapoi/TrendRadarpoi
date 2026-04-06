#!/usr/bin/env python3
"""
TrendRadar 主程序
集成双语翻译功能，使用项目原有架构
支持热榜平台 + RSS 订阅双路数据抓取
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def _convert_rss_items_to_list(rss_data, ctx) -> List[Dict]:
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
            try:
                feed_max_age_map[feed_id] = int(max_age)
            except (ValueError, TypeError):
                pass

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
            })

    if filtered_count > 0:
        print(f"[RSS] 新鲜度过滤：跳过 {filtered_count} 篇超过指定天数的旧文章")

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


def main():
    """主函数"""
    try:
        from trendradar.core import load_config
        from trendradar.context import AppContext
        from trendradar.services.translation_service import TranslationService
        from trendradar.crawler.rss import RSSFetcher, RSSFeedConfig
        from trendradar.crawler.fetcher import DataFetcher
        from trendradar.storage.base import (
            NewsItem, NewsData,
            convert_crawl_results_to_news_data,
        )

        print("🚀 TrendRadar 双语版本启动")
        print("=" * 50)

        # 加载配置 & 创建上下文
        config = load_config()
        ctx = AppContext(config)
        print("✅ 配置加载成功")

        # 初始化翻译服务
        translator = TranslationService()
        if translator.translation_tools:
            print("✅ Gemini 双语翻译服务就绪")
        else:
            print("⚠️ 翻译服务未初始化，将使用单语模式")

        # 初始化存储管理器
        storage_manager = ctx.get_storage_manager()
        request_interval = config.get("REQUEST_INTERVAL", 100)
        proxy_url = config.get("PROXY_URL", "")
        translated_count = 0
        total_hot_titles = 0

        # 读取报告模式（daily / current / incremental）
        report_mode = config.get("REPORT_MODE", "current")
        print(f"📋 报告模式: {report_mode}")

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
            print(f"\n🔥 开始热榜数据抓取: {len(platforms)} 个平台")
            ids = []
            for p in platforms:
                if "name" in p:
                    ids.append((p["id"], p["name"]))
                else:
                    ids.append(p["id"])
            print(f"  监控平台: {[p.get('name', p['id']) for p in platforms]}")

            Path("output").mkdir(parents=True, exist_ok=True)
            data_fetcher = DataFetcher(proxy_url=proxy_url)
            results, id_to_name, failed_ids = data_fetcher.crawl_websites(
                ids, request_interval
            )

            total_hot_titles = sum(len(titles) for titles in results.values())
            print(f"✅ 热榜抓取完成: {total_hot_titles} 条标题")

            # 转换并保存热榜数据 → output/news/
            crawl_time = ctx.get_time_display()
            crawl_date = ctx.format_date()
            hot_news_data = convert_crawl_results_to_news_data(
                results, id_to_name, failed_ids, crawl_time, crawl_date
            )

            # 翻译热榜数据
            if translator.translation_tools and hot_news_data.items:
                hot_news_items = []
                for source_id, items_list in hot_news_data.items.items():
                    hot_news_items.extend(items_list)

                if hot_news_items:
                    print(f"\n🔄 翻译热榜数据: {len(hot_news_items)} 条...")
                    hot_translated = translator.translate_news_items(
                        hot_news_items, skip_existing=False
                    )
                    translated_count += hot_translated
                    print(f"✅ 热榜翻译完成: {hot_translated}/{len(hot_news_items)} 条")

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
                print(f"[热榜] 词频统计跳过: {e}")
        else:
            print("\n⚠️ 未配置热榜平台，跳过热榜抓取")

        # ================================================================
        # B. RSS 数据抓取
        # ================================================================
        rss_items_list = []
        rss_stats = None
        rss_new_stats = None
        total_rss_items = 0
        rss_data = None

        if ctx.rss_enabled:
            print(f"\n📰 开始 RSS 数据抓取...")

            rss_feeds = ctx.rss_feeds
            if not rss_feeds:
                import yaml
                with open('config/config.yaml', 'r', encoding='utf-8') as f:
                    raw_config = yaml.safe_load(f)
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
                print(f"📋 RSS 源配置: {len(feeds)} 个源")
                for feed in feeds:
                    print(f"  - {feed.name} ({feed.id})")

                rss_config = ctx.rss_config
                fetcher = RSSFetcher(
                    feeds=feeds,
                    request_interval=rss_config.get("REQUEST_INTERVAL", 2000),
                    timeout=rss_config.get("TIMEOUT", 15),
                    use_proxy=rss_config.get("USE_PROXY", False),
                    proxy_url=rss_config.get("PROXY_URL", ""),
                    timezone=ctx.timezone,
                )
                rss_data = fetcher.fetch_all()

                if rss_data and rss_data.items:
                    total_rss_items = sum(len(items) for items in rss_data.items.values())
                    print(f"✅ RSS 数据抓取成功: {total_rss_items} 条新闻")

                    # 保存 RSS 数据 → output/rss/
                    if storage_manager.save_rss_data(rss_data):
                        print("✅ RSS 数据已保存到 output/rss/")

                    # 转换为列表格式
                    rss_items_list = _convert_rss_items_to_list(rss_data, ctx)
                    print(f"📋 过滤后 RSS 条目: {len(rss_items_list)} 条")

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

                        print(f"\n🔄 翻译 RSS 数据: {len(rss_news_items)} 条...")
                        rss_translated = translator.translate_news_items(
                            rss_news_items, skip_existing=False
                        )
                        translated_count += rss_translated
                        print(f"✅ RSS 翻译完成: {rss_translated}/{len(rss_news_items)} 条")

                        # 回写翻译到 rss_items_list，使 HTML/推送显示双语
                        _apply_translations_to_rss_items(rss_items_list, rss_news_items)

                        # 保存翻译后的 RSS 新闻数据 → output/news/
                        rss_news_data = NewsData(
                            date=rss_data.date,
                            crawl_time=rss_data.crawl_time,
                            items={},
                            id_to_name=rss_data.id_to_name,
                            failed_ids=rss_data.failed_ids,
                        )
                        for item in rss_news_items:
                            if item.source_id not in rss_news_data.items:
                                rss_news_data.items[item.source_id] = []
                            rss_news_data.items[item.source_id].append(item)
                        storage_manager.save_news_data(rss_news_data)

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
                            print(f"[RSS] 检测到 {len(rss_new_items_list)} 条新增")

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
                        print(f"[RSS] 关键词统计跳过: {e}")
                else:
                    print("⚠️ RSS 数据抓取失败")
        else:
            print("\n⚠️ RSS 未启用，跳过 RSS 抓取")

        # ================================================================
        # C. 生成 HTML 报告 + 发送通知
        # ================================================================
        total_all = total_hot_titles + len(rss_items_list)
        all_failed = failed_ids + (rss_data.failed_ids if rss_data else [])
        all_id_to_name = {**id_to_name}
        if rss_data:
            all_id_to_name.update(rss_data.id_to_name)

        # 生成 HTML 报告 → output/index.html
        print("\n📊 生成 HTML 报告...")
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
            print(f"✅ HTML 报告已生成: {html_file}")

        # 发送通知
        print("\n📱 发送通知...")
        # 增量模式：如果没有新增标题且非首次抓取，跳过通知
        skip_notification = False
        if report_mode == "incremental":
            has_hot_new = bool(new_titles and any(new_titles.values()))
            has_rss_new = bool(rss_new_stats)
            is_first = storage_manager.is_first_crawl_today()
            if not is_first and not has_hot_new and not has_rss_new:
                skip_notification = True
                print("  ℹ️ 增量模式：无新增内容，跳过通知")

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
                status = "✅" if success else "❌"
                print(f"  {status} {channel}")
        else:
            print("  ⚠️ 未配置通知渠道或无内容推送")

        # 清理资源
        ctx.cleanup()

        print(f"\n🎉 TrendRadar 运行完成！")
        print(f"  � 热榜: {total_hot_titles} 条")
        print(f"  📰 RSS: {len(rss_items_list)} 条")
        print(f"  🔄 翻译: {translated_count} 条")
        print(f"  📊 报告: {html_file or '未生成'}")
        return True

    except Exception as e:
        print(f"❌ 运行错误: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
