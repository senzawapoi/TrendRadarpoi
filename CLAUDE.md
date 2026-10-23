# TrendRadar 项目指南

## 项目定位

TrendRadarpoi 是兼容优先的个人情报项目，提供主抓取、AI Frontier、FastMCP 和默认关闭的 Lark Assistant 四个运行面。统一 `ContentItem`、Story、Security、Gemini 与 Assistant 使用版本化的 `intelligence.db`；旧 SQLite、报告与 MCP 保持兼容；通知仅保留 Lark。

## 关键结构

| 路径 | 职责 |
|------|------|
| `trendradar/core/` | settings、分析与统一模型 |
| `trendradar/crawler/` | 既有 NewsNow、RSS 抓取实现 |
| `trendradar/sources/` | NewsNow、RSS、AI Frontier 的统一 Adapter |
| `trendradar/intelligence/` | Adapter、去重、Story、统一 SQLite、投影与回填 |
| `trendradar/ai/` | 核心 Gemini、翻译/分析、Assistant、Session、检索与静态工具 |
| `trendradar/integrations/lark/`, `feishu/` | Lark 国际入口与内部兼容实现：SDK、身份校验、媒体、事件去重、失败投递重试与 Story 即时投递 |
| `trendradar/domains/security/` | CISA/NVD/RSS 安全采集、分析与报告 |
| `trendradar/storage/` | 旧 news/RSS 本地与 S3 存储 |
| `trendradar/ai_frontier/` | 七类 AI 来源、独立 SQLite 与报告 |
| `trendradar/report/` | 报告渲染；Lark 投递由 integrations 的 Scheduler 统一负责 |
| `mcp_server/` | FastMCP 服务与工具 |
| `tests/{ai,baseline,intelligence,ai_frontier,integrations}/` | 核心服务、兼容、情报、来源与飞书测试 |

## 运行与验证

```powershell
python -m pip install -r requirements.txt
python -m trendradar
python -m trendradar.ai_frontier
python -m mcp_server.server --transport stdio
python -m trendradar.integrations.lark --check
python -m pytest tests -q
python -m ruff check <changed-python-paths>
```

历史数据只通过显式命令回填：

```powershell
python -m trendradar.intelligence.backfill --from 2026-08-01 --to 2026-08-31 --dry-run
```

## 配置与数据

- `config/config.yaml`：平台、RSS feeds、AI Frontier、Lark、存储和统一情报层配置。
- `config/frequency_words.txt`：关键词规则。
- `.env.example`：无凭据的环境变量模板。
- 值优先级：非空环境变量 > YAML > 默认值；配置路径优先级：显式参数 > `CONFIG_PATH` > `config/config.yaml`。
- `INTELLIGENCE_ENABLED=false` 完整切回旧抓取路径；`INTELLIGENCE_DB_PATH` 默认 `output/intelligence.db`。
- `GEMINI_ENABLED=false` 保留确定性本地降级；`INTELLIGENCE_ASSISTANT_ENABLED=false` 仅关闭 Assistant。
- `LARK_ENABLED=false` 关闭国际版运行器；凭据 `LARK_APP_ID`、`LARK_APP_SECRET` 只从环境读取，兼容旧 `FEISHU_*` 别名。`--check` 不联网、不打开数据库，不代表租户权限已验证。
- 统一库不可用或写入失败时必须复用已抓取数据继续旧链路，禁止自动重抓上游。
- `output/news/`、`output/rss/`、`output/ai_frontier.db` 与 `output/intelligence.db` 都是运行状态，不得当作普通缓存删除。

## 工程约束

1. 架构改动前阅读 `.planning/PROJECT.md`、相关 `.planning/codebase/` 和 `docs/intelligence.md`。
2. 保留未提交的用户改动；未经明确要求不得 reset、commit、push 或 deploy。
3. 保持 `NewsItem`、`RSSItem`、`AIItem`、三套旧 schema 和现有入口兼容。
4. 网络获取与解析/Normalize 分离；单源或统一库失败不得中断其他来源及旧输出。
5. Python 3.10+、四空格、类型标注、100 列；Ruff 只检查本次变更的 Python 路径。
6. 密钥、Token、Cookie、webhook、`.env` 和数据库不得提交；Gemini 凭据只读环境变量，禁止恢复任何旧默认 key。
7. 飞书和 MCP 只能向内调用核心服务；身份授权必须先于内容解析、媒体下载和 Assistant。保留有界队列、重连冷却；已送达的重复 `event_id` 不再发送，失败投递只重试已保存回复，不声称外部投递严格 exactly-once。
8. Windows UAT 与 Linux VPS 部署分开；真实测试期间保留 `test/runtime/` 的库、WAL/SHM、图片与日志。核实实例描述文件与进程，不启动第二个 bot，不执行 `-Reset`。
9. Phase 7 安装只走固定受控入口与可信 `common.env`；不删事务记录绕过维护保护。保留 `PrivateTmp`，服务解释器不得放在 `/tmp` 或 `/var/tmp`；未完成复现时保留旧审计包和隔离 Linux 工具链。

## 当前部署约定

- 执行 [07-06 计划](.planning/phases/07-deployment/07-06-PLAN.md)，新 PR 不自动合并。
- Gemini 共用一个环境密钥，默认按 3.8 Flash、3.5 Flash Lite、3.1 Flash Lite 顺序切换；翻译独立使用 Gemini 3.1 Flash Lite，失败保留原文，不回退 Gemma。
- 正式配置使用 Lark 即时模式，Scheduler 每 60 秒检查；不增加上游采集频率。
- 即时推送采用来源分组、编号及可点击标题的紧凑富文本；消息分片整体保存，旧版文本快照仍按原内容重试。
- VPS 使用 Python 3.12 独立虚拟环境，共享资源上限 512M/768M/50% CPU。
- 本轮只做每小时本机备份，保留 24 小时、7 日、4 周；异地备份与 48 小时连续观察分别验收。

## 深入文档

- [文档导航](docs/README.md)：运行契约、Lark 配置、数据库表与验收证据。
- [本地测试沙箱](test/README.md)：入口、诊断、单实例核对及清理规则。
- [Phase 7 缺口交接](docs/phase7-actual-gap-evidence/HANDOFF.md)：已执行检查、失败用例和接续顺序。
- [.planning/STATE.md](.planning/STATE.md)：当前进度与待办；原始需求和 `conductor/` 历史快照不代表已交付状态。
