# Roadmap: TrendRadarpoi v5.0

## Overview

TrendRadarpoi v5.0 采用增量式 brownfield 升级：先固定当前运行基线和配置边界，再把所有来源统一为 `ContentItem`，构建以 Story 为核心的聚类和重要性排序，随后接入安全情报、Gemini Assistant、飞书、Agent-Reach、VPS 运行体系，最后完成全链路测试和发布验证。每个阶段都必须保持现有抓取、SQLite 数据和通知能力可用。

## Phases

- [x] **Phase 0: Project Baseline Stabilization** - 固定架构、运行和配置基线 (completed 2026-08-21)
- [x] **Phase 1: Unified Intelligence Data Layer** - 统一 ContentItem、Adapter、Normalize 和 Deduplicate (completed 2026-08-21)
- [x] **Phase 2: Story Intelligence** - 将多来源内容转化为可排序、可解释的 Story (completed 2026-09-04)
- [x] **Phase 3: Security Intelligence Domain** - 把漏洞和安全事件纳入统一情报流水线 (completed 2026-09-04)
- [x] **Phase 4: Gemini Intelligence Layer** - 建立统一 Gemini 服务和本地情报 Assistant (completed 2026-09-04)
- [x] **Phase 5: Feishu Assistant** - 提供个人白名单长连接交互和日报入口 (completed offline 2026-09-12)
- [x] **Phase 6: Agent-Reach Integration** - 通过受控 ResearchGateway 增加外部研究能力 (completed offline 2026-10-11)
- [ ] **Phase 7: Deployment** - 建立 VPS、systemd、CI、备份和维护流程 (07-05 actual-gap remediation in progress; VPS pending)
- [ ] **Phase 8: Testing** - 完成单元、集成、兼容和发布级验证

## Phase Details

### Phase 0: Project Baseline Stabilization

**Goal**: 在不改变现有行为的前提下建立架构审计、运行验证和统一配置基础
**Depends on**: Nothing
**Requirements**: BASE-01, BASE-02, CONF-01, CONF-02, CONF-03
**Success Criteria**:

  1. 维护者可以从 `docs/code-review.md` 定位模块依赖、高耦合区域和渐进重构边界。
  2. 同一套 settings 字段可用于本地、GitHub Actions 和 VPS，仓库只包含无真实凭据的示例。
  3. 主抓取、AI Frontier 和 MCP 的基线启动、测试及数据兼容行为在整理后保持不变。

**Plans**: 2 plans

Plans:

- [x] 00-01: 固定架构审计、运行基线和兼容性特征测试
- [x] 00-02: 建立统一 settings 边界、`.env.example` 和配置优先级

### Phase 1: Unified Intelligence Data Layer

**Goal**: 让所有现有来源通过统一 Adapter 产生可标准化、可去重的 ContentItem
**Depends on**: Phase 0
**Requirements**: CONT-01, CONT-02, ADPT-01, ADPT-02, NORM-01, NORM-02, DEDU-01, DEDU-02, DEDU-03, COMP-01
**Success Criteria**:

  1. 现有热点、RSS、GitHub 和 AI Frontier 数据可以无损转换为 `ContentItem`。
  2. Normalize 和 Deduplicate 对相同输入产生稳定结果，同时保留同一事件的不同来源。
  3. 单个来源失败可通过健康状态发现，且不阻塞其他来源。
  4. 现有 CLI、YAML、SQLite 历史、日报和通知在迁移期间继续工作。

**Plans**: 4 plans

Plans:

- [x] 01-01: 定义 ContentItem、统一存储契约和兼容转换
- [x] 01-02: 定义 Source Adapter、Normalize 和健康检查接口
- [x] 01-03: 按文档顺序迁移现有新闻、RSS、GitHub 和其他来源
- [x] 01-04: 实现幂等 Deduplicate 和旧入口兼容回归

### Phase 2: Story Intelligence

**Goal**: 把相关 ContentItem 聚合为稳定 Story，并按可解释的重要性排序
**Depends on**: Phase 1
**Requirements**: CLUS-01, CLUS-02, STOR-01, STOR-02, STOR-03, STOR-04, RANK-01, RANK-02
**Success Criteria**:

  1. 同一事件的多来源内容显示为一个 Story，不相关事件不会被错误合并。
  2. Story ID 和成员关系在增量更新中保持稳定，用户可查看全部原始来源。
  3. 每个 Story 有 Importance 和可读排序原因，日报按 Story 而非文章组织。
  4. Gemini 不可用时仍可生成基础 Story 和排序结果。

