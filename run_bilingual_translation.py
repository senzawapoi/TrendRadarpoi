#!/usr/bin/env python3
"""
手动运行双语翻译和推送的脚本
"""

import sys
sys.path.insert(0, '.')

from trendradar.services.translation_service import TranslationService
from trendradar.storage.base import NewsItem
from trendradar.storage.manager import get_storage_manager
from trendradar.context import AppContext
from trendradar.core.loader import load_config
from trendradar.notification.push_manager import PushRecordManager


def main():
    """主函数：运行双语翻译并推送"""
    print("🚀 开始手动双语翻译和推送...")
    
    try:
        # 加载配置
        config = load_config()
        ctx = AppContext(config)
        storage_manager = ctx.get_storage_manager()
        
        # 初始化翻译服务
        translator = TranslationService()
        
        if not translator.translation_tools:
            print("❌ 翻译服务未初始化")
            return False
        
        print("✅ 翻译服务初始化成功")
        
        # 模拟BBC新闻数据（实际应该从数据库读取）
        test_news = [
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
        
        print(f"📰 准备翻译 {len(test_news)} 条BBC新闻...")
        
        # 执行双语翻译
        translated_count = translator.translate_news_items(test_news, skip_existing=False)
        
        if translated_count > 0:
            print(f"✅ 翻译完成，成功翻译 {translated_count} 条新闻")
            
            # 显示翻译结果
            print("\n📋 翻译结果:")
            for i, item in enumerate(test_news, 1):
                print(f"\n【新闻 {i}】")
                print(f"  原标题: {item.title}")
                if item.title_translated:
                    print(f"  🇨🇳 中文翻译: {item.title_translated}")
                if item.title_english:
                    print(f"  🇺🇸 英文翻译: {item.title_english}")
                if item.summary and item.summary_translated:
                    print(f"  🇨🇳 中文摘要: {item.summary_translated[:50]}...")
                if item.summary and item.summary_english:
                    print(f"  🇺🇸 英文摘要: {item.summary_english[:50]}...")
            
            # 准备推送数据
            print("\n📱 准备Bark推送...")
            
            # 创建推送管理器
            push_manager = ctx.create_push_manager()
            
            # 格式化推送内容
            push_content = "🌍 BBC双语新闻推送\n\n"
            
            for i, item in enumerate(test_news, 1):
                push_content += f"【{i}】{item.title}\n"
                if item.title_translated:
                    push_content += f"🇨🇳 {item.title_translated}\n"
                if item.title_english:
                    push_content += f"🇺🇸 {item.title_english}\n"
                push_content += "\n"
            
            push_content += f"📊 共 {len(test_news)} 条新闻 | 翻译时间: {ctx.format_time()}"
            
            # 发送Bark推送
            try:
                # 使用现有的Bark配置
                bark_url = ctx.config.get("NOTIFICATION", {}).get("CHANNELS", {}).get("BARK", {}).get("URL", "")
                
                if bark_url:
                    import requests
                    
                    # 发送到Bark
                    response = requests.post(
                        f"{bark_url}",
                        json={
                            "title": "BBC双语新闻测试",
                            "body": push_content,
                            "sound": "alarm",
                            "icon": "https://via.placeholder.com/150"
                        },
                        headers={
                            "Content-Type": "application/json"
                        }
                    )
                    
                    if response.status_code == 200:
                        print("✅ Bark推送发送成功！")
                        print(f"📱 推送内容预览:\n{push_content}")
                    else:
                        print(f"❌ Bark推送发送失败，状态码: {response.status_code}")
                else:
                    print("❌ 未配置Bark推送URL")
                    
            except Exception as e:
                print(f"❌ 推送过程中出现错误: {e}")
                
        else:
            print("❌ 翻译失败")
            return False
            
        print("\n🎉 双语翻译和推送完成！")
        return True
        
    except Exception as e:
        print(f"❌ 执行过程中出现错误: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
