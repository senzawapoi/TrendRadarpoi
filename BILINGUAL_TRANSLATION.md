# 双语翻译功能文档

## 概述

TrendRadar 现已支持中英文双语翻译功能，能够自动检测新闻标题的语言，并提供相应语言的翻译。

## 功能特性

### 1. 自动语言检测
- 自动检测新闻标题是英文还是中文
- 支持混合语言内容的处理

### 2. 双向翻译
- **英文 → 中文**: 英文新闻标题自动翻译为中文
- **中文 → 英文**: 中文新闻标题自动翻译为英文
- **摘要翻译**: 支持新闻摘要的双语翻译

### 3. 智能存储
- `title_translated`: 英文→中文翻译
- `title_english`: 中文→英文翻译
- `summary_translated`: 英文→中文摘要翻译
- `summary_english`: 中文→英文摘要翻译

### 4. 多平台支持
- **Bark 推送**: 显示双语内容，带国旗标识
- **飞书**: 支持双语标题显示
- **其他平台**: 可扩展支持

## 数据库变更

### 新增字段

```sql
-- 英文标题翻译字段
ALTER TABLE news_items ADD COLUMN title_english TEXT DEFAULT '';

-- 摘要字段
ALTER TABLE news_items ADD COLUMN summary TEXT DEFAULT '';

-- 摘要翻译字段
ALTER TABLE news_items ADD COLUMN summary_translated TEXT DEFAULT '';

-- 英文摘要翻译字段
ALTER TABLE news_items ADD COLUMN summary_english TEXT DEFAULT '';
```

### 迁移脚本

运行迁移脚本添加新字段：
```bash
sqlite3 your_database.db < trendradar/storage/migration_bilingual.sql
```

## 使用方法

### 1. 启用双语翻译

翻译服务会自动检测语言并进行相应翻译：

```python
from trendradar.services.translation_service import TranslationService

# 初始化翻译服务
translator = TranslationService(gemini_api_key="your_api_key")

# 翻译新闻条目（自动双语）
translated_count = translator.translate_news_items(news_items)
```

### 2. MCP 工具使用

```python
from mcp_server.tools.translation import TranslationTools

translator = TranslationTools()

# 双语翻译模式
result = translator.translate_news_list(
    news_list,
    fields=["title", "summary"],
    bilingual=True  # 启用双语翻译
)
```

### 3. Bark 推送格式

Bark 推送现在会显示双语内容：

```
[来源] 🆕 原标题
🇨🇳 中文翻译
🇺🇸 English Translation
```

## 配置说明

### Gemini API 配置

确保在配置中设置了 Gemini API 密钥：

```yaml
# config/config.yaml
translation:
  gemini_api_key: "your_gemini_api_key"
```

### 环境变量

也可以通过环境变量设置：
```bash
export GEMINI_API_KEY="your_gemini_api_key"
```

## 测试

### 运行测试脚本

```bash
python test_bilingual_translation.py
```

### 运行演示脚本

```bash
python demo_translation.py
```

## 示例输出

### 英文新闻翻译
```
原标题: "AI Revolution Transforms Healthcare Industry"
中文翻译: "人工智能革命改变医疗行业"
```

### 中文新闻翻译
```
原标题: "全球市场因通胀降温迹象而反弹"
英文翻译: "Global Markets Rally as Inflation Shows Signs of Cooling"
```

### Bark 推送效果
```
[Tech News] 🆕 AI Revolution Transforms Healthcare Industry
🇨🇳 人工智能革命改变医疗行业
```

## 性能优化

### 1. 翻译缓存
- 避免重复翻译相同内容
- 智能跳过已有翻译的条目

### 2. 批量处理
- 支持批量翻译提高效率
- 异常处理确保服务稳定性

### 3. 索引优化
- 为翻译字段添加数据库索引
- 提高查询性能

## 故障排除

### 常见问题

1. **翻译失败**
   - 检查 Gemini API 密钥是否正确
   - 确认网络连接正常
   - 查看 API 配额是否用完

2. **数据库字段缺失**
   - 运行迁移脚本
   - 检查数据库权限

3. **Bark 推送格式异常**
   - 确认已更新 formatter.py
   - 检查字段名称是否正确

### 日志查看

翻译过程会输出详细日志：
```
[TranslationService] 翻译：'AI Revolution...' -> '人工智能革命...' (en->zh)
[TranslationService] 翻译完成：共处理 3 条，成功翻译 3 条
```

## 更新日志

### v2.0.0
- ✅ 新增双语翻译支持
- ✅ 数据库字段扩展
- ✅ Bark 推送双语显示
- ✅ 摘要翻译功能
- ✅ 自动语言检测优化

## 贡献指南

如需改进双语翻译功能：

1. **代码贡献**
   - 修改 `trendradar/services/translation_service.py`
   - 更新 `trendradar/report/formatter.py`
   - 添加相应测试

2. **文档更新**
   - 更新本文档
   - 添加使用示例
   - 完善故障排除指南

3. **测试**
   - 运行 `test_bilingual_translation.py`
   - 添加新测试用例
   - 验证多平台兼容性

## 许可证

本功能遵循项目原有许可证。
