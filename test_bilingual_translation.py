#!/usr/bin/env python3
"""
双语翻译功能测试脚本
验证中英文双语翻译是否正常工作
"""

import sys
sys.path.insert(0, '.')

from trendradar.services.translation_service import TranslationService
from trendradar.storage.base import NewsItem


def test_bilingual_translation():
    """测试双语翻译功能"""
    print("=" * 60)
    print("双语翻译功能测试")
    print("=" * 60)
    
    # 初始化翻译服务
    translation_service = TranslationService()
    
    if not translation_service.translation_tools:
        print("❌ 翻译工具初始化失败")
        return False
    
    # 创建测试新闻条目
    test_items = [
        NewsItem(
            title="AI Revolution Transforms Healthcare Industry",
            source_id="tech_news",
            source_name="Tech News Daily",
            rank=1,
            url="https://example.com/ai-healthcare",
            summary="Major hospitals adopt artificial intelligence systems for diagnosis and treatment planning."
        ),
        NewsItem(
            title="人工智能改变医疗行业",
            source_id="tech_daily",
            source_name="科技日报",
            rank=1,
            url="https://example.com/ai-healthcare-cn",
            summary="主要医院采用人工智能系统进行诊断和治疗规划。"
        ),
        NewsItem(
            title="Global Markets Rally on Economic Data",
            source_id="finance_news",
            source_name="财经新闻网",
            rank=2,
            url="https://example.com/global-markets",
            summary="投资者对经济数据反应积极，全球股市大幅上涨。"
        )
    ]
    
    print(f"测试新闻条目数量：{len(test_items)}")
    print()
    
    # 执行双语翻译
    translated_count = translation_service.translate_news_items(test_items, skip_existing=False)
    
    print(f"\n翻译完成，成功翻译 {translated_count} 条\n")
    
    # 验证翻译结果
    success = True
    for i, item in enumerate(test_items, 1):
        print(f"【新闻 {i}】")
        print(f"  原标题：{item.title}")
        print(f"  是否英文：{item.is_english}")
        
        if item.title_translated:
            print(f"  中文翻译：{item.title_translated}")
        else:
            print("  中文翻译：无")
            success = False
        
        if item.title_english:
            print(f"  英文翻译：{item.title_english}")
        else:
            print("  英文翻译：无")
            success = False
        
        if item.summary:
            print(f"  原摘要：{item.summary[:50]}...")
            
            if item.summary_translated:
                print(f"  中文摘要：{item.summary_translated[:50]}...")
            else:
                print("  中文摘要：无")
                success = False
            
            if item.summary_english:
                print(f"  英文摘要：{item.summary_english[:50]}...")
            else:
                print("  英文摘要：无")
                success = False
        
        print()
    
    return success


def test_bark_formatting():
    """测试 Bark 格式化"""
    print("=" * 60)
    print("Bark 双语格式化测试")
    print("=" * 60)
    
    from trendradar.report.formatter import format_title_for_platform
    
    # 测试数据
    test_data = {
        "title": "Climate Summit Reaches Historic Agreement",
        "title_translated": "气候峰会达成历史性协议",
        "title_english": "",  # 英文原文，不需要英文翻译
        "source_name": "Global News",
        "ranks": [1],
        "rank_threshold": 5,
        "url": "https://example.com/climate-summit",
        "mobile_url": "",
        "time_display": "09:30",
        "count": 1,
        "is_new": True
    }
    
    # 格式化为 Bark 内容
    bark_content = format_title_for_platform("bark", test_data, show_source=True)
    
    print("Bark 格式化结果：")
    print(bark_content)
    print()
    
    # 测试中文新闻的英文翻译
    test_data_cn = {
        "title": "全球市场因通胀降温迹象而反弹",
        "title_translated": "",  # 中文原文，不需要中文翻译
        "title_english": "Global Markets Rally as Inflation Shows Signs of Cooling",
        "source_name": "财经新闻网",
        "ranks": [2],
        "rank_threshold": 5,
        "url": "https://example.com/global-markets",
        "mobile_url": "",
        "time_display": "10:15",
        "count": 1,
        "is_new": False
    }
    
    bark_content_cn = format_title_for_platform("bark", test_data_cn, show_source=True)
    
    print("中文新闻 Bark 格式化结果：")
    print(bark_content_cn)
    
    return True


def main():
    """主测试函数"""
    print("🧪 双语翻译功能测试 🧪\n")
    
    try:
        # 测试 1: 双语翻译
        translation_success = test_bilingual_translation()
        
        # 测试 2: Bark 格式化
        formatting_success = test_bark_formatting()
        
        if translation_success and formatting_success:
            print("✅ 所有测试通过！双语翻译功能正常工作。")
            return 0
        else:
            print("❌ 部分测试失败，请检查实现。")
            return 1
            
    except Exception as e:
        print(f"❌ 测试过程中出现错误：{e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
