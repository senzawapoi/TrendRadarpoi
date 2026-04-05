#!/usr/bin/env python3
"""
新闻翻译功能演示脚本
展示英文新闻翻译的实际效果
"""

import sys
sys.path.insert(0, '/workspace')

from mcp_server.tools.translation import TranslationTools


def demo_single_translation():
    """演示单段文本翻译"""
    print("=" * 60)
    print("【演示 1】单段文本翻译")
    print("=" * 60)
    
    translator = TranslationTools()
    
    # 测试英文新闻标题
    test_texts = [
        "Breaking: Tech Giants Report Record Quarterly Earnings",
        "Scientists Discover New Species in Amazon Rainforest",
        "Global Markets Rally as Inflation Shows Signs of Cooling"
    ]
    
    for text in test_texts:
        print(f"\n原文 (EN): {text}")
        result = translator.translate_text(text)
        
        if result.get("success"):
            print(f"译文 (ZH): {result['translated_text']}")
            print(f"使用 API: {result.get('api_used', 'Unknown')}")
        else:
            print(f"翻译失败: {result.get('error', {}).get('message', 'Unknown error')}")
        print("-" * 60)


def demo_news_list_translation():
    """演示新闻列表批量翻译"""
    print("\n" + "=" * 60)
    print("【演示 2】新闻列表批量翻译")
    print("=" * 60)
    
    translator = TranslationTools()
    
    # 模拟英文新闻列表
    news_list = [
        {
            "title": "AI Revolution Transforms Healthcare Industry",
            "summary": "Major hospitals adopt artificial intelligence systems for diagnosis and treatment planning, showing promising results in early trials.",
            "source": "Tech News Daily",
            "url": "https://example.com/news/1"
        },
        {
            "title": "Climate Summit Reaches Historic Agreement",
            "summary": "World leaders commit to ambitious carbon reduction targets in landmark deal aimed at limiting global warming to 1.5 degrees Celsius.",
            "source": "Global Affairs",
            "url": "https://example.com/news/2"
        },
        {
            "title": "Already Translated: 人工智能改变医疗行业",  # 已包含中文，应被跳过
            "summary": "This is already in Chinese.",
            "source": "Test Source",
            "url": "https://example.com/news/3"
        },
        {
            "title": "Electric Vehicle Sales Surge Worldwide",
            "summary": "EV adoption accelerates as battery costs decline and charging infrastructure expands across major markets.",
            "source": "Auto Industry Report",
            "url": "https://example.com/news/4"
        }
    ]
    
    print(f"\n待翻译新闻数量：{len(news_list)} 条\n")
    
    result = translator.translate_news_list(
        news_list,
        fields=["title", "summary"],
        skip_if_chinese=True
    )
    
    if result.get("success"):
        print(f"翻译完成!")
        print(f"总数：{result['total']}")
        print(f"实际翻译数：{result['translated_count']}")
        print(f"源语言：{result['source_lang']} -> 目标语言：{result['target_lang']}\n")
        
        for i, news in enumerate(result['translated_news'], 1):
            print(f"[新闻 {i}]")
            print(f"  原标题：{news['title']}")
            if 'title_translated' in news:
                print(f"  翻译后：{news['title_translated']}")
            
            if 'summary' in news:
                print(f"  原摘要：{news['summary'][:80]}..." if len(news['summary']) > 80 else f"  原摘要：{news['summary']}")
            if 'summary_translated' in news:
                translated_summary = news['summary_translated']
                print(f"  翻译后：{translated_summary[:80]}..." if len(translated_summary) > 80 else f"  翻译后：{translated_summary}")
            
            print()


def demo_language_detection():
    """演示语言检测功能"""
    print("=" * 60)
    print("【演示 3】语言检测功能")
    print("=" * 60)
    
    translator = TranslationTools()
    
    test_cases = [
        "This is English text",
        "这是中文文本",
        "Mixed: Hello 世界",
        "Python programming language"
    ]
    
    for text in test_cases:
        lang = translator.detect_language(text)
        print(f"文本：'{text}' => 检测语言：{lang}")


def main():
    """主函数"""
    print("\n🌍 新闻翻译功能演示 🌍\n")
    
    try:
        # 演示 1: 单段翻译
        demo_single_translation()
        
        # 演示 2: 批量翻译
        demo_news_list_translation()
        
        # 演示 3: 语言检测
        demo_language_detection()
        
        print("\n✅ 所有演示完成!\n")
        
    except Exception as e:
        print(f"\n❌ 演示过程中出现错误：{e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
