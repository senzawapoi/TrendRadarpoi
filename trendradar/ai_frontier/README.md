# AI Frontier - AI 前沿资讯聚合

独立的 AI 前沿资讯聚合子系统，抓取全球 AI 最新动态，使用 Gemini 3.1 Flash Lite 翻译并生成报告。新增 Story 由 Lark Scheduler 统一投递。

## 数据源

| 源 | 说明 | API |
|---|---|---|
| 📄 **ArXiv** | cs.AI / cs.LG / cs.CL 最新论文 | ArXiv Atom（免 Key）|
| 🔥 **Reddit** | r/MachineLearning / r/LocalLLaMA / r/singularity / r/OpenAI | Reddit .json（免 Key）|
| 🗞️ **HackerNews** | AI/LLM/GPT/Claude/Gemini 高分帖子 | HN Algolia Search |
| ⭐ **GitHub Trending** | 每日趋势（Python + AI 关键词筛选 All 榜）| HTML 解析 |
| 🐦 **X / Twitter** | OpenAI / Anthropic / Karpathy / Sama + follow-builders AI builders | Nitter RSS 镜像 |
| 🎙️ **AI Podcasts** | Latent Space / Training Data / No Priors 等播客 | YouTube RSS |
| 📝 **Official Blogs** | Anthropic Engineering / Claude Blog | HTML 列表解析 |

## 快速开始

### 本地运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. （可选）设置翻译密钥
export GEMINI_API_KEY="your_gemini_key"

# 3. 运行
python -m trendradar.ai_frontier
```

执行后将会：
1. 并发抓取 7 类源的最新内容
2. 按 `(source, url)` 去重，过滤 24h 外的旧条目
3. 最佳努力写入统一 `output/intelligence.db`，并继续写入兼容权威 `output/ai_frontier.db`
4. 按分数阈值过滤 + 翻译英文标题为中文
5. 保存 HTML 报告到 `output/ai_frontier/YYYY-MM-DD/HH-MM.html`
6. 新增 Story 等待独立 Lark Scheduler 投递；采集器不直接发送

### 生产调度

VPS 的 `trendradar-collect-ai.timer` 每 2 小时运行一次，与主采集共用进程锁，串行执行。`.github/workflows/ai-frontier.yml` 仅保留手动诊断，避免重复调度。

翻译使用 `gemini-3.1-flash-lite`，共享 `GEMINI_API_KEY`。失败直接保留原文，不回退 Gemma；推理模型列表不影响翻译。

## 配置

见 `config/config.yaml` 的 `ai_frontier` 节点，可自定义：
- 数据源启用/禁用
- ArXiv 分类、Reddit 子版块、HN 关键词、X 账号、Podcast、Blog 列表
- 分数阈值（HN points / Reddit upvotes / GitHub stars；Podcast/Blog 默认不过滤）
- 单次 HTML 报告最大条数（兼容配置名 `push.max_items_per_push`）
- Nitter 实例列表（镜像失效时自动回退）

## 架构

```
trendradar/ai_frontier/
├── __main__.py          # 入口：python -m trendradar.ai_frontier
├── sources/             # 7 类数据源解析器
│   ├── base.py          # AIItem/AISource 基类
│   ├── arxiv.py
│   ├── reddit.py
│   ├── hackernews.py
│   ├── github_trending.py
│   ├── nitter.py
│   ├── youtube_podcast.py
│   └── official_blog.py
├── fetcher.py           # 并发聚合 + 去重 + 新鲜度过滤
├── storage.py           # 独立 SQLite: output/ai_frontier.db
├── detector.py          # 分数过滤 + 分组
├── translator.py        # 批量翻译（复用 TranslationService.batch_translate_titles）
└── renderer.py          # Markdown + HTML 渲染
```

## 与主系统的关系

- **兼容独立**：保留独立数据库、手动 Actions 和 HTML 报告
- **共享能力**：复用统一 Adapter/ContentItem、核心 `TranslationService` 与 `utils/logging`
- **可独立开关**：`ai_frontier.enabled: false` 即可关闭，不影响主系统

## 测试

```bash
python -m pytest tests/ai_frontier -v
```
