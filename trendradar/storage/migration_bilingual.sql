-- 双语翻译功能数据库迁移脚本
-- 添加英文翻译字段支持中英文双语翻译

-- ============================================
-- 添加英文翻译字段到 news_items 表
-- ============================================

-- 添加英文标题翻译字段
ALTER TABLE news_items ADD COLUMN title_english TEXT DEFAULT '';

-- 添加摘要字段（如果不存在）
ALTER TABLE news_items ADD COLUMN summary TEXT DEFAULT '';

-- 添加摘要翻译字段
ALTER TABLE news_items ADD COLUMN summary_translated TEXT DEFAULT '';

-- 添加英文摘要翻译字段
ALTER TABLE news_items ADD COLUMN summary_english TEXT DEFAULT '';

-- ============================================
-- 更新现有记录的注释说明
-- ============================================

-- title_translated: 英文->中文翻译
-- title_english: 中文->英文翻译  
-- summary: 原始摘要内容
-- summary_translated: 英文->中文摘要翻译
-- summary_english: 中文->英文摘要翻译

-- ============================================
-- 创建索引以提高查询性能
-- ============================================

-- 为翻译字段创建索引
CREATE INDEX IF NOT EXISTS idx_news_title_translated ON news_items(title_translated);
CREATE INDEX IF NOT EXISTS idx_news_title_english ON news_items(title_english);
CREATE INDEX IF NOT EXISTS idx_news_summary_translated ON news_items(summary_translated);
CREATE INDEX IF NOT EXISTS idx_news_summary_english ON news_items(summary_english);

-- ============================================
-- 迁移完成提示
-- ============================================
-- 迁移完成后，系统将支持：
-- 1. 英文标题自动翻译为中文
-- 2. 中文标题自动翻译为英文
-- 3. 摘要内容的双语翻译
-- 4. Bark 推送包含双语内容
