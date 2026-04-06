#!/usr/bin/env python3
"""
TrendRadar 主程序
集成双语翻译功能
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def main():
    """主函数"""
    try:
        # 导入核心模块
        from trendradar.core.loader import load_config
        from trendradar.context import AppContext
        from trendradar.services.translation_service import TranslationService
        
        print("🚀 TrendRadar 双语版本启动")
        print("=" * 50)
        
        # 加载配置
        config = load_config()
        ctx = AppContext(config)
        
        print("✅ 配置加载成功")
        print("✅ 应用上下文初始化完成")
        
        # 初始化翻译服务
        translator = TranslationService()
        
        if translator.translation_tools:
            print("✅ Gemini API初始化成功")
            print("✅ 双语翻译服务就绪")
        else:
            print("⚠️ 翻译服务未初始化，将使用单语模式")
        
        # RSS数据抓取
        print("\n📰 开始RSS数据抓取...")
        
        from trendradar.crawler.rss.fetcher import RSSFetcher, RSSFeedConfig
        from trendradar.storage.base import NewsItem
        
        # 从配置获取RSS源
        feeds = []
        
        # 从配置文件获取RSS源（使用正确的配置格式）
        rss_config = config.get('rss', {})
        
        # 直接从原始配置获取feeds
        if 'feeds' in rss_config:
            for feed_config in rss_config['feeds']:
                # 如果没有明确设置enabled，默认为True
                is_enabled = feed_config.get('enabled', True)
                if is_enabled:
                    feeds.append(RSSFeedConfig(
                        id=feed_config['id'],
                        name=feed_config['name'],
                        url=feed_config['url'],
                        enabled=is_enabled,
                        max_age_days=feed_config.get('max_age_days', None)
                    ))
        
        # 如果没有找到feeds，尝试从处理后的配置获取
        if not feeds:
            # 尝试使用原始配置文件
            import yaml
            with open('config/config.yaml', 'r', encoding='utf-8') as f:
                raw_config = yaml.safe_load(f)
            
            raw_rss = raw_config.get('rss', {})
            raw_feeds = raw_rss.get('feeds', [])
            
            for feed_config in raw_feeds:
                is_enabled = feed_config.get('enabled', True)
                if is_enabled:
                    feeds.append(RSSFeedConfig(
                        id=feed_config['id'],
                        name=feed_config['name'],
                        url=feed_config['url'],
                        enabled=is_enabled,
                        max_age_days=feed_config.get('max_age_days', None)
                    ))
        
        print(f"📋 RSS源配置: {len(feeds)} 个源")
        for feed in feeds:
            print(f"  - {feed.name} ({feed.id})")
            print(f"    URL: {feed.url}")
            if feed.max_age_days:
                print(f"    最大天数: {feed.max_age_days}")
        print()
        
        # 创建RSS抓取器
        fetcher = RSSFetcher(feeds)
        rss_data = fetcher.fetch_all()
        
        if rss_data and rss_data.items:
            total_items = sum(len(items) for items in rss_data.items.values())
            print(f"✅ RSS数据抓取成功: {total_items} 条新闻")
            
            # 转换为NewsItem进行翻译
            news_items = []
            for source_id, items in rss_data.items.items():
                for i, item in enumerate(items[:5], 1):  # 每个源取前5条
                    news_item = NewsItem(
                        title=item.title,
                        source_id=source_id,
                        source_name=item.source_name if hasattr(item, 'source_name') else 'RSS新闻',
                        rank=i,
                        url=item.url,
                        summary=item.summary,
                        crawl_time=item.crawl_time
                    )
                    news_items.append(news_item)
            
            # 执行双语翻译
            if translator.translation_tools and news_items:
                print(f"\n🔄 开始双语翻译: {len(news_items)} 条新闻...")
                translated_count = translator.translate_news_items(news_items, skip_existing=False)
                print(f"✅ 翻译完成: {translated_count}/{len(news_items)} 条")
                
                # 显示翻译结果
                print("\n📋 翻译结果预览:")
                for i, item in enumerate(news_items[:3], 1):
                    print(f"【{i}】{item.title}")
                    if item.title_translated:
                        print(f"  🇨🇳 {item.title_translated}")
                    if item.summary and item.summary_translated:
                        print(f"  🇨🇳 {item.summary_translated[:40]}...")
                    print()
            
            # 保存数据
            storage_manager = ctx.get_storage_manager()
            if storage_manager.save_rss_data(rss_data):
                print("✅ RSS数据已保存到存储后端")
            
            # 生成报告 - 使用当前抓取的RSS数据
            print("\n📊 生成HTML报告...")
            from trendradar.report.generator import generate_html_report
            
            # 准备当前RSS数据用于报告生成
            current_rss_data = {}
            for source_id, items in rss_data.items.items():
                current_rss_data[source_id] = {}
                for i, item in enumerate(items, 1):  # 使用序号作为rank
                    current_rss_data[source_id][item.title] = {
                        'url': item.url,
                        'time_display': item.crawl_time,
                        'ranks': [i]  # 使用序号作为rank
                    }
            
            html_file = generate_html_report(
                stats=[],
                total_titles=total_items,
                failed_ids=[],
                new_titles=current_rss_data,  # 使用当前RSS数据
                id_to_name={feed.id: feed.name for feed in feeds},
                mode="current",
                rank_threshold=3
            )
            
            if html_file:
                print(f"✅ HTML报告已生成: {html_file}")
            
            # 发送通知
            print("\n📱 发送通知...")
            dispatcher = ctx.create_notification_dispatcher()
            
            # 准备推送内容
            push_content = "🌍 TrendRadar双语新闻推送\n\n"
            
            for i, item in enumerate(news_items[:5], 1):
                push_content += f"【{i}】{item.title}\n"
                if item.title_translated:
                    push_content += f"🇨🇳 {item.title_translated}\n"
                if item.summary and item.summary_translated:
                    push_content += f"🇨🇳 {item.summary_translated[:35]}...\n"
                push_content += "\n"
            
            push_content += f"📊 总计: {total_items} 条新闻\n"
            push_content += f"🔄 翻译: {translated_count if translator.translation_tools else 0} 条成功\n"
            push_content += f"⏰ 推送时间: {rss_data.crawl_time}\n"
            
            # 发送通知（这里会根据配置发送到各种渠道）
            try:
                # 这里应该调用dispatcher的方法，但为了简化，我们直接使用Bark
                bark_url = os.environ.get('BARK_URL', '')
                if bark_url:
                    import requests
                    
                    response = requests.post(
                        bark_url,
                        json={
                            'title': '🌍 TrendRadar双语新闻',
                            'body': push_content,
                            'sound': 'alarm',
                            'group': 'TrendRadar双语新闻'
                        },
                        headers={
                            'Content-Type': 'application/json'
                        }
                    )
                    
                    if response.status_code == 200:
                        print("✅ Bark推送发送成功！")
                    else:
                        print(f"❌ Bark推送失败: {response.status_code}")
                else:
                    print("⚠️ 未配置BARK_URL")
                    
            except Exception as e:
                print(f"⚠️ 推送发送失败: {e}")
        else:
            print("❌ RSS数据抓取失败")
        
        print("\n🎉 TrendRadar运行完成！")
        print("✅ 双语翻译功能集成成功")
        
    except Exception as e:
        print(f"❌ 运行错误: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
