# Requirements: TrendRadarpoi v5.0

**Defined:** 2026-08-20
**Core Value:** 把多个来源关于同一事件的内容聚合成可解释、可排序、可追问的 Story，并通过飞书持续交付真正重要的个人情报。
**Authority:** `TrendRadarpoi_v5_CODEX_CONTEXT.md`、`TrendRadarpoi_v5_Codex_Task_List.md`、`TrendRadarpoi_v5_Implementation_Plan_Codex_Execution_Edition.md`

## v5.0 Requirements

### Phase 0 - Baseline Stabilization

- [x] **BASE-01**: 维护者可以在 `docs/code-review.md` 查看当前模块依赖、架构图、高耦合区域和渐进重构建议
- [x] **BASE-02**: 基线整理不改变现有运行行为，并记录可重复执行的启动、测试和数据兼容验证结果
- [x] **CONF-01**: 本地、GitHub Actions 和 VPS 通过一个统一 settings 边界读取 YAML、环境变量和默认值
- [x] **CONF-02**: 仓库提供不含真实凭据的 `.env.example`，所有活动 Key、Token 和 Secret 都由外部注入
- [x] **CONF-03**: Gemini、飞书、SQLite 路径和外部服务配置在本地与 VPS 使用相同字段和优先级规则

### Phase 1 - Unified Intelligence Data Layer

- [x] **CONT-01**: 系统用统一 `ContentItem` 保存 ID、标题、正文、URL、来源、领域、发布时间、标签和元数据
- [x] **CONT-02**: `ContentItem` 能无损表达现有热点、RSS、GitHub、AI Frontier 和后续安全来源的有效字段
- [x] **ADPT-01**: 每个来源通过包含 `fetch()`、`normalize()` 和 `health_check()` 的 Source Adapter 接入核心流水线
- [x] **ADPT-02**: 现有新闻、RSS、GitHub 和其他来源可以逐步迁移，未迁移来源在过渡期继续工作
- [x] **NORM-01**: Normalize 统一 URL、时间、空白、来源、领域和标签格式后再进入业务流水线
- [x] **NORM-02**: 标准化保留原始字段或来源元数据，使兼容输出和问题审计可追溯
- [x] **DEDU-01**: Deduplicate 使用 canonical URL、URL hash、标题相似度和时间窗口识别内容副本
- [x] **DEDU-02**: 去重只删除同一内容副本，不删除描述同一事件的不同来源条目
- [x] **DEDU-03**: 相同输入重复处理和写入时结果幂等，不产生重复 `ContentItem`
- [x] **COMP-01**: 现有 CLI、YAML 配置、SQLite 历史、日报和通知渠道在迁移期间保持可用

### Phase 2 - Story Intelligence

- [x] **CLUS-01**: Cluster Engine 使用时间接近度、标题相似度、实体关键词和主题标签分组相关 `ContentItem`
- [x] **CLUS-02**: 同一事件的多来源条目可以聚合，不同实体或事件保持独立，未匹配条目可形成单条 Story
- [x] **STOR-01**: Story 包含稳定 ID、标题、摘要、成员条目、Importance 和标签
- [x] **STOR-02**: 后续来源到达时可以幂等更新已有 Story，而不是重复创建同一事件
- [x] **STOR-03**: Story Generator 可以使用 Gemini 把 Cluster 转换为包含上下文和来源的可读情报
- [x] **STOR-04**: Gemini 不可用时，Cluster、Story 身份、成员关系和基础排序仍然可用
- [x] **RANK-01**: Story Ranking 综合来源数量、来源可靠性、增长速度和用户兴趣计算优先级
- [x] **RANK-02**: 每日报告以 Story 而不是原始文章为主体，并展示 Importance 原因和原始来源

### Phase 3 - Security Intelligence Domain

- [x] **SECU-01**: `domains/security/` 提供独立 collector、analyzer 和 report 职责
- [x] **SECU-02**: 系统采集 CISA KEV 和 NVD CVE 数据，并保留漏洞 ID、严重性和已利用状态
- [x] **SECU-03**: 用户可以配置漏洞新闻、安全 RSS 和安全事件来源
- [x] **SECU-04**: 所有安全数据转换为 `ContentItem` 并复用 Normalize、Deduplicate、Cluster 和 Ranking
- [x] **SECU-05**: 同一漏洞或事件的官方数据和新闻可以生成一个 Security Story
- [x] **SECU-06**: 安全报告优先展示高严重性、已利用或需要行动的 Story；来源失败时标记数据新鲜度

### Phase 4 - Gemini Intelligence Layer