**Plans**: 4 plans

Plans:

- [x] 02-01: 实现基于时间、标题、实体和标签的 Cluster Engine
- [x] 02-02: 建立 Story 模型、增量成员关系和 SQLite 持久化
- [x] 02-03: 实现 Gemini Story Generator 及确定性降级路径
- [x] 02-04: 实现 Ranking、Importance 和 Story 日报输出

### Phase 3: Security Intelligence Domain

**Goal**: 将 CVE、漏洞新闻和安全事件转化为可行动的 Security Story
**Depends on**: Phase 2
**Requirements**: SECU-01, SECU-02, SECU-03, SECU-04, SECU-05, SECU-06
**Success Criteria**:

  1. CISA KEV、NVD 和安全 RSS 通过统一 ContentItem 流水线处理。
  2. 同一漏洞的官方数据和新闻聚合为一个包含 CVE、严重性和 KEV 证据的 Story。
  3. 安全报告优先展示高严重性、已利用或需要行动的 Story，并标明来源新鲜度。

**Plans**: 3 plans

Plans:

- [x] 03-01: 建立 security collector、analyzer、report 领域模块和来源 Adapter
- [x] 03-02: 标准化 CVE/KEV 元数据并接入统一 Cluster/Story 流水线
- [x] 03-03: 实现安全分析、可行动排序、报告和来源故障降级

### Phase 4: Gemini Intelligence Layer

**Goal**: 将 Gemini 从翻译工具升级为统一推理服务和本地情报 Assistant
**Depends on**: Phase 3
**Requirements**: GEMI-01, GEMI-02, GEMI-03, GEMI-04, ASST-01, ASST-02, ASST-03, ASST-04
**Success Criteria**:

  1. Translation、Story、安全、日报和 Chat 通过同一个核心 `GeminiClient` 调用，核心不依赖 MCP。
  2. 用户可以自然语言查询本地 Story/ContentItem，并看到时间范围和来源证据。
  3. 多轮 Session 在 SQLite 中受限保存，登记工具之外的文件、shell 和能力不可调用。
  4. Gemini 故障不会中断采集、存储、确定性 Story 或旧通知。

**Plans**: 4 plans

Plans:
**Wave 1**

- [x] 04-01: 建立 GeminiClient、配置、重试、限流和结构化错误

**Wave 2**

- [x] 04-02: 迁移翻译、Story、日报和安全分析到统一服务边界

**Wave 3**

- [x] 04-03: 实现 Assistant、SQLite Session、本地检索和来源引用

**Wave 4**

- [x] 04-04: 实现工具登记、权限限制、上下文上限和降级验证

### Phase 5: Feishu Assistant

**Goal**: 通过飞书 WebSocket 为个人白名单用户提供对话和 Story 日报
**Depends on**: Phase 4
**Requirements**: FEIS-01, FEIS-02, FEIS-03, FEIS-04, FEIS-05, FEIS-06, FEIS-07
**Success Criteria**:

  1. 白名单用户可以通过飞书长连接发送消息并收到 Assistant/Gemini 回复。
  2. 未授权用户不会触发 Gemini 或工具，活动凭据不进入代码、日志或报告。
  3. 每日 Story 报告按配置时间和 `Asia/Shanghai` 时区只推送一次。
  4. 重复事件重放已保存回复而不重复生成；已确认日报窗口不重发，重连失败达到阈值后进入冷却。

**Plans**: 4 plans

Plans:

**Wave 1**

- [x] 05-01: 建立 Feishu client、handler、session 和秘密配置

**Wave 2** *(depends on Wave 1; complete)*

- [x] 05-02: 实现 SDK WebSocket 消息接收、路由和回复

**Wave 3** *(depends on Wave 2; complete)*

- [x] 05-03: 实现 allowed_users、Session 关联、幂等和有界重连

**Wave 4** *(depends on Wave 3; complete)*

- [x] 05-04: 实现每日 Story 推送、时区调度和重复发送保护

### Phase 6: Agent-Reach Integration

