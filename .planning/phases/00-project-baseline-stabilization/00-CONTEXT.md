# Phase 0: Project Baseline Stabilization - Context

**Gathered:** 2026-08-21
**Status:** Ready for planning
**Source:** v5 Codex documents and confirmed roadmap

<domain>
## Phase Boundary

本阶段只固定现有架构、运行、SQLite 兼容和配置边界。交付 `docs/code-review.md`、
可重复基线验证、统一 settings 接口与 `.env.example`。不引入 `ContentItem`、Adapter、
Story、Gemini Assistant、飞书长连接或 Agent-Reach；这些属于后续阶段。

</domain>

<decisions>
## Implementation Decisions

### Compatibility
- 保持 `python -m trendradar`、`python -m trendradar.ai_frontier`、MCP、现有 YAML 字段、
  SQLite schema 和通知行为兼容。
- 先用特征测试固定当前行为，再迁移配置读取点；不得借本阶段整理业务流水线。
- SQLite 继续作为主数据库，不做 schema 迁移。

### Configuration
- 配置优先级固定为：显式函数/CLI 路径 > 环境变量 > YAML > 代码默认值。
- canonical settings 实现在可打包的 `trendradar/core/settings.py`；文档指定的
  `config/settings.py` 只提供稳定转发入口，避免 wheel 运行时依赖仓库根目录包。
- Gemini、飞书凭据只从环境注入；`.env.example` 只列空值和说明，不加载或提交 `.env`。
- 数据库路径、时区和外部服务字段通过同一 settings 对象解析，本地、GitHub Actions 与
  VPS 使用相同环境变量名。

### Documentation
- `docs/code-review.md` 必须包含 Mermaid 架构图、依赖方向、高耦合模块和渐进重构顺序。
- `docs/baseline.md` 必须记录无网络的可重复命令、当前测试结果和 SQLite 兼容检查。

### Claude's Discretion
- dataclass 的内部拆分、测试 fixture 组织和文档表格布局可按现有 Python 风格决定。
- 不改变现有配置字典对外形状的前提下，可以提取通用 YAML/env 解析函数。

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Product and execution authority
- `TrendRadarpoi_v5_CODEX_CONTEXT.md` - v5 架构边界、兼容与部署约束。
- `TrendRadarpoi_v5_Codex_Task_List.md` - TASK-001/TASK-002 的交付物和验收条件。
- `TrendRadarpoi_v5_Implementation_Plan_Codex_Execution_Edition.md` - Phase 0 的执行顺序与配置范围。

### Repository baseline
- `.planning/codebase/ARCHITECTURE.md` - 三个运行面、依赖方向和架构约束。
- `.planning/codebase/CONCERNS.md` - 高耦合、SQLite、通知和配置风险。
- `.planning/codebase/TESTING.md` - 当前 91 项 AI Frontier 测试及缺口。
- `config/config.yaml` - 现有 YAML 字段和默认值的兼容权威。

</canonical_refs>

<specifics>
## Specific Ideas

- 统一设置边界应覆盖 `CONFIG_PATH`、`TIMEZONE`、`GEMINI_API_KEY`、`FEISHU_APP_ID`、
  `FEISHU_APP_SECRET`、`FEISHU_ALLOWED_USERS`、`DATABASE_PATH`、`AI_FRONTIER_DB_PATH`
  和现存外部服务环境变量。
- MCP 只能依赖核心 settings；核心 settings 不得导入 `mcp_server`。
- 已作废的 Google API key 按用户决定暂不处理，不复制到新文件、日志或测试快照。

</specifics>

<deferred>
## Deferred Ideas

- ContentItem、Adapter、Normalize、Deduplicate 延至 Phase 1。
- Cluster、Story、Ranking、Importance 延至 Phase 2。
- Gemini 服务重构、飞书 Assistant、Agent-Reach 和 VPS 服务分别留在 Phase 4-7。

</deferred>

---

*Phase: 00-project-baseline-stabilization*
*Context gathered: 2026-08-21 from confirmed v5 documents*