- [x] **GEMI-01**: 核心 `GeminiClient` 提供 `chat()`、`summary()` 和 `analyze()`，且不依赖 MCP 层
- [x] **GEMI-02**: Gemini 模型、凭据、超时、重试、限流和错误映射通过统一配置和客户端管理
- [x] **GEMI-03**: Translation、Story Generation、Daily Digest、Security Analysis 和 Chat 共用 Gemini 服务边界
- [x] **GEMI-04**: Gemini 缺失、超时、限流或返回异常时，采集、存储和确定性 Story 流程继续运行
- [x] **ASST-01**: Assistant Service 负责对话处理、上下文加载和受控工具选择
- [x] **ASST-02**: 多轮 Session 和有限历史上下文保存在 SQLite，并具有长度和过期限制
- [x] **ASST-03**: 用户可以查询本地 Story 和 ContentItem 历史，回答包含时间范围和来源证据
- [x] **ASST-04**: Assistant 只能调用登记工具，不能获得任意文件、通用 shell 或未授权外部能力

### Phase 5 - Feishu Assistant

- [x] **FEIS-01**: `integrations/feishu/` 分离 client、handler 和 session 职责
- [x] **FEIS-02**: 飞书通过官方 SDK WebSocket 长连接运行，不要求公网 webhook
- [x] **FEIS-03**: 白名单用户可以发送文本消息并收到 Assistant/Gemini 回复
- [x] **FEIS-04**: 系统按配置时间和 `Asia/Shanghai` 时区向飞书推送每日 Story 报告
- [x] **FEIS-05**: 只有 `allowed_users` 中的个人身份可触发 Gemini 和工具，默认拒绝所有用户
- [x] **FEIS-06**: 长连接支持有界重连、错误隔离和消息幂等；重复事件重放已存回复而不重复生成，已确认日报窗口不重发
- [x] **FEIS-07**: Feishu App ID、App Secret 和用户标识通过环境或 VPS Secret 配置且不写入日志

### Phase 6 - Agent-Reach Integration

- [x] **RSCH-01**: Agent-Reach 通过独立 ResearchGateway 接入，不属于 crawler 且不是基础运行的强依赖
- [x] **RSCH-02**: Research Adapter 提供文档规定的 `research()`、`search()` 和 `fetch()` 受控接口
- [x] **RSCH-03**: ResearchGateway 包装 Agent-Reach 选定的 Web、GitHub、Reddit、YouTube 等能力
- [x] **RSCH-04**: 每次研究调用都有参数校验、超时、错误隔离、结果上限和审计日志
- [x] **RSCH-05**: 飞书用户和 Gemini 都不能通过 ResearchGateway 获得通用 shell 或任意命令执行

### Phase 7 - Deployment

- [ ] **DEPL-01**: VPS 通过 systemd 管理 `trendradar-bot` 和 `trendradar-worker` 服务
- [ ] **DEPL-02**: VPS 运行 Feishu Bot、Assistant Worker、Scheduler、SQLite 和 Agent-Reach，并提供健康检查
- [ ] **DEPL-03**: GitHub Actions 负责 CI、测试、备份和发布，不承担长期长连接运行
- [ ] **DEPL-04**: `docs/deployment.md` 记录 VPS 安装、环境变量、服务重启、日志、备份和恢复步骤
- [ ] **DEPL-05**: 目标 1 核、约 1.87 GB RAM 环境通过并发、上下文和结果上限保持稳定运行

### Phase 8 - Testing

- [ ] **TEST-01**: 单元测试覆盖 ContentItem、Story、Adapter、Normalize、Deduplicate、Cluster、Ranking 和 Gemini 服务
- [ ] **TEST-02**: 单元测试覆盖安全模块、飞书 handler/白名单/重连以及 ResearchGateway 权限边界
- [ ] **TEST-03**: 集成测试验证 `Feishu Message -> Assistant -> Gemini -> Response` 主链路
- [ ] **TEST-04**: 兼容测试验证现有 CLI、配置、SQLite 历史、日报和全部既有 AI Frontier 测试
- [ ] **TEST-05**: CI 执行 pytest、增量 Ruff、配置/依赖一致性、迁移与敏感信息检查

## Future Requirements

### Optional Expansion

- **FUTR-01**: 当现有检索质量出现可测量缺口时，再评估语义搜索和 Vector Storage
- **FUTR-02**: 个人知识图谱、更多研究工具和更多通知入口按实际使用反馈规划

## Out of Scope

| Feature | Reason |
|---------|--------|
| Full rewrite | 文档要求通过接口和 Adapter 渐进迁移现有系统 |
| SaaS or multi-tenant platform | 项目只服务一个个人用户 |
| PostgreSQL or distributed database | SQLite 已满足当前容量和低维护目标 |
| Vector database in v5.0 | 先完成结构化 Story 和可验证检索，再按实际缺口评估 |
| Kubernetes, microservices, or complex queues | 目标 VPS 和个人运维不需要企业级基础设施 |
| General shell access | 与飞书和 ResearchGateway 的最小权限边界冲突 |

