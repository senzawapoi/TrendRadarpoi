#!/usr/bin/env python3
"""
简单双语翻译和推送脚本
"""

import sys
import os
import requests
sys.path.insert(0, '.')

# 设置环境变量
os.environ['GEMINI_API_KEY'] = 'AIzaSyDoPYCP3M9aRY3ecaOjO_zPP1Nw3iTUXYg'
os.environ['BARK_URL'] = 'https://api.day.app/AocxghzJ2Thdd3VP9Mpd7n/'

from trendradar.services.translation_service import TranslationService
from trendradar.storage.base import NewsItem

def main():
    print("🚀 启动TrendRadar双语版本")
    
    try:
        translator = TranslationService()
        
        if not translator.translation_tools:
            print("❌ 翻译服务未初始化")
            return False
        
        print("✅ 翻译服务初始化成功")
        
        # 模拟BBC新闻
        test_news = [
            NewsItem(
                title="UK inflation falls to lowest level in nearly three years",
                source_id="bbc_news",
                source_name="BBC新闻",
                rank=1,
                url="https://www.bbc.com/news/business-68055384",
                summary="The Consumer Prices Index shows inflation dropping to 2.3% in March."
            )
        ]
        
        print(f"📰 翻译 {len(test_news)} 条BBC新闻...")
        
        # 执行翻译
        translated_count = translator.translate_news_items(test_news, skip_existing=False)
        
        if translated_count > 0:
            print(f"✅ 翻译完成，成功翻译 {translated_count} 条")
            
            # 显示结果
            print("\n📋 翻译结果:")
            for i, item in enumerate(test_news, 1):
                print(f"【{i}】{item.title}")
                if item.title_translated:
                    print(f"  🇨🇳 {item.title_translated}")
                if item.title_english:
                    print(f"  🇺🇸 {item.title_english}")
            
            # 发送Bark推送
            print("\n📱 发送Bark推送...")
            
            push_content = "🌍 BBC双语新闻推送\n\n"
            
            for i, item in enumerate(test_news, 1):
                push_content += f"【{i}】{item.title}\n"
                if item.title_translated:
                    push_content += f"🇨🇳 {item.title_translated}\n"
                if item.title_english:
                    push_content += f"🇺🇸 {item.title_english}\n"
                push_content += "\n"
            
            bark_url = os.environ.get('BARK_URL', '')
            
            if bark_url:
                response = requests.post(
                    bark_url,
                    json={
                        'title': '🌍 BBC双语新闻',
                        'body': push_content,
                        'sound': 'alarm'
                    },
                    headers={
                        'Content-Type': 'application/json'
                    }
                )
                
                if response.status_code == 200:
                    print("✅ Bark推送发送成功！")
                else:
                    print(f"❌ Bark推送失败，状态码: {response.status_code}")
            else:
                print("❌ 未配置BARK推送URL")
                
            print("\n🎉 双语翻译和推送完成！")
            return True
            
        except Exception as e:
            print(f"❌ 错误: {e}")
            return False
    
    if __name__ == "__main__":
        success = main()
        sys.exit(0 if success else 1)
