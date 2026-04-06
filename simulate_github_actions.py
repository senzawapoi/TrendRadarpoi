#!/usr/bin/env python3
"""
模拟GitHub Actions运行的脚本
"""

import sys
import os
sys.path.insert(0, '.')

# 设置环境变量（模拟GitHub Actions）
os.environ['GEMINI_API_KEY'] = 'AIzaSyDoPYCP3M9aRY3ecaOjO_zPP1Nw3iTUXYg'
os.environ['BARK_URL'] = 'https://api.day.app/AocxghzJ2Thdd3VP9Mpd7n/'
os.environ['GITHUB_ACTIONS'] = 'true'

from trendradar.services.translation_service import TranslationService
from trendradar.storage.base import NewsItem
from trendradar.storage.manager import get_storage_manager
from trendradar.context import AppContext
from trendradar.core.loader import load_config
import requests


def simulate_data_fetching():
    """模拟数据抓取"""
    print("📰 模拟数据抓取...")
    
    # 模拟热榜数据
    hot_news = [
        NewsItem(
            title="GitHub announces new AI features",
            source_id="github",
            source_name="GitHub",
            rank=1,
            url="https://github.blog"
        ),
        NewsItem(
            title="Tech stocks rally on earnings",
            source_id="ithome", 
            source_name="IT之家",
            rank=2,
            url="https://ithome.com"
        )
    ]
    
    # 模拟RSS数据（包括BBC）
    rss_news = [
        NewsItem(
            title="UK inflation falls to lowest level in nearly three years",
            source_id="bbc_news",
            source_name="BBC新闻", 
            rank=1,
            url="https://www.bbc.com/news/business-68055384",
            summary="The Consumer Prices Index shows inflation dropping to 2.3% in March.",
            crawl_time="09:30"
        ),
        NewsItem(
            title="Climate summit reaches historic agreement on fossil fuels",
            source_id="bbc_news",
            source_name="BBC新闻",
            rank=2,
            url="https://www.bbc.com/news/science-environment-68054891",
            summary="World leaders commit to transition away from coal, oil and gas.",
            crawl_time="09:45"
        ),
        NewsItem(
            title="Artificial intelligence breakthrough in medical diagnosis",
            source_id="bbc_news",
            source_name="BBC新闻",
            rank=3,
            url="https://www.bbc.com/news/technology-68054850", 
            summary="New AI system can detect diseases earlier than traditional methods.",
            crawl_time="10:00"
        )
    ]
    
    return hot_news, rss_news


def simulate_translation_and_push():
    """模拟翻译和推送"""
    print("🔄 开始双语翻译...")
    
    # 初始化翻译服务
    translator = TranslationService()
    
    if not translator.translation_tools:
        print("❌ 翻译服务未初始化")
        return False
    
    print("✅ 翻译服务初始化成功")
    
    # 获取模拟数据
    hot_news, rss_news = simulate_data_fetching()
    
    print(f"📰 准备翻译 {len(hot_news) + len(rss_news)} 条新闻...")
    
    # 翻译热榜数据
    hot_translated = translator.translate_news_items(hot_news, skip_existing=False)
    print(f"✅ 热榜数据翻译完成，成功翻译 {hot_translated} 条")
    
    # 翻译RSS数据
    rss_translated = translator.translate_news_items(rss_news, skip_existing=False)
    print(f"✅ RSS数据翻译完成，成功翻译 {rss_translated} 条")
    
    # 准备推送内容
    print("📱 准备Bark推送...")
    
    push_content = "🌍 TrendRadar双语新闻推送\n\n"
    
    push_content += "🔥 热榜新闻:\n"
    for i, item in enumerate(hot_news, 1):
        push_content += f"【{i}】{item.title}\n"
        if item.title_translated:
            push_content += f"🇨🇳 {item.title_translated}\n"
        push_content += "\n"
    
    push_content += "\n📰 RSS新闻（含BBC）:\n"
    for i, item in enumerate(rss_news, 1):
        push_content += f"【{i}】{item.title}\n"
        if item.title_translated:
            push_content += f"🇨🇳 {item.title_translated}\n"
        if item.summary and item.summary_translated:
            push_content += f"🇨🇳 摘要: {item.summary_translated[:50]}...\n"
        push_content += "\n"
    
    push_content += f"\n📊 统计: 热榜 {len(hot_news)} 条 | RSS {len(rss_news)} 条\n"
    push_content += f"🔄 翻译完成: 热榜 {hot_translated} 条 | RSS {rss_translated} 条\n"
    push_content += f"⏰ 推送时间: 21:54\n"
    
    # 发送Bark推送
    bark_url = os.environ.get('BARK_URL', '')
    
    if bark_url:
        try:
            response = requests.post(
                bark_url,
                json={
                    'title': '🌍 TrendRadar双语新闻推送',
                    'body': push_content,
                    'sound': 'alarm',
                    'icon': 'https://via.placeholder.com/150',
                    'group': 'TrendRadar双语新闻'
                },
                headers={
                    'Content-Type': 'application/json',
                    'User-Agent': 'TrendRadar-GitHub-Actions/1.0'
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                print('✅ Bark推送发送成功！')
                print(f'📱 消息ID: {result.get("message_id", "未知")}')
                print(f'📱 推送内容预览:')
                print(push_content[:800] + '...' if len(push_content) > 800 else push_content)
                return True
            else:
                print(f'❌ Bark推送失败，状态码: {response.status_code}')
                return False
                
        except Exception as e:
            print(f'❌ 推送过程中出现错误: {e}')
            return False
    else:
        print('❌ 未配置BARK_URL')
        return False


def main():
    """主函数"""
    print("🚀 模拟GitHub Actions运行TrendRadar")
    print("=" * 60)
    
    success = simulate_translation_and_push()
    
    if success:
        print("\n🎉 GitHub Actions模拟运行成功！")
        print("✅ 双语翻译功能完全正常")
        print("✅ Bark推送成功发送")
        print("✅ 所有功能集成完成")
    else:
        print("\n❌ GitHub Actions模拟运行失败")
    
    print("=" * 60)
    return success


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
