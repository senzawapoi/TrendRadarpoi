# TrendRadarpoi

个人情报助手：聚合热点、RSS、AI 与安全资讯，将来源证据归并为 Story，保留本地历史与 HTML 报告，通过 Lark 接收新增情报并进行文本、图片问答。

[English](README-EN.md) · [文档导航](docs/README.md) · [仓库交接](docs/repository-handoff-20261023.md) · [部署手册](docs/deployment.md)

[配置与关键词规则](docs/configuration.md) · [MCP 客户端配置](docs/mcp-setup.md)（均为中英对照）

## 数据与运行入口

`SourceAdapter -> ContentItem -> Deduplicate -> Story -> Lark`

统一数据存放在 `output/intelligence.db`；兼容数据库 `output/news/`、`output/rss/`、`output/ai_frontier.db` 继续供报告与 MCP 使用。启动不自动导入历史数据，正式部署使用新库，不复制 Windows UAT 数据。

```bash
python -m pip install -r requirements.lock
python -m trendradar
python -m trendradar.ai_frontier
python -m mcp_server.server --transport stdio
python -m trendradar.integrations.lark --check
```

支持 Python 3.10+；Linux VPS 使用 Python 3.12 独立虚拟环境。采集与报告可以独立运行，Lark 默认关闭。生产数据库必须显式迁移，具体步骤见部署手册。

## 模型与翻译

仅使用环境变量 `GEMINI_API_KEY`。推理默认顺序为：

1. `gemini-3.8-flash`
2. `gemini-3.5-flash-lite`
3. `gemini-3.1-flash-lite`

`GEMINI_MODELS` 接受逗号分隔列表，优先于旧 `GEMINI_MODEL` 和 YAML 配置。每个候选每次请求最多尝试一次，总计最多三次；模型错误触发即时切换与默认 60 秒冷却。全部不可用时返回确定性本地证据。共享鉴权错误不会轮换模型。

翻译使用独立的 `gemini-3.1-flash-lite` 客户端，共用 API key；不继承推理模型列表，也不调用匿名翻译服务。失败直接保留原文，不回退 Gemma。

主采集和 AI Frontier 在发布 Story 前完成规范标题翻译并保存结果，报告复用同一译文；原始来源证据与已保存的投递内容保持不变。详见[翻译与发布契约](docs/intelligence.md#title-translation-before-publication)。

## Lark

凭据和授权身份使用 [.env.example](.env.example) 中的 `LARK_*`，不得写入 YAML 或 Git。支持授权单聊、群聊 @、图片与图文；已送达的重复事件不会再次回复。

正式配置选择 `LARK_DELIVERY_MODE=instant`，不启用定时日报。Scheduler 每 60 秒检查新 Story，每批最多 20 条，剩余条目留在持久化队列。更新、重复采集与重启不重新推送已登记 Story；失败重试复用保存内容与分片进度。采集器自身不发送通知，维护期间停止投递。

即时消息使用紧凑富文本：显示本批新增数量、来源分组和编号标题，点击标题打开原文。每条 Story 展示一个来源入口；详细摘要、评分和其他证据保留在报告中。长消息按完整条目分片，已保存的旧版文本消息仍按原内容重试。

## 部署与备份

使用 `deploy/` 下的 systemd 服务和固定安装入口，保留 `PrivateTmp`、`ProtectHome`、维护 guard 与事务日志。初始共享预算为 512M 内存软限、768M 硬限、50% CPU；主采集与 AI Frontier 串行执行。

每小时生成 SQLite 一致性快照，覆盖统一库、AI Frontier 与 news/RSS 日期库，保留 24 小时、7 日和 4 周快照。当前部署选择 `TRENDRADAR_OFFSITE_ENABLED=false`；本机备份不构成异地备份验收。GitHub 采集工作流仅手动运行，生产采集由 VPS timers 承担。

## 验证与状态

```bash
python -m pytest tests -q
python -m ruff check <changed-python-paths>
python -m trendradar.ops health --readiness --json
```

当前计划见 [07-06-PLAN.md](.planning/phases/07-deployment/07-06-PLAN.md)。GitHub run `39921046202` 已部署 `p7-20261023-28e7283`，用户曾确认中文标题和链接收件；之后 10-23 19:41 的雅虎财经等未翻译报告仍待诊断。交接分支的来源健康与部署保护修改已通过 WSL 全量回归，用户已批准分组提交及叠加 PR，尚未部署；来源稳定性、至少 48 小时观察及异地备份/恢复仍未验收。查看[Phase 7 交接](docs/phase7-release-20261023/HANDOFF.md)和[仓库交接](docs/repository-handoff-20261023.md)。

## 来源与许可证

本项目基于 [sansan0/TrendRadar](https://github.com/sansan0/TrendRadar)，按 [GPL-3.0](LICENSE) 分发。AI Frontier 的部分默认 Podcast、Blog 和 X 信息源参考 [follow-builders](https://github.com/zarazhangrui/follow-builders)。
