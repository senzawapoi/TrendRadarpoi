# TrendRadarpoi Personal Intelligence Assistant

## What This Is

TrendRadarpoi 是面向个人长期使用的信息采集、分析、研究与对话助手。它在保留现有热点、RSS、AI Frontier、SQLite、报告和通知能力的基础上，把多来源内容统一成可去重、可聚类、可排序的情报对象，并通过飞书提供每日情报和历史问答。

当前 v5.0 按文档规划为 Phase 0-8：基线稳定、统一数据层、Story Intelligence、安全情报、Gemini、飞书、Agent-Reach、VPS 部署和测试。每个阶段都必须保持项目可运行，并通过增量接口逐步迁移现有实现。

Phase 0-6 已实现并完成离线验证：统一 ContentItem、Story、Importance、安全情报、Gemini、Assistant 和受控 ResearchGateway 已接入。Phase 5 提供默认关闭的 SDK 长连接、身份白名单、单聊/群聊 @、文本/图片和持久化恢复。Phase 7 当前执行 07-06：记录中的 VPS 版本为 `p7-20261023-8fc8f82`，通过已批准的 GitHub 发布流程部署；后续标题翻译与 Story 发布顺序修复仍在本地，尚未提交或部署。本地 Windows/Linux 全量验证和 Python 3.12 归档安装已通过；修复发布、中文标题 Lark 验收、来源健康及 48 小时观察仍开放。仅启用本机备份，异地恢复不计为通过。接续以[当前交接](../docs/phase7-release-20261023/HANDOFF.md)为准，保留历史验收和失败现场。旧采集、报告、MCP 和数据库保持兼容；按用户新决策，通知仅保留 Lark。

## Core Value

把多个来源关于同一事件的内容聚合成可解释、可排序、可追问的 Story，并通过飞书持续交付真正重要的个人情报。

## Requirements

### Validated

- ✓ 系统可以采集多个热点平台并生成排名和关键词统计 — existing
- ✓ 系统可以采集 RSS/Atom/JSON Feed 并按发布时间过滤 — existing
- ✓ AI Frontier 可以并发采集 ArXiv、Reddit、Hacker News、GitHub、X、Podcast 和官方博客 — existing
- ✓ 系统可以使用 Gemini 翻译英文标题，并在不可用时降级为原文 — existing
- ✓ 系统可以用 SQLite 保存热点、RSS 和 AI Frontier 历史并检测新增内容 — existing
- ✓ 系统可以生成 HTML 报告；早期多渠道通知已由 Phase 7 的 Lark SDK 统一投递取代 — existing / Phase 7
- ✓ MCP 可以查询和分析历史新闻，并触发受限的现有抓取能力 — existing
- ✓ GitHub Actions 和 Docker 可以运行现有批处理抓取任务 — existing
- ✓ 架构、入口与 SQLite 兼容基线已固定，三个运行面共享安全的 settings 边界 — Phase 0
- ✓ 热点、RSS 和 AI Frontier 可无损转换为 UTC-aware `ContentItem` 并保留来源 observation — Phase 1
- ✓ Source Adapter、Normalize、Deduplicate 和本地 `intelligence.db` 已默认启用且可一键回滚 — Phase 1
- ✓ 同一真实事件的多个 `ContentItem` 已聚合为稳定、可增量更新的 `Story` — Phase 2
- ✓ Story 已完成 Ranking、Importance 评估并保留可解释依据 — Phase 2
- ✓ CISA KEV、NVD 和安全 RSS 已纳入统一流水线并生成可行动、可解释的 Security Story — Phase 3
- ✓ 安全报告已提供 CVE、CVSS、KEV、行动证据和来源新鲜度，并保持独立故障降级 — Phase 3
- ✓ 独立于 MCP 的统一 `GeminiClient` 已供翻译、Story、日报、安全分析和 Chat 复用 — Phase 4
- ✓ SQLite Assistant Session、本地情报检索、不可伪造引用和静态受控工具已完成 — Phase 4
- ✓ 飞书官方 SDK 薄适配层、白名单、文本/图片、事件重放、冷却和日报已完成离线验证 — Phase 5
- ✓ ResearchGateway 已通过受控能力白名单接入 Agent-Reach，并完成超时、权限、结果上限和无 shell 边界的离线验证 — Phase 6

### Active

- [ ] 完成中文标题即时 Story 的真实收件验收，保留已记录的文本、图片问答证据
- [ ] 完成 VPS 服务的来源健康与连续观察验收；Agent-Reach 仍按需启用
- [ ] 保持现有 CLI、SQLite 历史和 AI Frontier 兼容；Lark 为唯一通知渠道，迁移可回滚
- [ ] 为统一模型、迁移、Story、Gemini、飞书、Agent-Reach 和部署链路建立单元及集成验证

### Out of Scope

- 任意 shell 执行 — 飞书助手和未来 ResearchGateway 都不得向模型或用户暴露通用命令执行
- PostgreSQL、Vector DB、Kubernetes — 个人低维护场景继续使用 SQLite
- 语义向量检索 — 当前先使用 SQLite 可验证检索；达到明确需求后再评估 Vector Storage
- 多租户、公开注册和团队权限系统 — 当前只服务个人白名单账号
- Bark、旧 webhook 及其他通知渠道 — 用户在 Phase 7 明确要求删除，统一由 Lark SDK 投递

