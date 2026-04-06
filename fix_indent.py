# 修复缩进问题的脚本
import re

# 读取原始文件
with open('trendradar/__main__.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 修复第1060行的缩进问题
# 将8个空格替换为12个空格
content = content.replace('            print(f"✅ 热榜数据翻译完成，成功翻译 {translated_count} 条")\n            \n            # 翻译RSS数据（如果存在）\n            if hasattr(self, \'rss_data\') and self.rss_data:', 
                                          '            print(f"✅ 热榜数据翻译完成，成功翻译 {translated_count} 条")\n            \n            # 翻译RSS数据（如果存在）\n            if hasattr(self, \'rss_data\') and self.rss_data:')

# 写回修复后的文件
with open('trendradar/__main__.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ 缩进问题已修复")