## User Stories

- 作为个人用户，我每天在飞书收到少量重要 Story，而不是大量重复文章。
- 作为个人用户，我可以追问 Story 背景、重要性和来源，并在本地数据不足时触发受控研究。
- 作为个人用户，我可以看到需要行动的安全情报及其 CVE、KEV 和严重性依据。
- 作为维护者，我可以逐阶段迁移现有系统，并在每个阶段继续运行原有抓取和通知任务。
- 作为维护者，我可以在小型 VPS 上用统一配置、systemd、备份和 CI 长期维护服务。

## Definition of Done

- Phase 0-8 的全部 v5.0 需求映射到唯一阶段并通过对应验收。
- 现有功能和数据兼容性经过验证，每个迁移步骤可备份、恢复和回滚。
- 日报以 Story 为核心，Gemini、飞书和 Agent-Reach 均通过受控接口接入。
- 飞书白名单、ResearchGateway 权限、秘密注入和无通用 shell 边界通过测试。
- 目标 VPS 服务、CI、单元测试、端到端测试和部署文档可重复执行。

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| BASE-01 | Phase 0 | Complete |
| BASE-02 | Phase 0 | Complete |
| CONF-01 | Phase 0 | Complete |
| CONF-02 | Phase 0 | Complete |
| CONF-03 | Phase 0 | Complete |
| CONT-01 | Phase 1 | Complete |
| CONT-02 | Phase 1 | Complete |
| ADPT-01 | Phase 1 | Complete |
| ADPT-02 | Phase 1 | Complete |
| NORM-01 | Phase 1 | Complete |
| NORM-02 | Phase 1 | Complete |
| DEDU-01 | Phase 1 | Complete |
| DEDU-02 | Phase 1 | Complete |
| DEDU-03 | Phase 1 | Complete |
| COMP-01 | Phase 1 | Complete |
| CLUS-01 | Phase 2 | Complete |
| CLUS-02 | Phase 2 | Complete |
| STOR-01 | Phase 2 | Complete |
| STOR-02 | Phase 2 | Complete |
| STOR-03 | Phase 2 | Complete |
| STOR-04 | Phase 2 | Complete |
| RANK-01 | Phase 2 | Complete |
| RANK-02 | Phase 2 | Complete |
| SECU-01 | Phase 3 | Complete |
| SECU-02 | Phase 3 | Complete |
| SECU-03 | Phase 3 | Complete |
| SECU-04 | Phase 3 | Complete |
| SECU-05 | Phase 3 | Complete |
| SECU-06 | Phase 3 | Complete |
| GEMI-01 | Phase 4 | Complete |
| GEMI-02 | Phase 4 | Complete |
| GEMI-03 | Phase 4 | Complete |
| GEMI-04 | Phase 4 | Complete |
| ASST-01 | Phase 4 | Complete |
| ASST-02 | Phase 4 | Complete |
| ASST-03 | Phase 4 | Complete |
| ASST-04 | Phase 4 | Complete |
| FEIS-01 | Phase 5 | Complete (offline verified) |
| FEIS-02 | Phase 5 | Complete (offline verified) |
| FEIS-03 | Phase 5 | Complete (offline verified) |
| FEIS-04 | Phase 5 | Complete (offline verified) |
| FEIS-05 | Phase 5 | Complete (offline verified) |
| FEIS-06 | Phase 5 | Complete (offline verified) |
| FEIS-07 | Phase 5 | Complete (offline verified) |
| RSCH-01 | Phase 6 | Complete (offline verified) |
| RSCH-02 | Phase 6 | Complete (offline verified) |
| RSCH-03 | Phase 6 | Complete (offline verified) |
| RSCH-04 | Phase 6 | Complete (offline verified) |
| RSCH-05 | Phase 6 | Complete (offline verified) |
| DEPL-01 | Phase 7 | Pending |
| DEPL-02 | Phase 7 | Pending |
| DEPL-03 | Phase 7 | Pending |
| DEPL-04 | Phase 7 | Pending |
| DEPL-05 | Phase 7 | Pending |
| TEST-01 | Phase 8 | Pending |
| TEST-02 | Phase 8 | Pending |
| TEST-03 | Phase 8 | Pending |
| TEST-04 | Phase 8 | Pending |
| TEST-05 | Phase 8 | Pending |

**Coverage:**
- v5.0 requirements: 59 total
- Mapped to phases: 59
- Unmapped: 0

---
*Requirements defined: 2026-08-20*
*Last updated: 2026-09-04 after Phase 4 verification*