**Goal**: 通过最小权限 ResearchGateway 为 Assistant 增加可控外部研究能力
**Depends on**: Phase 5
**Requirements**: RSCH-01, RSCH-02, RSCH-03, RSCH-04, RSCH-05
**Success Criteria**:

  1. Assistant 只通过 ResearchGateway 调用 Agent-Reach，基础抓取和本地问答不依赖它。
  2. 文档规定的 research/search/fetch 能力可以返回受限、可审计的外部研究结果。
  3. 每次调用都有参数、超时、结果和权限限制，不能获得通用 shell。
  4. Agent-Reach 或任一上游失败时，本地 Assistant 和其他能力继续工作。

**Plans**: 3 plans

Plans:

- [x] 06-01: 定义 ResearchGateway、能力白名单和权限模型 (offline verified)
- [x] 06-02: 实现 Agent-Reach Adapter、超时、隔离、日志和结果限制 (offline verified)
- [x] 06-03: 接入 Assistant 工具选择并验证本地降级和无 shell 边界 (offline verified)

### Phase 7: Deployment

**Goal**: 在目标 VPS 建立低维护、可恢复的长期运行和发布体系
**Depends on**: Phase 6
**Requirements**: DEPL-01, DEPL-02, DEPL-03, DEPL-04, DEPL-05
**Success Criteria**:

  1. systemd 可以独立启动、停止、重启和检查 bot/worker，Scheduler、SQLite 和 Agent-Reach 状态可见。
  2. GitHub Actions 可执行 CI、测试、备份和发布，长连接只在 VPS 运行。
  3. 维护者可按 `docs/deployment.md` 完成安装、秘密配置、日志查看、备份和恢复演练。
  4. 服务在 1 核、约 1.87 GB RAM 下通过资源上限长期运行。

**Plans**: 5 plans (four original deliverables plus actual-gap remediation)

Plans:

- [x] 07-01: 建立 trendradar-bot、trendradar-worker 和 Scheduler systemd 服务 (isolated Linux lifecycle/full regression passed; VPS pending)
- [x] 07-02: 配置 VPS 秘密、健康检查、日志轮转和资源限制 (offline remediation verified; target measurement pending)
- [x] 07-03: 建立 GitHub Actions CI、测试、备份和发布流程 (offline remediation verified; remote execution pending)
- [x] 07-04: 编写并验证部署、重启、备份和恢复文档 (offline remediation verified; operator drill pending)
- [ ] 07-05: 修复实际缺口，完成 28 项 ENV/HEALTH/PERM/GUARD/RG 验证及 G1/G2/G3 证据 (local work complete; 27 PASS/1 BLOCKED, G1 PASS; G2 clean candidate/G3 target open; see HANDOFF)

### Phase 8: Testing

**Goal**: 完成 v5.0 单元、集成、兼容和发布级质量验证
**Depends on**: Phase 7
**Requirements**: TEST-01, TEST-02, TEST-03, TEST-04, TEST-05
**Success Criteria**:

  1. 核心模型、Adapter、Pipeline、Gemini、安全、飞书和 ResearchGateway 具有自动化单元测试。
  2. `Feishu Message -> Assistant -> Gemini -> Response` 主链路通过集成测试。
  3. 现有 CLI、配置、SQLite、日报和 91 项 AI Frontier 测试在 v5.0 下继续通过。
  4. CI 自动执行测试、增量 Ruff、配置/依赖一致性、迁移和秘密扫描并形成发布证据。

**Plans**: 3 plans

Plans:

- [ ] 08-01: 补齐模型、Adapter、Pipeline、Gemini、安全、飞书和 ResearchGateway 单元测试
- [ ] 08-02: 建立飞书到 Gemini 的集成测试和关键故障场景验证
- [ ] 08-03: 完成兼容回归、CI 质量门禁和 v5.0 发布验收

## Progress

**Execution Order:** Phase 0 -> 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 0. Project Baseline Stabilization | 2/2 | Complete    | 2026-08-21 |
| 1. Unified Intelligence Data Layer | 4/4 | Complete    | 2026-08-21 |
| 2. Story Intelligence | 4/4 | Complete | 2026-09-04 |
| 3. Security Intelligence Domain | 3/3 | Complete | 2026-09-04 |
| 4. Gemini Intelligence Layer | 4/4 | Complete | 2026-09-04 |
| 5. Feishu Assistant | 4/4 | Complete (offline verified) | 2026-09-12 |
| 6. Agent-Reach Integration | 3/3 | Complete (offline verified) | 2026-10-11 |
| 7. Deployment | 4/5 | Actual-gap remediation in progress; VPS pending | - |
| 8. Testing | 0/3 | Not started | - |
