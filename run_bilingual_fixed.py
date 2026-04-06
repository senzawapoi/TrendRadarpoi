#!/usr/bin/env python3
"""
修复版 - 集成双语翻译功能
"""

import sys
import os
sys.path.insert(0, '.')

# 设置环境变量
os.environ['GEMINI_API_KEY'] = 'AIzaSyDoPYCP3M9aRY3ecaOjO_zPP1Nw3iTUXYg'
os.environ['BARK_URL'] = 'https://api.day.app/AocxghzJ2Thdd3VP9Mpd7n/'
os.environ['GITHUB_ACTIONS'] = 'true'

from trendradar.services.translation_service import TranslationService
from trendradar.storage.base import NewsItem

def main():
    """主函数：运行双语翻译和推送"""
    print("🚀 启动TrendRadar双语版本")
    print("=" * 50)
    
    try:
        # 初始化翻译服务
        translator = TranslationService()
        
        if not translator.translation_tools:
            print("❌ 翻译服务未初始化")
            return False
        
        print("✅ 翻译服务初始化成功")
        
        # 模拟BBC新闻数据
        test_news = [
            NewsItem(
                title="UK inflation falls to lowest level in nearly three years",
                source_id="bbc_news",
                source_name="BBC新闻",
                rank=1,
                url="https://www.bbc.com/news/business-68055384",
                summary="The Consumer Prices Index shows inflation dropping to 2.3% in March."
            ),
            NewsItem(
                title="Climate summit reaches historic agreement on fossil fuels",
                source_id="bbc_news",
                source_name="BBC新闻",
                rank=2,
                url="https://www.bbc.com/news/science-environment-68054891",
                summary="World leaders commit to transition away from coal, oil and gas."
            ),
            NewsItem(
                title="Artificial intelligence breakthrough in medical diagnosis",
                source_id="bbc_news",
                source_name="BBC新闻",
                rank=3,
                url="https://www.bbc.com/news/technology-68054850",
                summary="New AI system can detect diseases earlier than traditional methods."
            )
        ]
        
        print(f"📰 准备翻译 {len(test_news)} 条BBC新闻...")
        
        # 执行双语翻译
        translated_count = translator.translate_news_items(test_news, skip_existing=False)
        
        if translated_count > 0:
            print(f"✅ 翻译完成，成功翻译 {translated_count} 条新闻")
            
            # 显示翻译结果
            print("\n📋 翻译结果:")
            for i, item in enumerate(test_news, 1):
                print(f"【新闻 {i}】")
                print(f"  原标题: {item.title}")
                if item.title_translated:
                    print(f"  🇨🇳 中文翻译: {item.title_translated}")
                if item.title_english:
                    print(f"  🇺🇸 英文翻译: {item.title_english}")
                if item.summary and item.summary_translated:
                    print(f"  🇨🇳 中文摘要: {item.summary_translated[:50]}...")
                if item.summary and item.summary_english:
                    print(f"  🇺🇸 英文摘要: {item.summary_english[:50]}...")
                print()
            
            # 发送Bark推送
            print("\n📱 准备发送Bark推送...")
            push_content = "🌍 BBC双语新闻推送\n\n"
            
            for i, item in enumerate(test_news, 1):
                push_content += f"【{i}】{item.title}\n"
                if item.title_translated:
                    push_content += f"🇨🇳 {item.title_translated}\n"
                if item.title_english:
                    push_content += f"🇺🇸 {item.title_english}\n"
                push_content += "\n"
            
            push_content += f"\n📊 总计: {len(test_news)} 条新闻\n"
            push_content += f"🔄 翻译时间: {os.environ.get('TIME', '21:54')}\n"
            
            bark_url = os.environ.get('BARK_URL', '')
            
            if bark_url:
                import requests
                
                try:
                    response = requests.post(
                        bark_url,
                        json={
                            'title': '🌍 BBC双语新闻',
                            'body': push_content,
                            'sound': 'alarm',
                            'icon': 'https://via.placeholder.com/150',
                            'group': 'BBC双语新闻'
                        },
                        headers={
                            'Content-Type': 'application/json',
                            'User-Agent': 'TrendRadar-Bilingual/1.0'
                        }
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        print("✅ Bark推送发送成功！")
                        print(f"📱 消息ID: {result.get('message_id', '未知')}")
                    else:
                        print(f"❌ Bark推送失败，状态码: {response.status_code}")
                        
                except Exception as e:
                    print(f"❌ 推送过程中出现错误: {e}")
            else:
                print("❌ 未配置BARK推送URL")
                
            print("\n🎉 双语翻译和推送完成！")
            return True
            
        except Exception as e:
            print(f"❌ 运行过程中出现错误: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    if __name__ == "__main__":
        success = main()
        sys.exit(0 if success else 1)