## Context

- 现有代码是兼容优先的 Python brownfield 项目，包含主抓取、AI Frontier、MCP 和默认关闭的飞书 Assistant 四个运行面。
- 主抓取使用 `NewsItem`/`RSSItem`，AI Frontier 使用 `AIItem`；三套入口存在重复的抓取、标准化、存储、分析和通知职责。
- SQLite 是当前持久化基础：热点和 RSS 按日期分库，AI Frontier 使用独立数据库；统一模型通过本地 `intelligence.db` 和兼容投影并行运行，后续阶段仍须保持旧数据可读。
- Phase 0-6 已覆盖入口、旧 SQLite 兼容、统一数据与 Story、安全情报、Gemini/Assistant、白名单、媒体、事件幂等、有界重连和 ResearchGateway 无 shell 边界。当前修复测试及失败项见[交接](../docs/phase7-release-20261023/HANDOFF.md)，历史测试数字不用于验收后续修改；离线验证与实际外部联调分开记录。
- 全仓 Ruff 仍有既有问题；以变更路径检查作为增量门禁，不应在功能阶段混入无边界的全仓格式化。
- 目标 VPS 为 1 核 CPU、约 1.87 GB RAM；长期服务必须限制并发、上下文大小、数据库事务和外部请求资源。
- Agent-Reach（`https://github.com/Panniantong/Agent-Reach`）是安装、体检和路由上游 CLI/MCP 的能力层，不是统一 Python API。Phase 6 必须通过 ResearchGateway 包装明确能力，不能透传其 shell 使用方式。

## Constraints

- **Compatibility**: 保持 `python -m trendradar`、AI Frontier、现有配置、SQLite 历史数据和通知能力可用 — 个人生产任务不能因重构中断
- **Storage**: v1 继续使用 SQLite，并采用版本化迁移、备份和兼容读取 — 低维护优先
- **Identity**: 飞书消息默认拒绝，只有配置在 `allowed_users` 中的个人身份可以使用助手 — 防止未授权调用和费用消耗
- **Transport**: 飞书采用 SDK WebSocket 长连接 — 适配 VPS 且不要求暴露公网回调端口
- **Notification**: Lark 为唯一渠道，正式配置每 60 秒检查新增 Story，时区 `Asia/Shanghai`；不增加采集频率，不同时运行日报发送器
- **AI boundary**: Gemini 是核心应用服务，MCP 只能依赖核心服务，核心服务不得依赖 MCP — 保证内部运行不绑定外部接口
- **Secrets**: 活跃 API Key、Token 和 Cookie 只能来自 `.env`、GitHub Secrets 或 VPS Secret — 不进入 Git、日志或报告
- **Research safety**: Agent-Reach 只通过 ResearchGateway 开放命名白名单能力、参数校验、超时和结果上限 — 禁止通用 shell
- **Operations**: GitHub Actions 负责 CI、测试、备份和发布；VPS 承载飞书、Assistant、Scheduler、SQLite 和 Agent-Reach — 符合文档部署边界

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| v5.0 按 Phase 0-8 执行 | 完整遵循三份 Codex v5 文档的工程分解 | — Pending |
| Phase 0 独立完成架构审计和配置统一 | 在功能迁移前建立可验证基线和一致配置方式 | ✓ Validated in Phase 0 |
| Phase 1 交付 ContentItem、Adapter、Normalize、Deduplicate | 先建立所有后续能力共享的稳定输入边界 | ✓ Validated in Phase 1 |
| Phase 2 交付 Cluster、Story、Ranking、Importance | Story 是从新闻推送器升级为情报助手的核心，不延期 | ✓ Validated in Phase 2 |
| Phase 3 交付安全采集、Security Story、可行动排序和新鲜度报告 | 复用统一数据和 Story 合约，同时隔离高波动外部来源 | ✓ Validated in Phase 3 |
| Phase 4 交付统一 Gemini 服务和有界本地 Assistant | 复用同一推理边界，限制 Session、引用、工具和故障影响范围 | ✓ Validated in Phase 4 |
| 保持现有入口和 SQLite 兼容，通知统一为 Lark | 用户在 Phase 7 明确删除旧通知实现 | — Implemented; live localized delivery open |
| 飞书使用 WebSocket 长连接和 deny-by-default 白名单 | 减少公网暴露并限制为个人使用 | ✓ Validated offline in Phase 5 |
| Lark 即时推送新增 Story，默认时区 Asia/Shanghai | Phase 7 取代正式定时日报，已登记 Story 不重推 | — Recorded deployed; translation repair local |
| Phase 6 通过 ResearchGateway 接入 Agent-Reach | 保持研究层独立于 crawler，并隔离权限和故障 | — Offline verified |
| Phase 7 使用 systemd 管理 VPS 运行服务 | 适配个人服务器的低维护部署方式 | — 07-06 recorded deployed; acceptance incomplete |
| Phase 8 完成跨模块单元和集成测试 | 验证飞书到 Gemini 的完整主链路 | — Pending |
| v1 不引入 PostgreSQL、Vector DB 或 Kubernetes | 当前规模下维护成本大于收益 | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-10-23 after workspace reconciliation; live state not rechecked during cleanup*
