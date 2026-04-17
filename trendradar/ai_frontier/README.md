# AI Frontier - AI 前沿资讯聚合

独立的 AI 前沿资讯聚合子系统，并行抓取全球 AI 相关的最新动态，自动翻译并推送到 Bark。

## 数据源

| 源 | 说明 | API |
|---|---|---|
| 📄 **ArXiv** | cs.AI / cs.LG / cs.CL 最新论文 | ArXiv Atom（免 Key）|
| 🔥 **Reddit** | r/MachineLearning / r/LocalLLaMA / r/singularity / r/OpenAI | Reddit .json（免 Key）|
| 🗞️ **HackerNews** | AI/LLM/GPT/Claude/Gemini 高分帖子 | HN Algolia Search |
| ⭐ **GitHub Trending** | 每日趋势（Python + AI 关键词筛选 All 榜）| HTML 解析 |
| 🐦 **X / Twitter** | OpenAI / Anthropic / Karpathy / Sama 等关键账号 | Nitter RSS 镜像 |

## 快速开始

### 本地运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. （可选）设置翻译与推送密钥
export GEMINI_API_KEY="your_gemini_key"
export BARK_URL="https://api.day.app/your_device_key/"

# 3. 运行
python -m trendradar.ai_frontier
```

执行后将会：
1. 并发抓取 5 个源的最新内容
2. 按 `(source, url)` 去重，过滤 24h 外的旧条目
3. 写入 `output/ai_frontier.db`（SQLite，独立于主系统）
4. 按分数阈值过滤 + 翻译英文标题为中文
5. 保存 HTML 报告到 `output/ai_frontier/YYYY-MM-DD/HH-MM.html`
6. 推送 markdown 摘要到 Bark

### GitHub Actions 自动运行

`.github/workflows/ai-frontier.yml` 已配置每 2 小时触发一次。

**无需额外配置 Secrets**：直接复用主仓库已有的 `GEMINI_API_KEY` 与 `BARK_URL`（与 `crawler.yml` 共用同名 secret）。

Bark URL 解析优先级：
1. `secrets.BARK_URL`（Actions 环境变量）
2. `config.yaml` 的 `ai_frontier.push.bark_url`（独立专用，可选）
3. `config.yaml` 的 `notification.channels.bark.url`（回退到主系统已配置的 Bark）

## 配置

见 `config/config.yaml` 的 `ai_frontier` 节点，可自定义：
- 数据源启用/禁用
- ArXiv 分类、Reddit 子版块、HN 关键词、X 账号列表
- 分数阈值（HN points / Reddit upvotes / GitHub stars）
- 单次推送最大条数
- Nitter 实例列表（镜像失效时自动回退）

## 架构

```
trendradar/ai_frontier/
├── __main__.py          # 入口：python -m trendradar.ai_frontier
├── sources/             # 5 个数据源适配器
│   ├── base.py          # AIItem/AISource 基类
│   ├── arxiv.py
│   ├── reddit.py
│   ├── hackernews.py
│   ├── github_trending.py
│   └── nitter.py
├── fetcher.py           # 并发聚合 + 去重 + 新鲜度过滤
├── storage.py           # 独立 SQLite: output/ai_frontier.db
├── detector.py          # 分数过滤 + 分组
├── translator.py        # 批量翻译（复用 TranslationService.batch_translate_titles）
├── renderer.py          # markdown + HTML 渲染
└── pusher.py            # 独立 Bark 推送器
```

## 与主系统的关系

- **完全解耦**：独立数据库、独立 Actions、独立推送链路
- **共享能力**：复用 `TranslationService` 批量翻译、`utils/logging`
- **可独立开关**：`ai_frontier.enabled: false` 即可关闭，不影响主系统

## 测试

```bash
python -m pytest tests/ai_frontier -v
```
