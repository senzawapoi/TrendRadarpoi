# Phase 1-6 Fix Audit

审计日期：2026-10-12（Asia/Shanghai）。这份记录对应
`TrendRadarpoi-Phase1-6-修复计划.md`，不把离线测试写成真实租户、provider 或 VPS 验收。

## 状态矩阵

| ID | 当前状态 | 已补齐/已验证 | 仍需真实验收 |
| --- | --- | --- | --- |
| R1 | 离线验证通过 | 入站先落库；启动恢复；运行中 SQLite 轮询；容量上限；租约 fencing；无效恢复载荷终止 | Linux 服务退出/崩溃后真实 Lark 重复投递抑制与资源观察 |
| R2 | 离线验证通过 | 回复先保存；失败退避；重启和运行中自动重试；不重复 Gemini；发送异常可控 | Lark 发送超时后的未知结果窗口及真实平台幂等行为 |
| R3 | 离线验证通过 | HTTP 子进程硬截止、分块读取、响应上限和子进程回收 | 目标 VPS 上真实 Jina/网络中断；HTTP 研究仍建议先保持关闭 |
| R4 | 离线验证通过 | 仅 `INTELLIGENCE_RESEARCH_GITHUB_TOKEN` 注入 GitHub；临时 `GH_CONFIG_DIR`；无宿主 gh 配置继承 | `gh` 版本、公共仓库查询、认证/限流错误的真实验证 |
| R5 | 离线验证通过 | 结构化 JSON、MCP `content[].text`、嵌套 JSON、错误 envelope 和空结果分流 | 已安装 `mcporter` 的真实 Exa/Reddit 输出契约 |
| R6 | 离线验证通过 | `requirements.txt` 与 `pyproject.toml` 补齐并统一约束；固定已验证的 Pydantic 组合 | Linux VPS 的实际安装路径和外部工具版本 |

R1/R2 复用现有 `feishu_events` 作为兼容的 durable inbox/outbox 等价结构，未另建表；
`status`、`lease_until`、`delivery_attempts` 和 `reply_json` 共同表达处理、退避、送达和终止状态。

## 可发布范围

本轮补漏新增了持久载荷版本与事件 ID 校验、布尔字段严格校验、耗尽任务过滤及正文清理、
出站租约续期、失败交付的恢复目标保存、启动恢复排序和 worker 异常上报。
回归测试见 `tests/integrations/feishu/test_repair_recovery.py`，均使用临时 SQLite。

当前代码可以继续进行 Phase 7 的离线部署准备。Lark 基础服务的实现具备持久恢复和发送重试路径，但在真实 Linux 单实例运行、备份恢复、异常退出和资源观察完成前，不应写成已生产验收。外部研究保持默认关闭；没有完成对应工具和 provider 的真实验收，不要一次性打开 `search_web`、`search_github`、`search_reddit`、网页读取或视频字幕能力。

## 数据库与回滚

`intelligence.db` 当前 schema 为 v6。v6 是向前迁移，旧程序不能被假设可以打开新版本数据库；回滚应停止写入并使用经过 SQLite 一致性备份验证的旧副本，不得手改 `PRAGMA user_version`。旧 `news`、RSS 和 AI Frontier 数据库未迁移破坏。无法从旧 `completed` 记录判断发送是否成功时，不自动批量重发。

## 仍存在的边界

用户已确认采用修复计划语义：同一 `event_id` 的回复成功送达后，后续重复事件不再调用 Lark 发送，也不重新调用 Gemini。账本仍保留 `completed` 和持久化回复用于审计；`claim()` 只返回瞬时的 `duplicate_delivered` 抑制状态，不改变 schema。

发送请求已经到达平台但本地在提交成功状态前崩溃时，记录仍可能停留在带回复的 `failed` 状态并触发一次保存回复重试；Lark SDK/平台幂等窗口无法确认时，不能宣称外部 exactly-once。媒体引用过期时只能走现有媒体降级，不保证重启后图片仍可下载。

验证基线：`500 passed, 1 warning` 全量 pytest；Lark/Research/基线聚焦测试 `158 passed, 1 warning`；目标 Ruff 和 `git diff --check` 通过。requirements 安装环境与当前项目 wheel 安装环境均通过 `pip check`，并完成 bs4、Google GenAI、FastMCP、MCP、主入口、AI Frontier 和 Lark 入口导入检查。警告为现有 OpenTelemetry/Authlib 弃用提示，不是本轮失败。
