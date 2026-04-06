#!/usr/bin/env python3
"""
双语翻译集成脚本
这个脚本会在现有数据抓取完成后，对数据进行双语翻译处理
"""

import sys
import os
sys.path.insert(0, '.')

from trendradar.services.translation_service import TranslationService
from trendradar.storage.manager import get_storage_manager
from trendradar.context import AppContext
from trendradar.core.config import load_config
from trendradar.core.loader import load_config


def integrate_translation():
    """集成双语翻译功能到现有数据"""
    print("🔄 开始双语翻译集成...")
    
    try:
        # 加载配置
        config = load_config()
        
        # 创建应用上下文
        ctx = AppContext(config)
        
        # 获取存储管理器
        storage_manager = ctx.get_storage_manager()
        
        # 初始化翻译服务
        translator = TranslationService()
        
        if not translator.translation_tools:
            print("❌ 翻译服务未初始化，跳过翻译")
            return False
        
        # 读取今天的热榜数据
        print("📖 读取热榜数据...")
        news_data = storage_manager.get_today_all_data()
        
        if not news_data or not news_data.items:
            print("❌ 没有找到热榜数据")
            return False
        
        print(f"✅ 找到 {len(news_data.items)} 条热榜数据")
        
        # 翻译热榜数据
        translated_count = translator.translate_news_data(news_data, skip_existing=True)
        print(f"✅ 热榜数据翻译完成，成功翻译 {translated_count} 条")
        
        # 读取RSS数据
        print("📰 读取RSS数据...")
        try:
            # 尝试读取最新的RSS数据
            from trendradar.crawler.rss.fetcher import RSSFetcher, RSSFeedConfig
            from trendradar.crawler.rss.parser import RSSParser
            
            # 获取RSS配置
            rss_feeds = []
            if hasattr(ctx, 'rss_feeds'):
                for feed in ctx.rss_feeds:
                    if feed.enabled:
                        rss_feeds.append(RSSFeedConfig(
                            id=feed.id,
                            name=feed.name,
                            url=feed.url,
                            enabled=feed.enabled,
                            max_age_days=getattr(feed, 'max_age_days', None)
                        ))
            
            if rss_feeds:
                fetcher = RSSFetcher(rss_feeds)
                rss_data = fetcher.fetch_all()
                
                if rss_data and rss_data.items:
                    print(f"✅ 找到 {len(rss_data.items)} 条RSS数据")
                    
                    # 转换为NewsData格式进行翻译
                    from trendradar.core.data import convert_rss_results_to_news_data
                    rss_news_data = convert_rss_results_to_news_data(
                        [], {}, [], rss_data.crawl_time, rss_data.date
                    )
                    
                    # 翻译RSS数据
                    rss_translated_count = translator.translate_news_data(rss_news_data, skip_existing=True)
                    print(f"✅ RSS数据翻译完成，成功翻译 {rss_translated_count} 条")
                    
                    # 保存翻译后的数据
                    if storage_manager.save_rss_data(rss_data):
                        print("✅ RSS翻译数据已保存到存储后端")
                else:
                    print("❌ 没有找到RSS数据")
            else:
                print("❌ 没有配置RSS源")
                
        except Exception as e:
            print(f"❌ RSS数据处理错误: {e}")
        
        print("🎉 双语翻译集成完成！")
        return True
        
    except Exception as e:
        print(f"❌ 翻译集成过程中出现错误: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = integrate_translation()
    if success:
        print("\n✅ 双语翻译功能已成功集成到现有数据中")
        print("现在可以运行主程序来推送包含双语翻译的新闻")
    else:
        print("\n❌ 双语翻译集成失败")
    
    sys.exit(0 if success else 1)
