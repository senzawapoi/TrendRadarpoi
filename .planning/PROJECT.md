# TrendRadarpoi Personal Intelligence Assistant

## What This Is

TrendRadarpoi 是面向个人长期使用的信息采集、分析、研究与对话助手。它在保留现有热点、RSS、AI Frontier、SQLite、报告和通知能力的基础上，把多来源内容统一成可去重、可聚类、可排序的情报对象，并通过飞书提供每日情报和历史问答。

当前 v5.0 按文档规划为 Phase 0-8：基线稳定、统一数据层、Story Intelligence、安全情报、Gemini、飞书、Agent-Reach、VPS 部署和测试。每个阶段都必须保持项目可运行，并通过增量接口逐步迁移现有实现。

Phase 0-6 已实现并完成离线验证：现有热点、RSS 和 AI Frontier 默认通过 Adapter 生成统一 ContentItem、保留 observation 并写入本地 intelligence.db；Cluster、Story、Importance、安全情报、统一 Gemini、有界本地 Assistant 和受控 ResearchGateway 形成增量情报视图。Phase 5 增加默认关闭的飞书官方 SDK 长连接、身份白名单、单聊/群聊 @、文本/图片输入、持久化事件恢复和上海时区日报。Phase 7 当前执行 07-05：ENV-03 已修复，H1-A..D 的 22 项 Linux 聚焦验证通过；补齐 Windows tzdata，并修复系统校时导致控制器短租约误拒绝的问题，相关租约、回滚和真实 systemd 验证 118 项通过。冻结 v6 的隔离 Windows 全量为 683 passed、342 skipped、2 warnings，Linux 全量为 1019 passed、6 skipped、2 warnings；独立 dirty 空 venv 安装通过，均 exit 0。301 个输入及归档对应成员匹配，28 项矩阵为 27 PASS、1 BLOCKED（RG-04 干净候选）。G1 通过；G2 被干净候选阻断，G3 待现场证据。干净候选、真实 GitHub 执行与 VPS 验收仍开放，旧失败证据保留。接续顺序以 `docs/phase7-actual-gap-evidence/HANDOFF.md` 为准。旧报告、通知、MCP 和数据库兼容保持；Windows Lark/Gemini 真实用例与剩余现场缺口分别记录在 Phase 5 验收文档中。

## Core Value

把多个来源关于同一事件的内容聚合成可解释、可排序、可追问的 Story，并通过飞书持续交付真正重要的个人情报。

## Requirements

### Validated

- ✓ 系统可以采集多个热点平台并生成排名和关键词统计 — existing
- ✓ 系统可以采集 RSS/Atom/JSON Feed 并按发布时间过滤 — existing
- ✓ AI Frontier 可以并发采集 ArXiv、Reddit、Hacker News、GitHub、X、Podcast 和官方博客 — existing
- ✓ 系统可以使用 Gemini 翻译英文标题，并在不可用时降级为原文 — existing
- ✓ 系统可以用 SQLite 保存热点、RSS 和 AI Frontier 历史并检测新增内容 — existing
- ✓ 系统可以生成 HTML 报告，并通过 Bark、飞书 webhook 等渠道发送通知 — existing
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

- [ ] 配置飞书/Gemini 环境凭据和租户权限，验收实际长连接问答、图片及每日 Story 推送
- [ ] 在 VPS 上以可维护的服务运行 Feishu Bot、Assistant Worker、Scheduler、SQLite 和 Agent-Reach
- [ ] 保持现有 CLI、配置、SQLite 历史、AI Frontier 和通知渠道兼容，迁移期间可回滚
- [ ] 为统一模型、迁移、Story、Gemini、飞书、Agent-Reach 和部署链路建立单元及集成验证

### Out of Scope

- 任意 shell 执行 — 飞书助手和未来 ResearchGateway 都不得向模型或用户暴露通用命令执行
- PostgreSQL、Vector DB、Kubernetes — 个人低维护场景继续使用 SQLite
- 语义向量检索 — 当前先使用 SQLite 可验证检索；达到明确需求后再评估 Vector Storage
- 多租户、公开注册和团队权限系统 — 当前只服务个人白名单账号
- 新日报同时推送 Bark 或其他渠道 — 保留旧渠道兼容，但新的个人 Story 日报只推送飞书

## Context

- 现有代码是兼容优先的 Python brownfield 项目，包含主抓取、AI Frontier、MCP 和默认关闭的飞书 Assistant 四个运行面。
- 主抓取使用 `NewsItem`/`RSSItem`，AI Frontier 使用 `AIItem`；三套入口存在重复的抓取、标准化、存储、分析和通知职责。
- SQLite 是当前持久化基础：热点和 RSS 按日期分库，AI Frontier 使用独立数据库；统一模型通过本地 `intelligence.db` 和兼容投影并行运行，后续阶段仍须保持旧数据可读。
- 2026-10-13 的历史全量自动测试为 531 项通过，另有 1 个上游 OpenTelemetry 弃用警告；不能用于验收随后修改的当前工作区。当前 07-05 聚焦检查及待办见 `docs/phase7-actual-gap-evidence/HANDOFF.md`。Phase 0-6 已覆盖入口、旧 SQLite 兼容、统一数据与 Story、安全情报、Gemini/Assistant、飞书官方 SDK 边界、白名单、媒体、事件/日报幂等、有界重连和 ResearchGateway 无 shell 边界。实际外部服务联调和 Linux VPS 运行不包含在离线验证结论中。
- 全仓 Ruff 仍有既有问题；以变更路径检查作为增量门禁，不应在功能阶段混入无边界的全仓格式化。
- 目标 VPS 为 1 核 CPU、约 1.87 GB RAM；长期服务必须限制并发、上下文大小、数据库事务和外部请求资源。
- Agent-Reach（`https://github.com/Panniantong/Agent-Reach`）是安装、体检和路由上游 CLI/MCP 的能力层，不是统一 Python API。Phase 6 必须通过 ResearchGateway 包装明确能力，不能透传其 shell 使用方式。

## Constraints

- **Compatibility**: 保持 `python -m trendradar`、AI Frontier、现有配置、SQLite 历史数据和通知能力可用 — 个人生产任务不能因重构中断
- **Storage**: v1 继续使用 SQLite，并采用版本化迁移、备份和兼容读取 — 低维护优先
- **Identity**: 飞书消息默认拒绝，只有配置在 `allowed_users` 中的个人身份可以使用助手 — 防止未授权调用和费用消耗
- **Transport**: 飞书采用 SDK WebSocket 长连接 — 适配 VPS 且不要求暴露公网回调端口
- **Notification**: 新个人日报只发送飞书，时区默认 `Asia/Shanghai`，发送时间可配置 — 避免重复通知并保留个人控制
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
| 保持现有入口、配置、SQLite 和通知兼容 | 避免个人生产任务中断并支持渐进迁移 | — Pending |
| 飞书使用 WebSocket 长连接和 deny-by-default 白名单 | 减少公网暴露并限制为个人使用 | ✓ Validated offline in Phase 5 |
| 新个人日报只发送飞书，默认时区 Asia/Shanghai | 建立单一主要交互入口并避免重复推送 | ✓ Validated offline in Phase 5 |
| Phase 6 通过 ResearchGateway 接入 Agent-Reach | 保持研究层独立于 crawler，并隔离权限和故障 | — Offline verified |
| Phase 7 使用 systemd 管理 VPS 运行服务 | 适配个人服务器的低维护部署方式 | — 07-05 actual-gap remediation in progress; VPS acceptance pending |
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
*Last updated: 2026-10-14 after actual-gap workspace reconciliation*
