# TrendRadarpoi：Phase 7 完整部署计划与 Agent 执行框架

- 文档版本：1.0
- 基线日期：2026-10-12，Asia/Shanghai
- 项目：C:/Users/DELL/Desktop/TrendRadarpoi-master
- 对应阶段：Phase 7 — Deployment
- 承接文件：TrendRadarpoi-Phase1-6-修复计划.md、docs/phase1-6-fix-audit.md
- 原定工作包：07-01、07-02、07-03、07-04；不新增 Phase，不重排既有编号。
- 文档性质：实施计划与状态基线。07-01 至 07-04 的代码、脚本、systemd 模板和离线验收已完成；Linux/VPS 现场验收、远程发布和真实运行仍不表示已执行。
- 置信度：离线实现与测试证据为高；目标 VPS 资源余量、外部网络及真实服务表现为未知，须现场验证。

## 1. 给接手 agent 的任务说明

将已经实现的 Phase 1–6 能力部署为一套个人可长期维护的运行系统：

1. VPS 持续采集数据，更新统一情报和兼容历史库。
2. Lark Bot 持续接收获授权消息，并在接收后保留可恢复的本地工作状态。
3. Assistant Worker 独立处理聊天、调用获准能力和重试已生成的回复。
4. 日报调度独立于聊天 Worker，使用已有投递检查点。
5. 代码、依赖、配置、数据库、发布、备份和恢复均有可重复执行的流程。
6. 在目标小型 VPS 的实际资源限制下，证明队列能前进、数据持续更新、异常能够恢复。

### 1.1 延续前一份修复计划的逻辑

每个工作包都必须包含：现状与差距、实现目标、明确的职责边界、实施步骤、交付物、验收用例、失败处理与证据。

R1–R6 已有实现和离线验证记录；先检查当前成果，再复用。不能把旧修复计划中的“当时尚未修复”当作今天的状态，也不能为满足文件命名重建另一套 inbox/outbox。

本阶段重点是部署闭环。Story 聚类、Importance 算法、Assistant 工具范围和旧报告逻辑不在本阶段重写。

### 1.2 保持的范围

- 保持现有主采集、RSS、AI Frontier、Security、统一数据层、Lark 和 MCP 兼容。
- 延续模块化单体与 SQLite，不引入 Redis、Celery、PostgreSQL、向量库、Kubernetes 或微服务网络。
- Lark 使用官方 SDK 长连接，不为 Bot 新开公网回调端口。
- MCP 继续按已有使用方式保留；本计划不开放新的公网 MCP 服务。
- 外部研究默认关闭；逐能力验收，不因 Phase 6 离线完成而整体开启。
- 所有模型及研究调用仍经过既有授权、固定工具、引用、超时和结果限制。
- 保存用户未提交改动，以及 output/、test/runtime/ 和其 WAL/SHM、日志、fixture。
- 本文件同时作为实施记录和后续验收清单。已有代码、模板和离线证据不等于取得真实消息发送、生产切换、Git 提交或推送的授权；沿用会话中已明确授予的对应授权，不重复索要。

## 2. 已核实基线与待确认条件

### 2.1 当前项目事实

| 项目 | 核实结果 | 对 Phase 7 的影响 |
| --- | --- | --- |
| 原始部署需求 | DEPL-01 至 DEPL-05；ROADMAP 为 0/4、Not started | 保留四个工作包及需求映射 |
| 运行入口 | 公开入口为 python -m trendradar.integrations.lark | 对外文档使用 Lark 名称；内部 feishu 包保留兼容 |
| 当前进程模型 | run_bot 启动 Worker 线程；Worker 内每约 60 秒运行 Scheduler | 不能把同一现有入口放入两个 unit 冒充进程拆分 |
| 入站与回复恢复 | schema v6 的 feishu_events 保存准备后的事件、租约、回复与投递重试状态 | 跨进程复用现有账本，不另建竞争的工作协议 |
| SQLite 同步策略 | storage.py 当前对连接设置 synchronous=NORMAL | 进程恢复与主机掉电持久性须区分；生产消息账本需要明确加强同步策略 |
| 已完成事件 | 重复事件不再次调用 Assistant，也不再次发送回复 | 拆分、迁移、恢复时必须保持此语义 |
| 日报 | feishu_deliveries 保存窗口、分块及发送检查点 | Scheduler 继续复用这套幂等机制 |
| 主采集 | 主入口包含热点、RSS 及 best-effort Security 路径 | 默认不再额外调度一份 Security 采集 |
| AI Frontier | 有独立入口，同时写统一库和自己的兼容库 | 需要独立定时任务并指向同一统一库 |
| 统一数据存储 | intelligence.db 目前只在本地，未由 S3 后端同步 | 不能假定 Actions 的采集结果会自动到达 VPS |
| 旧数据 | news/、rss/ 的日期库和 ai_frontier.db 仍服务旧报告/MCP | 备份和迁移不能只考虑 intelligence.db |
| 既有 Actions | 仍有 crawler、ai-frontier、docker、clean-crawler 等旧工作流 | 它们不是新部署体系；需明确采集和通知的唯一执行方 |
| 已知离线验证 | Phase 7 交付后全量 `python -B -m pytest tests -q -p no:cacheprovider` 为 511 passed、1 warning；scoped Ruff 与 `git diff --check` 通过 | 作为当前离线基线；不替代 Linux/VPS 现场证据 |
| 当前发布状态 | 大量改动尚未形成已核实的部署版本 | 发布前固定实际代码与依赖来源 |
| 部署产物 | `deploy/`、`scripts/deploy/`、`trendradar/ops/`、对应 systemd unit、`docs/deployment.md` 和验收记录已存在 | 复核与现场验收，不重复创建或重建另一套部署体系 |

文档与源码冲突时，以当前源码和实际执行证据为准，并同步修正文档。不要采用 PROJECT.md 等旧说明中的历史测试数作为最新结果。

### 2.2 仍然没有现场确认的信息

| 条件 | 当前认知 | 如何消除不确定性 |
| --- | --- | --- |
| VPS | 规划目标为 1 CPU、约 1.87 GB RAM | 核对实际主机、OS、CPU 架构、MemTotal、磁盘、现有负载 |
| Python/systemd/SQLite | 项目声明 Python >=3.10；目标版本未知 | 记录目标服务实际解释器及链接的 SQLite，不能只看系统 sqlite3 命令 |
| 外部网络 | Lark、Gemini、各采集源和研究服务的目标 VPS 可达性未知 | 部署验收时逐项验证，保存错误分类与耗时 |
| 实际运行库 | 本地有 UAT 数据和测试 fixture；生产初始化来源未确定 | 明确新建生产库或导入指定历史，不复制整个 UAT 沙箱 |
| GitHub 发布 | 分支、环境、部署身份和网络可达性待核对 | 在 07-03 的 release manifest 和工作流配置中固定 |
| 异地备份 | 目的地、权限、加密和保留费用未知 | 在首次长期启用前落实；不能只留下同机副本 |
| 真实 UAT | C3 断网/冷却恢复、C4 日报接收确认尚待补证据 | 纳入本阶段上线验收，沿用已通过项目和已接受例外 |

以上未知项不阻止完成代码、模板和离线测试；会阻止对应的“真实部署通过”结论。

## 3. 目标架构与固定决策

### 3.1 默认采用的部署形态

采用两个常驻 Python 服务，加若干按需执行的 systemd oneshot 服务及 timer。仍然是同一仓库、同一核心库和同机 SQLite，没有新增网络服务之间的 RPC。

| 组件 | 运行形式 | 唯一职责 | 明确不承担 |
| --- | --- | --- | --- |
| trendradar-bot | 常驻 service | Lark 长连接、身份与消息规范化、持久化入站 | Assistant 推理、日报、采集 |
| trendradar-worker | 常驻 service，初始单 Worker | 消费持久事件、Assistant/媒体处理、回复发送与重试 | 第二条长连接、日报调度 |
| trendradar-scheduler | oneshot service + timer | 调用一次已有日报 tick，续传持久分块 | 常驻聊天消费、另一套日报去重 |
| trendradar-collect-main | oneshot service + timer | 运行现有主采集，包含其 Security 路径 | Bot 或新的研究代理 |
| trendradar-collect-ai | oneshot service + timer | 运行 AI Frontier，写同一统一库 | 重复执行主采集 |
| trendradar-backup | oneshot service + timer/Actions 触发 | 一致性快照、校验、异地保存 | 复制正在变化的原始库文件 |
| trendradar-health | 只读检查命令，按需/定时执行 | 汇总运行、数据、队列与备份状态 | 主动发消息、调用模型、创建数据库 |
| SQLite | 同机持久文件 | 情报、会话、消息和投递状态 | 独立数据库守护进程 |
| ResearchGateway/上游 CLI | Worker 按需调用 | 已明确启用的研究能力 | 常驻万能 Agent、任意 shell |

这里“独立 Scheduler”由 oneshot service 实现，符合原计划的 Scheduler 服务要求；无需再常驻一套 Python 主进程。SQLite 和 Agent-Reach 的状态应可见，但不为它们虚构没有必要的守护服务。

### 3.2 数据与消息流

~~~mermaid
flowchart TD
  L["Lark 消息"] --> B["Bot：授权与持久接收"]
  B --> Q["同机 SQLite：事件与回复账本"]
  Q --> W["Worker：Assistant 与投递"]
  W --> Q
  W --> L
  C["VPS 定时采集"] --> D["统一情报与兼容历史库"]
  D --> W
  D --> S["Scheduler：日报窗口与检查点"]
  S --> L
~~~

图中的事件账本和统一情报数据实际复用 intelligence.db；兼容历史库保持现有文件。分开画出只是区分职责，不代表新建第二份统一数据库。

### 3.3 必须在实施中坚持的决策

1. VPS 是新长期运行范围内的数据写入和业务调度中心；Actions 承担 CI、构建、发布和备份控制/验证。
2. Bot 与 Worker 以持久账本通信，queue.Queue 不能作为跨进程工作真相来源。
3. Worker 和 Scheduler 各持有自己的连接与客户端；不跨进程传递 SDK、SQLite connection 或内存锁。
4. 成功落盘才算本地接收成功；有回复后优先重试已保存回复，已完成记录永不正常重发。
5. 日报使用当前目标、上海日期、窗口键和稳定发送 UUID；不增加另一套日期判断。
6. 两个采集入口在 VPS 运行，共享明确的数据库和输出路径，采集之间初始串行。
7. 发布绑定 commit、依赖解析结果、配置版本和 schema；数据库不跟随发布目录替换。
8. 备份成功必须包括可恢复性；灾难恢复不得直接把旧待发送记录重新放行。
9. 功能开关、代码版本回退和数据恢复是三种不同操作。
10. 先部署基础服务；研究增强、采集/日报的额外 Gemini 润色按验收和资源余量开启。

## 4. 执行顺序与需求映射

### 4.1 工作顺序

W0 基线冻结与环境清单 → 07-01 运行拆分和采集调度 → 07-02 配置、状态与资源 → 07-03 构建、备份和发布 → 07-04 现场演练与文档闭环 → Phase 8 全面发布质量验收。

07-02 的路径、配置和日志约定应在 07-01 编码前先确定；07-03 的备份工具必须在第一次真实迁移之前可用。编号是工作包边界，不允许为了顺序形式先迁移、后补备份。

| 工作包 | 核心交付 | 覆盖需求 | 完成门槛 |
| --- | --- | --- | --- |
| 07-01 | 独立角色入口、持久消费、Scheduler、采集 unit/timer | DEPL-01、DEPL-02 | Linux 上进程边界、停启和恢复通过 |
| 07-02 | 稳定目录、秘密注入、健康状态、日志与资源限制 | DEPL-02、DEPL-05 | 无隐式路径、无假健康、资源实测合格 |
| 07-03 | 可复现产物、CI、备份、受控发布与回退 | DEPL-03 | 同一产物可安装；失败不会无声破坏当前版本 |
| 07-04 | 操作手册、首次部署、恢复演练、试运行证据 | DEPL-04，并汇总其余需求 | 维护者按文档能够完成并复现操作 |

### 4.2 分层门槛

| 门槛 | 允许推进到 | 必须已有的证据 |
| --- | --- | --- |
| G0：开发基线可用 | 编码、模板、临时数据库和离线 CI | 当前 R1–R6 状态明确，保护现有改动 |
| G1：部署候选可用 | 目标 Linux 的隔离安装和迁移演练 | 角色拆分、依赖、unit、备份工具离线通过 |
| G2：基础试运行可用 | 指定个人范围内的真实采集、问答和日报 | 真实配置、单实例切换、备份恢复、目标资源初验通过 |
| G3：Phase 7 运行验收通过 | 进入 Phase 8 的发布级质量验收 | C3/C4、连续运行、恢复与操作文档有实际证据 |
| G4：可选研究能力可启用 | 仅开放通过验收的单项能力 | 对应认证、网络、输出契约、超时和资源实测通过 |

G4 不阻塞关闭研究的基础范围完成。Phase 7 完成也不代表 Phase 8 完成。

## 5. W0：实施前基线与部署清单

### 5.1 先读与复核

读取 AGENTS.md、.planning/PROJECT.md、.planning/ROADMAP.md、.planning/REQUIREMENTS.md、.planning/STATE.md、相关 codebase 文档、docs/intelligence.md、docs/phase1-6-fix-audit.md、test/README.md，以及现有 Phase 5/6 的验收记录。

记录：

- 工作分支、HEAD、工作区差异及变更归属；不要自动 stash、reset、clean 或提交。
- R1–R6 实际代码位置、schema 版本、最近已执行测试和已知限制。
- 本地和目标环境是否存在同一 Lark 应用的运行进程、旧 Docker/cron/systemd/Actions 调度。
- 本轮计划的具体发布范围、启用来源、通知目标与关闭能力。
- 当前依赖声明、SDK 固定版本、Python 支持声明及目标解释器版本。

如接手时其他 agent 已完成部分 Phase 7，应合并事实并补缺口，不能覆盖其已验证成果。

### 5.2 VPS 预检

只记录必要的系统信息，不输出秘密或无关用户文件：

- 主机身份与授权目标，Linux 发行版、版本、架构。
- CPU、实际内存、交换空间、现有常驻服务、可用磁盘和 inode。
- systemd、cgroup 能力、Python、pip、Python sqlite3.sqlite_version、时钟同步、时区数据、CA 证书。
- 持久文件系统类型；生产 WAL 数据库必须位于同一主机本地存储。
- 服务用户、部署用户、目录权限、出站 DNS/TLS 和目标接口可达性。
- 是否已有支持的异地备份位置，以及 GitHub runner 到 VPS 的受限发布通道。

SQLite 额外版本门槛：官方已公布多连接 WAL 场景中的 WAL-reset 缺陷，3.51.3 及以后包含修复，部分旧分支有回移版本。核对 Python 实际链接库或发行版补丁证明；不能仅以“Python 版本较新”判定已修复。当前并未确认此项目发生过损坏，也未确认目标库版本受影响。[S3]

缺少目标信息时继续完成可离线工作，把缺口写进 preflight 表；不要填写推测的 VPS 参数。

### 5.3 初始化与历史导入决策

默认新生产运行状态与 Windows UAT 分离：

1. 创建新的生产状态目录。
2. 若需要历史内容，选定明确的 news/rss/AI 历史库，用现有 backfill 在隔离副本验证后导入。
3. 不将测试 fixture、UAT 会话、测试 pending 事件、测试日报目标直接导入生产。
4. 如确需完整搬迁已有正式库，必须证明它是目标生产数据，先做一致性快照并记录队列/投递状态。
5. backfill 使用明确目标路径和日期，生产运行期间不无界重建历史。
6. 旧 Actions cache 或 S3 中的数据只有经明确导出、验证和导入后才算迁入；不做隐式多端数据库合并。

## 6. 07-01：运行角色、持久消费与 systemd 调度

### 6.1 07-01-A：新增角色入口，保留兼容入口

建议扩展公开 Lark CLI：

~~~text
python -m trendradar.integrations.lark --role bot --config <path>
python -m trendradar.integrations.lark --role worker --config <path>
python -m trendradar.integrations.lark --role scheduler-once --config <path>
python -m trendradar.integrations.lark --role bot --check --config <path>
~~~

上述 --role 是待实现接口，不是现成命令。可以按仓库风格调整命名，但交付文档、unit 和测试必须一致。

- 不带 --role 的旧运行方式保留为 combined 兼容模式，默认仍由现有启用开关控制。
- combined、bot、worker、scheduler 都必须遵守同一角色排他规则，避免人为绕过 unit 后重复运行。
- --check 保持纯配置检查：不联网、不打开或创建运行库、不构建真实 SDK/provider。
- 各角色按需要验证配置，Bot 不因未配置研究 token 而失败。
- 延迟导入 Assistant/Gemini/研究实现，减少纯接收进程不必要的初始化。
- Worker 需要 Lark 发送及媒体客户端，但绝不能初始化 SDK WebSocket。
- Scheduler 只建立日报所需依赖，不创建 Assistant 会话或聊天消费线程。

### 6.2 07-01-B：Bot 的接收协议

1. 保持原有身份、chat type、群聊 @ 等校验顺序。
2. 先规范化事件，再将最小恢复载荷持久写入现有 EventLedger。
3. record 成功后才能正常返回 SDK 回调；失败必须沿用经验证的错误/重试路径。
4. completed 重复事件正常确认后结束；不再发送“已完成”的第二条回复。
5. 队列容量在持久存储中原子检查；不能用进程内长度作为唯一上限。
6. Bot 重启不得回收 Worker 的仍有效租约，也不调用全局“重置所有 processing”。
7. DB busy、磁盘满、权限错误与载荷错误分类记录；不泄露原始正文。
8. SDK 的实际确认/重投行为必须有对应版本测试；本地持久化不能证明平台无限重试。

生产持久性要求：当前统一库使用 WAL + synchronous=NORMAL，不能据此承诺主机掉电或硬重启后所有已确认事务都保留。SQLite 文档明确区分 NORMAL 与 FULL 的提交持久性。[S2] 本计划默认生产统一库的所有写连接使用 FULL，并统一从连接构造边界落实，覆盖 Bot、Worker、租约心跳、Scheduler 和采集；不得只执行一次 PRAGMA 就假定其他连接也改变。若引入配置项，明确默认值、传播路径和非法值拒绝，实测增加的写入延迟。健康信息应由各角色报告自己的实际连接策略，而不是打开一个新连接推断所有写者。进程 kill 测试不能冒充掉电验证；生产机无需为验收直接做硬断电。

进程间不要求增加唤醒通道；初版 Worker 有界轮询 SQLite 即可。内存队列若保留，仅作为单进程优化，不是可靠性基础。

### 6.3 07-01-C：Worker 的消费协议

- 从 pending_events 或等价查询提取候选，通过现有原子 claim 取得所有权后执行。
- 初始一名逻辑 Worker；一次只处理一个聊天任务，研究并发初始不超过 1。
- 轮询空闲间隔建议 0.5–1 秒；遇锁和错误有退避，不能忙循环。
- 恢复时重新核对当前授权、principal/session/chat 绑定和载荷版本。
- 未生成回复：通过 Assistant 的 request_id 与会话幂等处理。
- 已保存回复：直接继续投递，不重新调用模型。
- completed：不消费、不重发；损坏终态按现有 fail-closed 路径处理。
- 租约到期、owner fencing、心跳和重试次数复用 R1/R2 成果。
- 永久错误和耗尽重试的事件停止自动处理，保留脱敏可见状态。
- Worker 崩溃非零退出，让 systemd 恢复；不能只留下“进程在、消费线程已死”。
- 不承诺跨外部平台的 exactly-once；平台已接受而本地尚未确认的窗口仍须明确记录。

### 6.4 07-01-D：Scheduler 从 Worker 中移出

- 独立角色调用现有 DeliveryScheduler.tick()，执行一次后退出。
- 建议 timer 每约 60 秒触发；窗口仍由现有 Asia/Shanghai 配置决定。
- 从拆分后的 Worker 中删除日报 tick；combined 模式只保留其自己的一份 Scheduler。
- 使用同一个 feishu_deliveries 表及稳定 UUID，不新建另一套日报表。
- 初始日报使用确定性格式，不注入 Gemini key；聊天 Gemini 可独立启用。
- 已保存 chunks 时恢复原分块和 next_chunk，不因重启重新生成整份日报。
- 对 send_failed、empty、unavailable、lease_lost 等返回值形成明确健康状态，不能一概记录成功。
- 为单次 tick 定义总执行预算，包括准备、分块发送、请求重试和退出；不能只给单次 HTTP 设置 timeout。
- 进程预算耗尽时保留检查点，下一次在窗口内继续；未发送分块不得标记完成。
- timer 不会自动创建同一仍运行 unit 的第二个实例；应用仍需防止手工命令和 combined 并发。[S5]
- 默认不补发已经错过的历史日期日报。重启仍在当前窗口内可重试，过窗则记录 missed，不伪装成功。
- 重启跨午夜、跨日窗口、时钟校正和投递时间修改都要有明确定义。

日报时间沿用有效的用户配置，不把文档示例的时间写成用户已选时间。窗口应覆盖启动、任务预算及短时断网恢复。

### 6.5 07-01-E：把采集接到 VPS 数据库

| 任务 | 默认沿用的频率基线 | 调用逻辑 | 关键约束 |
| --- | --- | --- | --- |
| 主采集 | 每小时一次，原 Actions 为每小时第 30 分钟 | 现有主入口 | 包含现有 Security 路径 |
| AI Frontier | 每 2 小时一次，原 Actions 为整点 | 现有 AI Frontier 入口 | 统一库与兼容库都落在稳定状态目录 |
| 日报 | timer 检查窗口，窗口内幂等投递 | 现有 Scheduler | 不与聊天共用阻塞消费循环 |
| 历史回填 | 显式维护任务 | 现有 backfill | 不作为每次开机默认动作 |

实施要求：

1. 两个采集任务使用同一明确的 INTELLIGENCE_DB_PATH，保留各自的兼容数据库。
2. 主采集与 AI Frontier 共享一个采集排他锁；同一任务重入也必须被拒绝或跳过。
3. 锁竞争记作 skipped_busy，不冒充成功；持续跳过通过 freshness/health 暴露。
4. 默认只补一次当前采集，不重放机器关机期间每一个 cron 时间点。
5. 若 timer 使用 Persistent=true，必须验证开机后不会造成两个来源组争抢、重复通知或连续追赶。[S5]
6. 初始参考单批总预算 20 分钟，按实际来源最慢路径调整；超时清理所属子进程。
7. 限制采集内部并发；初始 RSS/AI/Security 并发目标不超过 2，不能仅限制外层入口而放任内部 fan-out。
8. 统一库写入可能 best effort 失败而旧报告仍成功。部署检查必须同时读取本次 canonical/source_runs 结果，不能只看进程 exit 0。
9. 来源失败隔离保留；某个来源失败不能触发所有来源重新抓取。
10. 在 VPS 稳定前保留旧调度；切换时先停旧调度、确认已在跑的旧任务结束，再启用同范围 VPS timer。
11. 旧报告/Bark/webhook 的功能保留，但同一任务、同一目标只有一处发送。不得长期让 Actions 和 VPS 重复推送。
12. 不把 Actions cache 当生产统一库，也不引入两份 SQLite 的自动双向同步。

### 6.6 07-01-F：服务生命周期与互斥

- Bot 和 Worker 能独立 stop/start/restart；停 Worker 时 Bot 可继续接收至持久队列上限。
- systemd 的 After 只表达顺序，不代表另一服务已就绪。不要用强绑定让 Worker 重启无理由切断 Bot。
- 首次初始化或迁移由独立维护步骤完成，再启动角色；禁止两个服务同时隐式升级库。
- 角色启动前确认库存在、schema 兼容、路径一致；库缺失时不得静默新建空库后报告健康。
- Linux 使用进程持有的角色锁；combined 按固定顺序一次获得 bot、worker、scheduler 所需锁。
- 锁包含数据库/部署身份，使用固定共享目录；不放到被 PrivateTmp 隔离的 /tmp。
- 文件存在不等于仍持锁；使用 OS 锁，不靠容易留下的 PID 文件判断。
- 本机锁无法排除 Windows 上同一 Lark 应用：首次切换必须停旧 Bot，并记录实际进程状态。
- 服务使用前台进程；建议 Type=simple、Restart=on-failure、有限 RestartSec 和 StartLimit。
- 配置错误、schema 不兼容、重复实例应有不同退出分类，并避免无限快速重启。
- SIGTERM：Bot 先停止接收并关闭长连接；Worker 停止新 claim，有限等待当前任务；Scheduler 保存已有检查点。
- TimeoutStopSec 必须大于应用实际退出预算，计入模型重试、工具调用、发送与清理；超时由 systemd 清理服务进程组。[S4]
- 不在尚未实现 sd_notify 心跳时使用 Type=notify/WatchdogSec 来假装具备应用 watchdog。
- SDK 正常冷却期间不靠自动重启绕过冷却；健康检查要识别 cooldown 期限，systemd 重启策略不能抵消既有有界重连。
- 收到失败后的恢复依赖持久租约；不为了重启速度粗暴清空 processing 状态。
- unit 使用绝对解释器路径和明确配置；不依赖 activate、交互 shell、Windows 路径或当前登录人的 PATH。

### 6.7 07-01 交付物与验收

交付角色实现、单实例保护、调度与采集包装、unit/timer 模板、对应测试和 07-01-SUMMARY.md。

| 编号 | 场景 | 必须观察到 |
| --- | --- | --- |
| A01 | 各角色 --check、功能关闭 | 无网络、无数据库创建、无真实 provider |
| A02 | Bot/Worker 独立运行 | 只有 Bot 建立长连接；Worker 不启动 Scheduler |
| A03 | Worker 停止期间接收消息 | 事件落盘；恢复后可处理，达到上限时明确拒绝 |
| A04 | Bot 在入库前/后异常退出 | 失败未被伪装成功；已落盘事件可恢复 |
| A05 | 两个消费者竞争同一事件 | 原子 claim、有效租约及 owner fencing 生效 |
| A06 | 生成后发送失败再重启 | 复用保存回复，不重复调用 Assistant/Gemini |
| A07 | completed 重复事件 | 不重复发消息；损坏账本不降级重发 |
| A08 | 处理中撤销身份或目标不匹配 | 恢复和投递按现有授权边界拒绝 |
| A09 | Scheduler 与 Worker 并行 | 聊天不被日报 tick 阻塞，无双调度 |
| A10 | 日报分块中断、跨日、错过窗口 | 检查点正确；无默认跨日补发 |
| A11 | 两个采集入口、重复 timer/手工触发 | 采集串行、无来源重复抓取、锁跳过可见 |
| A12 | canonical 写失败但旧输出成功 | 健康检查显示退化，不能报告情报更新正常 |
| A13 | SIGTERM、SIGKILL、自动重启、过新 schema、连接同步策略 | 有界恢复；不误迁移、不清任务；生产写连接 FULL 生效，进程测试不冒充掉电保证 |
| A14 | combined 与拆分角色混用 | 本机角色冲突被拒绝；跨机切换有停旧实例证据 |

## 7. 07-02：目录、秘密、健康检查与资源管理

### 7.1 07-02-A：稳定目录和安装路径

采用以下参考布局；若已有可靠约定可调整，但所有入口必须统一：

| 绝对路径 | 内容与权限原则 |
| --- | --- |
| /opt/trendradar/releases/<release-id>/ | 不可变代码、该版本 venv、必要静态资源；运行用户不可写 |
| /opt/trendradar/current | 指向选定 release 的链接；仅部署身份切换 |
| /etc/trendradar/ | 脱敏业务配置和按角色划分的受限环境文件 |
| /var/lib/trendradar/ | 稳定 WorkingDirectory；运行用户拥有 |
| /var/lib/trendradar/output/intelligence.db | 唯一生产统一库，所有角色显式使用此路径 |
| /var/lib/trendradar/output/news/、rss/ | 现有日期分区兼容数据库 |
| /var/lib/trendradar/output/ai_frontier.db | AI Frontier 兼容数据库 |
| /var/lib/trendradar/output/stories/、security/、ai_frontier/ | 既有报告输出 |
| /var/lib/trendradar/control/ | 维护/恢复暂停状态；不随 release 切换或重启丢失 |
| /run/trendradar/ | 临时角色锁、非敏感运行心跳；开机时按统一规则创建 |
| /var/backups/trendradar/ | 同机一致性快照与 manifest；不能代替异地备份 |
| journald | 默认运行日志，设置容量和保留边界 |

实施前检查所有相对资源：config 文件、frequency_words 等辅助配置、模板、报告资源、AI Frontier 默认路径、日志输出和 MCP 历史路径。

本计划默认以 /var/lib/trendradar 为 WorkingDirectory、通过该 release 的 venv 安装项目包，并显式传递配置。若某入口仍依赖仓库根目录，补齐明确路径或将只读资源打包；不要靠在新 cwd 静默生成默认配置。

特别验证 AI Frontier 的配置参数与主 CONFIG_PATH 的实际关系。给它传入单独的 YAML 不代表统一库配置已自动一致。

运行用户建议为无 sudo 权限的 trendradar；部署身份负责 release 与 unit；备份身份按实际需要分离。避免给运行用户对 /opt、systemd unit 或部署脚本的写权限。

### 7.2 07-02-B：角色化配置与秘密注入

沿用统一 settings 的环境变量覆盖 YAML 逻辑；不在本阶段另建配置系统。

| 角色 | 需要的秘密/配置范围 | 初始不注入 |
| --- | --- | --- |
| Bot | Lark 应用凭据、Bot 身份、允许用户/chat、统一库路径 | Gemini、研究 token、备份凭据 |
| Worker | Lark 发送/媒体凭据、相同授权配置；按范围提供 Gemini | 未验收研究 token、备份凭据 |
| Scheduler | Lark 凭据、日报目标与窗口 | 初始不提供 Gemini 或研究 token |
| 主采集 | 来源所需凭据、NVD 可选 key、明确启用的旧通知配置 | Lark 长连接开关、研究 token |
| AI Frontier | 对应来源与旧通知配置 | Lark 长连接、研究 token |
| 备份/部署 | 独立的传输与存储凭据 | 业务 provider key |

要求：

1. 环境文件由 systemd 注入；当前应用不会自动读取 .env，不能只把文件放在目录里就认为生效。
2. 优先保留现有环境变量契约；文件权限限制为 root 可读或必要的最小组可读。
3. EnvironmentFile 是配置传递方式，不是对同一服务用户的强隔离；不把它描述为秘密保险库。
4. 真实值不进入 YAML、Git、unit 内容、命令行参数、release artifact、健康 JSON 或日志。
5. Bot 与 Worker 使用相同的非秘密授权配置及其摘要；不一致时禁止启动或标记 unhealthy。
6. 凭据变更有明确的验证和受影响服务重启步骤；不自动输出新值。
7. 旧 FEISHU_* 别名维持兼容，新增文档优先 LARK_*。
8. 采集若暂不开启 Gemini，既关闭相关功能也不注入 key，并用模拟调用计数验证无模型调用。
9. 新部署的首份模板保持 LARK_ENABLED=false、日报关闭、研究关闭，按验收逐步打开；不要修改项目现有全局默认来制造部署专用行为。
10. 日报目标和允许用户均为环境特定值；禁止把 UAT 目标或示例身份当生产默认值。

### 7.3 07-02-C：健康检查必须反映工作是否前进

建议新增独立 ops health 命令，提供人读摘要和 --json。这是待实现入口，与原来的 --check 区分。

| 检查面 | 最少字段 | 不能误判的情况 |
| --- | --- | --- |
| 版本/路径 | release ID、schema、配置摘要、解析后的 DB 路径 | Bot 和 Worker 实际打开两份库 |
| Bot | 角色存活、连接状态、最近连接/断开、冷却期限 | 进程存在但长期断开 |
| Worker | 心跳、最近一次轮询、最近处理进展、当前任务年龄 | 空闲无消息是健康；死线程不是健康 |
| 入站队列 | pending、processing、最老任务等待时间、已过期租约、终止失败数 | 进程健康但队列不再前进 |
| 出站 | 可重试回复数、最老发送等待、最近错误类别 | 生成成功但发送一直失败 |
| Scheduler | 最近 tick、当前/最近窗口、分块进度、投递结果 | timer active 但 tick 每次失败 |
| 数据 | 每个启用源的最近成功/退化运行、Story 更新、新鲜度 | 合法零新增与采集失败必须区分 |
| 数据库/磁盘 | 文件大小、WAL、磁盘/inode、只读查询结果 | 丢失 DB 时不得自动创建空库 |
| 备份 | 最近本机/异地成功时间、最近恢复演练结果 | 上传失败却只报告快照创建成功 |
| 可选研究 | disabled / unavailable / verified 及工具版本 | 关闭能力不是核心故障；已启用缺工具是退化 |

设计原则：

- 默认只读、无网络，不调用 Gemini、不发送 Lark、不自动迁移、不修复数据库。
- 使用明确的只读连接，路径不存在就失败；不要经会隐式建库的存储构造器读取健康。
- 心跳只保存非敏感字段；带 role、PID/启动标识、release ID 和时间，过期文件不能代表存活。
- “心跳活着”和“业务有进展”分开；有界慢任务可解释，超过任务总预算才判停滞。
- 输出状态建议 healthy、degraded、unhealthy、disabled、maintenance；定义稳定退出码。
- 不要在每分钟健康检查中跑全库 integrity_check；完整检查放在备份/恢复验证。
- 可选网络诊断单独使用显式开关，声明可能产生网络调用；不能藏在基础健康检查内。
- 初版使用 journald、健康 JSON 和有限频率摘要；不新增 Prometheus/Grafana 维护负担。

建议初始阈值，均需在目标机器校准：

| 信号 | 初始阈值建议 | 处理 |
| --- | --- | --- |
| 空闲 Worker 心跳 | 超过 60 秒未更新 | unhealthy；保留诊断后恢复 |
| 队列持续无进展 | 超过有效单任务总预算 + 租约恢复余量 | 告警，查 DB/worker/provider |
| 采集新鲜度 | 连续错过 2 个计划周期 | degraded；安全源还保留既有 stale_after_hours 语义 |
| 异地备份 | 超过约定 RPO 未成功 | degraded；再次超窗提升严重度 |
| 磁盘/inode | 使用率接近 80% 预警、90% 严重 | 清理可重建产物，保护数据库及工作账本 |
| Scheduler | 窗口内应运行却未 tick，或过窗未完成 | 明确 missed/failed，不能显示日报成功 |

告警先写本地和 CI 可读状态。向用户发送运维告警时使用已授权的目标并限频；不能让 Lark 故障的唯一告警也依赖 Lark。

### 7.4 07-02-D：资源预算和子进程约束

资源数值属于设计起点，必须以目标 VPS 实测修订，不能描述为当前消耗。

- 初始一个 Worker、一个研究任务；主采集和 AI Frontier 串行。
- 把 Bot、Worker、Scheduler、采集及其子进程放入明确的 systemd slice，统计整体资源。
- 在确认为约 1.87 GB 内存且无其他重要负载时，可从整体 MemoryHigh 约 1 GiB、MemoryMax 约 1.25 GiB 的候选配置测起；须检查实际 MemTotal 并保留系统余量。
- 每个 unit 的 MemoryMax、TasksMax、文件描述符和 CPU 权重按实测分配，不能把各自上限都设为全机上限。
- 限制总并发、媒体大小、上下文、来源结果、CLI 输出与 subprocess 生命周期；不要仅靠 OOM 杀进程。
- 收集空闲、单聊天、图片、采集与聊天重叠、日报与聊天重叠、备份与采集重叠的峰值。
- 资源紧张时先关闭可选润色、降低来源并发和大结果，再评估容量；不默认增加 Worker。
- 研究工具固定安装版本，禁止每次请求通过 npx 等方式临时下载最新包。
- 核对实际安装的 mcporter/Node、gh、yt-dlp 版本与运行时要求；不能沿用开发机 Node 版本作兼容证明。
- 任何限制导致的退出必须留下分类和恢复证据，不允许不断 OOM 重启后标记“稳定”。

cgroup 设置按目标 systemd 版本支持范围实现，并通过现场查询证明生效；不能只提交带资源字段的模板。

### 7.5 07-02-E：日志、保留与 systemd 限权

1. 默认标准输出进入 journald，日志含角色、release、脱敏事件关联 ID、阶段、耗时和错误类别。
2. 不记录用户完整正文、图片、完整模型响应、令牌、签名 URL 或原始 SDK payload。
3. 设置日志容量和保留；如目标支持独立日志 namespace 可使用，否则说明全机 journald 配额对其他服务的影响，不能擅自更改全机策略。
4. 文件日志若仍存在，使用明确轮转；同一路径不能同时依赖两套无边界日志机制。
5. 初始报告和普通日志可采用约 14 天保留作为建议；实际保留需与已有用户设置协调。
6. 不在 Phase 7 默认删除内容历史、会话、completed 去重记录或日报检查点。终态清理必须保留足够去重信息。
7. pending、processing、待发送回复及其有效租约永远不按普通日志 TTL 删除。
8. 清理仅处理允许目录和明确可再生产物；先给出清单，不扫描删除整个 output 或 test/runtime。
9. unit 候选限权包括 NoNewPrivileges、ProtectSystem、ProtectHome、PrivateTmp、UMask 及有限写路径，按实际运行逐项验证。[S6]
10. 临时目录要允许受控 HTTP/CLI 子进程工作；共享锁不放 PrivateTmp 中。Linux Node 工具可能受额外沙箱限制，不一刀切加入未经验证的 syscall 或内存执行限制。
11. 正常网络使用出站 DNS/HTTPS/WSS；不为健康检查开放新的公网端口。
12. 不让自动健康恢复变成重启风暴；数据库损坏、版本不兼容、缺秘密属于人工可诊断阻塞。

### 7.6 07-02 验收

| 编号 | 场景 | 必须观察到 |
| --- | --- | --- |
| B01 | 非仓库 cwd、重启、release 切换 | 所有入口仍读写同一稳定状态目录 |
| B02 | 缺库、路径拼错、权限不足 | 拒绝启动/报告异常，不新建空库掩盖问题 |
| B03 | 角色环境与配置摘要 | 只注入所需秘密，授权配置一致 |
| B04 | 关闭模式与研究缺工具 | 关闭项无网络；核心能力可用，状态分类准确 |
| B05 | Worker 线程/循环停滞 | 心跳或进展检查能识别，不能仅以 PID 判健康 |
| B06 | 全部来源失败、合法零新增、写库失败 | freshness 和业务状态分别准确 |
| B07 | 日报与回复发送持续失败 | 投递积压可见，模型成功不等于业务成功 |
| B08 | 日志及错误信息审查 | 无秘密、原始正文/图片泄露；日志可轮转 |
| B09 | 权限与限权运行 | 服务用户不能改 release/unit，必要临时文件仍可用 |
| B10 | 目标负载组合 | 记录 cgroup/内存/CPU/任务数峰值，无未解释 OOM 或泄漏 |
| B11 | 磁盘不足与保留清理 | 明确退化，保护数据库、WAL 和有效任务 |
| B12 | 备份超期、恢复暂停状态 | 健康准确显示，不自动发消息或解除暂停 |

## 8. 07-03：可复现构建、CI、备份和发布

### 8.1 07-03-A：固定真正的部署版本

交付一份 release manifest，至少含：

- 仓库 commit、构建时间、artifact 校验摘要、是否存在未提交差异。
- 包版本与 release ID。当前 pyproject 的版本号仍为 4.6.0，不把规划名称 v5.0 当作已经发布的版本。
- 目标 OS/架构、Python、pip、实际 SQLite 版本/补丁证据。
- 直接依赖与解析后的完整安装清单、锁文件/约束文件校验摘要。
- lark-oapi 固定版本、可选研究 CLI 及其运行时版本。
- 可读写 schema 范围、迁移起止版本、配置模板版本。
- 通过的测试、部署范围、默认关闭项、对应备份 ID 和上一可回退 release。

保留前一轮统一依赖成果；以明确的单一事实来源生成或校验另一安装清单，禁止再次出现 requirements 与包声明漂移。

初版生产选择一个目标 Python minor 版本并固定；CI 同时覆盖声明的最低 Python 兼容性，或明确缩小支持声明。不能以 Windows 开发环境代替 Linux 安装证据。

### 8.2 07-03-B：产物和资源可用性

建议产出版本化发行包，包含 wheel、锁定的依赖清单/必要 wheelhouse、只读资源、配置示例、unit、部署工具与 manifest。

- 同一个经过验证的 artifact 用于 VPS 安装，不能部署时再 git pull 最新分支或无约束 pip install。
- 若依赖含平台相关 wheel，构建/收集必须匹配实际目标架构；不能把 x86 的产物直接用于 ARM。
- venv 在最终 release 目录内创建，不能构建后移动一个带绝对 shebang 的 venv。
- 验证 sdist/wheel 中实际包含运行所需包和资源；主入口不得悄悄从开发目录读取遗漏文件。
- 不把运行数据库、.env、用户消息、备份解密密钥、测试沙箱或本机绝对路径装入发行包。
- 安装过程不启动 Bot，不调用外部 provider；检查通过后才进入切换流程。

### 8.3 07-03-C：CI 的必要门禁

按现有项目要求执行：

1. 配置和依赖声明一致性检查。
2. 针对本阶段角色/恢复/路径/备份的测试。
3. 仓库要求的全量 pytest；记录实际数量、warning、skip。
4. 变更 Python 路径 Ruff、必要编译/导入检查；不把全仓历史 Ruff 债务混入本阶段。
5. 干净安装、pip check，以及旧入口/公开 Lark 入口的离线检查。
6. 目标 Linux 上 unit 语法验证；角色生命周期验证必须在具备实际 systemd 的环境完成，纯文本检查不能替代。
7. schema 旧版本副本升级、重复迁移、异常中断、过新版本拒绝。
8. 构建产物资源检查、秘密扫描、artifact 摘要与 provenance 记录。
9. PR CI 不接触生产秘密，不运行真实消息、模型或 provider 验收。

GitHub Actions 引用固定经核实的完整 commit SHA；作业权限最小化。不能通过执行不可信 PR 内容的高权限工作流暴露部署凭据。[S8]

新测试验证真实风险，不以大量断言模板字符串代替跨进程行为和恢复测试。

### 8.4 07-03-D：工作流职责

建议新增或调整以下逻辑工作流，名称可按仓库风格统一：

| 工作流 | 触发 | 作用 |
| --- | --- | --- |
| CI | PR / 可信分支更新 | 离线测试、检查、构建和上传候选产物 |
| Release | 明确的版本/手动触发 | 从已通过的确定 commit 产出不可变发行包 |
| Deploy | 明确的部署触发 | 将指定 artifact 部署到指定环境 |
| Backup verification/control | 定时或手动 | 触发/核查 VPS 备份与异地保存，记录恢复演练状态 |

Actions 不维持 Lark 长连接，不持有一份可被误当生产库的活动数据库。

备份必须能在 GitHub 调度暂时失败时由 VPS timer 继续执行；Actions 的责任是提供远程控制、结果核查和证据，不能成为唯一的定时可靠性来源。

备份文件默认不作为普通 CI artifact 公开或无边界保留；CI 只保存脱敏 manifest 与验证结果。异地存储按受限权限和加密方案落实。

### 8.5 07-03-E：受控部署步骤

部署脚本的顺序必须固定，可重入，且每步有状态记录：

1. 验证目标环境、artifact 来自允许的仓库/commit、摘要和目标平台。
2. 获得全机发布/迁移维护锁；GitHub concurrency 也使用同一生产组，并禁止中断正在切换的发布。
3. 将新 release 安装到独立最终目录；离线检查通过，此时不切 current。
4. 进入维护模式：停新调度，停止新入站，有限等待在途任务，停止全部会写相关库的角色及批处理。
5. 制作发布前一致性快照，完成校验；记录队列、schema 和旧 release。
6. 在副本验证迁移，再对正式库做一次有锁迁移；不由各个服务竞争执行。
7. 原子切换 current，并部署匹配的配置/unit；配置变化同样需保留可恢复版本。
8. 先做只读 schema/路径检查，再启动 Worker、Bot，最后启用 Scheduler 和采集 timer。
9. 验证版本一致、路径一致、单实例、队列可推进、采集可更新；真实发送使用已授权的验收范围。
10. 写入发布结果与对应备份 ID；失败进入明确的回退路径，不继续标记完成。

GitHub environment 与 concurrency 是两个不同控制面，必须分别配置；另一个 workflow 若未使用同一 concurrency 组，不会自动被环境名称串行化。[S7]

同时保留 VPS 端锁，防止手工部署绕过 Actions 并发限制。不要依赖默认“只留一个 pending”的队列规则保证每个部署请求都执行。

首次版本建议显式触发部署，避免普通 push 自动重启生产；这是部署机制的设计，实际操作授权继续以用户当前指令为准。

### 8.6 07-03-F：发布连接与权限

- 固定目标主机与 host key，禁止 StrictHostKeyChecking=no。
- 部署身份只具有必要目录和服务控制权限；不授予任意 root shell 作为默认发布接口。
- 如需受限 sudo，调用的脚本及其父目录必须由管理员控制，参数校验不得允许任意路径/命令。
- 发布、备份、业务 provider 凭据分开；测试 job 不继承生产 secrets。
- 不因 GitHub-hosted runner IP 变化而开放数据库或取消 SSH 身份验证。
- 若 runner 无法访问 VPS，先产出可验证 release，使用已授权的固定手工部署步骤完成；将远程自动发布标记待完成，不能虚报 DEPL-03。
- 不在这台小型生产 VPS 上默认增设能执行任意 PR 的 self-hosted runner。
- 正常业务停机不触发部署回滚；只有发布校验失败进入明确流程。

### 8.7 07-03-G：区分功能回退和版本回退

| 场景 | 处理 |
| --- | --- |
| 单项研究 provider 失败 | 关闭该能力，保留基础 Assistant 和数据库 |
| Gemini 不可用 | 沿用确定性回答/日报降级，不改 Story 身份或事实 |
| Bot 需要暂停 | 停 Bot 或关闭对应入口，保留账本和其他采集 |
| 同 schema 且兼容的坏 release | 停服务，切回已验证旧 artifact/config，检查后重启 |
| 新 schema 与旧代码不兼容 | 停写；保留失败后的状态快照；执行已验证的数据恢复方案 |
| 数据损坏/主机丢失 | 按 07-04 灾难恢复流程，不等同于普通代码回退 |

不能手工降低 PRAGMA user_version，不能以“新增表而已”为由声称旧代码兼容。

数据库回退可能丢失备份之后的数据。脚本必须明确列出备份时间、受影响窗口和保留的当前副本；不得静默覆盖。生产恢复不设计为无限自动重试覆盖数据库。

### 8.8 07-03 验收

| 编号 | 场景 | 必须观察到 |
| --- | --- | --- |
| C01 | 依赖声明与干净安装 | 两种支持安装入口能力一致；pip check 通过 |
| C02 | 实际发行产物在新 Linux 环境安装 | 无开发目录依赖，资源和旧入口可用 |
| C03 | PR CI 与生产秘密边界 | 离线执行；无生产消息、模型调用或凭据 |
| C04 | artifact 摘要错误/目标平台不符 | 部署拒绝，当前服务不受影响 |
| C05 | 两个部署/手工部署竞争 | Actions 与 VPS 锁均生效，无中途互相取消 |
| C06 | 构建/安装失败 | current 不变，原服务继续可用 |
| C07 | 发布前备份失败 | 不开始数据库迁移和正式切换 |
| C08 | 迁移中断/版本过新 | 原因可诊断，未丢数据，不并发自动修复 |
| C09 | 切换后健康检查失败 | 按 schema 兼容性走明确回退，无盲目覆盖 |
| C10 | artifact/日志/manifest 审查 | 不含秘密、运行库或 UAT 数据 |
| C11 | Actions 暂不可用 | VPS 备份仍运行，结果后续可核查 |
| C12 | 旧 Actions 与 VPS 调度交接 | 同范围采集和通知仅一处执行，保留回退记录 |

## 9. 07-04：部署手册、备份恢复与真实运行验收

### 9.1 07-04-A：备份范围与目标

| 数据 | 是否备份 | 说明 |
| --- | --- | --- |
| intelligence.db | 必须 | 包含内容、Story、会话、事件和日报账本 |
| news/rss 日期库、ai_frontier.db | 必须覆盖仍需保留的历史 | 旧报告和 MCP 仍依赖它们 |
| 非秘密配置、来源清单、配置版本 | 必须 | 与发布版本关联，不能只备份代码 |
| release manifest、依赖锁定与 unit 版本 | 必须 | 支持找到正确恢复程序 |
| 维护/恢复状态和任务状态摘要 | 必须记录 | 恢复时不能无条件继承“可发送”状态 |
| HTML 报告等可重建内容 | 按成本选择 | 文档明确恢复还是重建 |
| 环境秘密/备份解密材料 | 独立受控保管 | 不混入普通日志、CI artifact 或公开备份 |
| 临时文件、缓存、图片中间数据 | 默认不备份 | 不将它们当作恢复必需项 |

建议初始服务目标：

- 本机故障误操作：每小时一致性快照，保留最近约 24 个小时点。
- 主机丢失：每天至少一份已验证异地副本；候选 RPO 为 24 小时。
- 异地保留候选：14 个日点、4 个周点，并保留最近两次发布前快照。
- 候选 RTO 为 30–60 分钟，但只有计时恢复演练才可以确认。
- 以上是待落实的运行目标，不是当前保证。磁盘和历史库大小决定最终保留数量。

24 小时异地 RPO 意味着主机丢失后可能无法恢复最近一天的内容、会话和任务；不能把单机“已落盘”描述为抵御整机丢失的零数据损失。如果需要更短窗口，提高异地频率后实测，不靠文档承诺。

备份客户端优先复用用户已有且通过恢复验证的方案；若尚无方案，默认采用固定版本 restic，将完成后的 SQLite 快照集发送到受限的 S3 兼容或 SFTP 仓库。restic 支持这些后端和独立仓库口令；口令需在 VPS 之外有恢复途径。[S9] 不额外在小型 VPS 上部署一个对象存储服务。

### 9.2 07-04-B：一致性快照算法

1. 获得备份锁，并检查维护状态、磁盘余量和目标权限。
2. 用 SQLite Online Backup API 或经验证的等价方式，把每个数据库写入新的临时快照文件。[S1]
3. 设置全程截止时间和有限 busy 重试；备份不能因持续写入无限不返回。
4. 关闭快照连接，验证 integrity_check、foreign_key_check、schema 和关键表。
5. 检查 Story/会话/事件/日报关键状态能被匹配版本读取。
6. 写 manifest：备份 ID、每库开始/完成时间、大小、校验和、release/schema/config 摘要、检查结果。
7. 全部必需文件成功后才把 staging 标为完整快照；部分失败不能更新 latest-success。
8. 向异地传输完成并核查后，单独更新 remote-success；本机成功不等于异地成功。
9. 保留策略仅删除已被明确策略覆盖的旧备份；先有足够已验证的新副本。
10. 失败时保留上一份可用快照，记录原因和下次尝试，不输出秘密。

禁止直接让 cp、rsync、压缩工具或 restic 扫描活动 SQLite 主文件来充当一致性快照。WAL 是持久状态的一部分，孤立复制 .db 可能漏掉已提交事务；也不能分别在不同瞬间拷贝 .db/.wal/.shm 后宣称得到一致备份。[S2]

多个独立数据库各自的在线快照不是同一瞬间的跨库事务。普通备份在 manifest 中标明各库时间；发布前/完整搬迁需要一致的业务停写窗口，覆盖全部写入入口后再制作快照。

### 9.3 07-04-C：恢复演练与生产恢复

恢复命令默认恢复到新的隔离目录，不能默认覆盖当前生产目录。

1. 明确恢复目标、备份时间、预计数据缺口和对应 release/schema。
2. 验证异地取回、解密、manifest 和所有文件校验和。
3. 在隔离目录内做完整性、外键、schema 与应用读取检查。
4. 隔离阶段不提供真实 provider 凭据，关闭 Bot、日报和所有对外发送；测试替身不与生产进程争用应用身份。
5. 抽查内容/Story/来源、历史查询、完整会话轮次和各类事件/日报状态。
6. 以临时模拟任务验证可写和可恢复，禁止向真实旧用户消息补发。
7. 若正式恢复，先停止全部写者并保留故障后现有状态的完整副本。
8. 安装匹配 release/config，放入恢复库，进入持久化 restore-guard 状态。
9. Worker 和 Scheduler 在 guard 下不得对外发送；Bot 初始也不连接，先完成状态核对。
10. 将从旧备份恢复的非终态回复、处理中事件及未确定的日报窗口隔离；不要全表改成 pending 或 completed。
    首次重新接入时还要记录明确的恢复切换时间：平台重新投来的旧消息，即使其 event_id 不在备份中，也不能自动当作新消息执行；结合已验证的事件创建时间隔离，时间缺失或结果未知则待核对。只扫描备份里的 pending 行不足以覆盖备份之后曾成功发送的事件。
11. 明确哪些可重新处理、哪些已在平台发送、哪些结果未知。按单条/单批有界恢复，保留操作记录。
12. 核对新配置的授权及目标，解除 guard 后先恢复新消息路径，再启用采集和日报。
13. 记录实际恢复时间、恢复到的数据时间点、丢失窗口与人工处理范围。

restore-guard 是本阶段需实现的维护能力，可采用状态目录中的持久标记和受控命令；不得只依赖重启就丢失的内存变量或 /run 文件。它应区分“检查恢复副本”“接受新工作”“处理恢复遗留工作”“允许对外发送”。

旧备份可能缺少备份后已经成功发送的记录，平台 UUID 去重期限也不能假定永久有效。因此，恢复演练除了“数据库能打开”，必须验证“不自动重复发旧消息”。历史成功窗口与当前窗口结果未知时，同样不能直接重跑日报。

### 9.4 07-04-D：首次部署分步启用

| 步骤 | 开启范围 | 必须完成的检查 |
| --- | --- | --- |
| D0 | 仅安装、配置和离线检查 | 正确路径、依赖、schema、资源和秘密注入 |
| D1 | 采集与统一数据 | 真实来源更新、Story/旧报告可读、无双重通知 |
| D2 | Bot + Worker，本地确定性问答 | 旧 Bot 已停止，白名单/群 @/消息恢复正常 |
| D3 | Chat Gemini | 真实问答及错误降级，引用保持正确、费用和耗时可见 |
| D4 | 日报 Scheduler | C4 实际接收、无重复、分块恢复、时区窗口正确 |
| D5 | 逐项研究能力 | 仅开启完成真实契约与资源验收的能力 |

D3 在已有有效真实证据的同一版本/环境边界内可复用相应结果；平台和目标 VPS 变化的部分需要补证据。

C3 断网与冷却验收应针对 Bot 流程或测试网络边界进行，保留管理连接和恢复方式，不能随意切断整台 VPS 的 SSH。验证失败计数、冷却期限、稳定连接重置、恢复后队列和任务状态。

### 9.5 07-04-E：连续运行与运维手册

Phase 7 建议至少完成连续 48 小时，并覆盖两个实际配置的日报窗口、正常采集周期、一次可控重启、一次投递失败恢复和一次异地恢复演练。仅等待 48 小时不构成通过。

必须记录：

- 运行版本、来源配置、消息量、采集次数和实际日报接收。
- pending 等待、任务耗时、失败与恢复、资源峰值和是否出现 OOM。
- 对外网络失败与本地故障的区别，降级是否符合范围。
- 定时任务是否持续运行，数据是否新鲜，备份是否按时到达异地。
- 发现的问题、修复版本和需要重验的具体场景。

docs/deployment.md 至少包括：

1. 支持的环境和预检方法。
2. 服务用户、目录、安装、配置和秘密注入。
3. 各角色启停、日志查询、健康解释、timer 状态和维护模式。
4. 采集/通知所有权切换，以及 Windows UAT 到 VPS 的单实例交接。
5. 发布、迁移、同 schema 回退和不兼容 schema 恢复。
6. 备份范围、频率、保留、异地验证、口令恢复与恢复演练。
7. 常见故障：缺库、锁、权限、网络、队列停滞、发送失败、磁盘满、版本不符。
8. 可选研究的安装、逐项启用和关闭。
9. 当前未验证项、用户接受的测试例外、已知保证边界。

手册里的每条生产命令必须与实际脚本和 unit 对应，区分只读、重启、联网、迁移和覆盖恢复操作。不得出现尚未实现却标为可直接运行的命令。

### 9.6 07-04 验收

| 编号 | 场景 | 必须观察到 |
| --- | --- | --- |
| D01 | 活动库持续写入时备份 | 快照完整可读，无裸文件复制，业务延迟在预算内 |
| D02 | 磁盘满、备份中断、上传失败 | 不覆盖上一可用备份，成功状态准确 |
| D03 | 从异地恢复到隔离目录 | 摘要、完整性、外键、schema 和应用读取均通过 |
| D04 | 恢复旧 pending/回复/日报记录 | guard 默认生效，无自动旧消息外发 |
| D05 | 恢复后权限和新目标变更 | 不跨 principal/chat 发送历史内容 |
| D06 | 一次升级和一次回退演练 | 记录 artifact、备份、schema、耗时和数据变化 |
| D07 | VPS/服务重启 | 状态路径稳定、角色唯一、定时任务恢复 |
| D08 | 真实断网/冷却恢复 C3 | 有界重连、冷却、稳定后恢复，管理通道可用 |
| D09 | 真实日报 C4 | 目标接收确认及投递检查点一致，无正常重复 |
| D10 | 真实采集至问答/日报 | 新数据确实进入 VPS 统一库并可被引用 |
| D11 | 连续运行及重叠负载 | 覆盖关键场景，无未解释积压、OOM 或子进程残留 |
| D12 | 按手册独立复现 | 操作步骤与实现一致，RPO/RTO 有实测或明确未达标 |

## 10. 配置与命令契约清单

实施者必须逐项核对现有名称；新增参数统一记录，不能在 unit 中使用应用尚未读取的“假配置”。

| 配置/接口 | 当前已有或拟新增 | 本阶段规则 |
| --- | --- | --- |
| CONFIG_PATH、现有 --config | 已有，但各入口需核对 | 指向明确的环境配置 |
| INTELLIGENCE_DB_PATH | 已有 | 所有角色指向唯一生产统一库 |
| INTELLIGENCE_ENABLED | 已有 | false 保持旧采集回退；Lark 不应绕过此开关 |
| LARK_ENABLED | 已有 | 默认关闭，按部署阶段启用 |
| LARK_APP_ID / LARK_APP_SECRET / LARK_BOT_ID | 已有 | 环境秘密/身份配置，不写文档真实值 |
| LARK_IDENTITY_FIELDS、允许 chat 配置 | 已有 | Bot、Worker 一致，恢复时重新授权 |
| LARK_DELIVERY_ENABLED / TARGET / TIME / END | 已有 | 明确窗口，Scheduler 单独启用 |
| GEMINI_ENABLED / GEMINI_API_KEY | 已有 | 按角色注入，不因一个角色启用而全局提供 |
| INTELLIGENCE_RESEARCH_ENABLED / CAPABILITIES | 已有 | 默认 false；只开启验收通过的能力 |
| INTELLIGENCE_RESEARCH_GITHUB_TOKEN | 已有修复 | 仅 GitHub 能力最小注入 |
| --role | 拟新增 | 保留旧 combined，角色行为互斥 |
| ops preflight / health / migrate | 拟新增逻辑接口 | 配置检查、只读健康和写入迁移明确分开 |
| ops backup / restore | 拟新增逻辑接口 | 默认不覆盖生产；恢复触发持久 guard |
| maintenance / restore-guard | 拟新增 | 重启和 release 切换后仍有效 |
| 角色锁/采集锁/维护锁 | 拟新增或复用合适实现 | 明确作用范围、顺序、超时和冲突状态 |
| SQLite 连接同步策略 | 当前硬编码 NORMAL；生产策略待实现 | 生产全部写连接 FULL，角色自报实际值并验证延迟 |

不用为了部署而更改当前 schema v6；若新持久字段确有必要，采用真实的下一迁移版本，补旧版本副本迁移与回退证据。不能硬写“Phase 7 必须升到 schema v7”。

## 11. 与 Phase 5、6、8 的衔接

### 11.1 Phase 5 的剩余真实验收

- C3：真实断网/冷却/恢复，纳入 D08。
- C4：日报目标实际接收确认，纳入 D09。
- 群聊未 @ 不响应已有真实记录可复用，拆分后仍需离线回归。
- 非白名单其他真人账号的验收曾由用户主动跳过：保留为覆盖例外，不重新强制索要。
- 禁用模式继续作为配置回退和可选功能隔离门槛，不能删除。
- 平台重复事件和结果未知窗口的真实证据能取得则补齐；不能由本地 mock 推断平台永久去重。

### 11.2 Phase 6 的能力启用矩阵

| 能力 | 基础上线时 | 开启前证据 |
| --- | --- | --- |
| 本地历史检索与引用 | 开启 | 同一 VPS 数据库可读、引用与权限通过 |
| GitHub 研究 | 关闭 | 固定 gh 版本、专用认证、公共查询成功、错误分类 |
| Web / Reddit 研究 | 关闭 | 固定 mcporter/上游工具、真实非空及错误输出解析 |
| 网页读取 | 关闭 | URL 边界、完整请求截止时间、大小上限、目标网络 |
| 视频/字幕 | 关闭 | 工具版本、实际站点可用性、输出及资源边界 |

全部研究关闭时 DEPL-02 应展示 disabled 状态；工具安装和能力状态可见，但不能把“尚未真实验收”写成“已生产可用”。

### 11.3 Phase 8 的职责

本阶段的运行、安全边界和恢复测试必须随实现完成，不能推迟到 Phase 8。

Phase 8 继续负责完整业务链路、各模块覆盖缺口、旧 91 项 AI Frontier 等兼容要求、引用质量、Story 误合并/漏合并和排序效果，以及 7–14 天实际使用观察。不因 Phase 7 验收通过就宣布 v5.0 总体完成。

Phase 7 交接时提供测试资产和实际结果，Phase 8 补缺口，不机械重复全部部署演练。

## 12. 主要失败模式与处置

| 风险 | 优先级 | 必须采取的措施 |
| --- | --- | --- |
| 两个 unit 都启动旧 combined | 阻塞 | 显式角色、锁、只有一个 WebSocket |
| Bot 成功但无新数据 | 阻塞 | VPS 采集、统一路径、freshness 和查询实证 |
| 不同 cwd 写出第二份库 | 阻塞 | 绝对路径、资源打包、缺库拒绝 |
| SQLite 多进程竞态/运行库版本未知 | 阻塞 | 原子 claim、短事务、补丁核对、真实多进程测试 |
| 把 NORMAL 提交当作掉电后绝不丢失 | 阻塞 | 生产写连接 FULL，区分进程崩溃、掉电和整机丢失保证 |
| 活跃库只复制 .db 或旧快照自动重发 | 阻塞 | SQLite 一致性快照、恢复 guard 与状态核对 |
| 老代码读不了新 schema | 阻塞 | 兼容矩阵、发布前快照、分离版本回退与数据恢复 |
| Actions/VPS 同时采集和通知 | 高 | 明确执行方、停旧任务、保留切换记录 |
| 进程存活但队列停滞 | 高 | 业务进展、心跳、任务截止时间和有限恢复 |
| 小内存下采集/研究并发失控 | 高 | 串行批处理、有限并发、子进程约束、重叠负载实测 |
| provider 未验证却整体启用 | 高 | 能力白名单逐项放行 |
| 只有同机备份 | 高 | 异地保存并实际取回恢复 |
| 部署成功但文档未对齐 | 中 | 逐条执行手册，证据与 release 绑定 |

这里的“阻塞”指相关上线门槛；不阻止在临时环境中继续实现其他工作。

## 13. 文件交付结构与接手顺序

以下为建议的新文件位置，均相对于项目根目录；允许按现有代码风格合并，但职责不得遗漏。

| 路径 | 交付内容 |
| --- | --- |
| .planning/phases/07-deployment/07-CONTEXT.md | 固定决策、范围和待确认环境 |
| 同目录 07-RESEARCH.md | 当前入口、版本要求与外部契约 |
| 同目录 07-01-PLAN.md 至 07-04-PLAN.md | 从本文四个工作包拆出可执行任务 |
| 同目录 07-01-SUMMARY.md 至 07-04-SUMMARY.md | 实际改动、命令、结果和限制 |
| 同目录 07-VERIFICATION.md | DEPL-01 至 DEPL-05 证据映射 |
| deploy/systemd/ | 角色服务、采集/日报/备份/健康 timer、slice、必要 tmpfiles 配置 |
| deploy/config/ | 脱敏配置和角色环境示例 |
| scripts/deploy/ | preflight、安装、发布、回退的受控入口 |
| 适合仓库分层的 Python ops 模块 | health、快照、恢复、维护状态等可测试实现 |
| tests/deployment/ 及原有受影响测试目录 | 本阶段有意义的回归与集成测试 |
| .github/workflows/ | CI、release、deploy、backup control/verification |
| docs/deployment.md | 真实可执行运维手册 |
| docs/phase7-acceptance.md | 脱敏现场验收、试运行、资源和恢复报告 |
| .planning/STATE.md、ROADMAP.md、REQUIREMENTS.md、docs/README.md | 同步真实进度和导航 |

共享 /run/trendradar 目录的生命周期要统一管理，例如由 tmpfiles 配置创建；不能让某个 service 停止时删除其他角色正在使用的锁和心跳目录。

建议每次交付聚焦一个工作包或其明确子任务。即使由多个 agent 接手，也只能有一个执行者负责同一数据库迁移、真实 Bot 切换和生产发布；本计划不要求额外并行代理。

## 14. 验证证据与完成定义

### 14.1 每项证据的最小格式

~~~text
用例编号：
对应需求/工作包：
环境与 release/commit：
配置范围（脱敏）：
数据库来源及 schema：
实际执行命令：
实际观察结果与退出码：
通过/失败/跳过/未执行：
日志或报告位置：
真实外部调用及授权范围：
剩余限制与后续项：
~~~

本文共定义 50 个验收场景：A01–A14、B01–B12、C01–C12、D01–D12。场景不等于必须新建 50 个测试函数；复用已有测试和合并集成场景即可，但每个验收目标必须有对应证据。

建议验证顺序：针对性模拟测试 → Linux 跨进程测试 → 全量回归与干净安装 → systemd 现场检查 → 临时副本迁移/恢复 → 授权范围内真实业务 → 连续运行。

### 14.2 工作包关闭表

| 工作包 | 实现状态 | 离线结果 | Linux/systemd 结果 | 真实验收 | 证据位置 |
| --- | --- | --- | --- | --- | --- |
| 07-01 | 离线通过 | 角色边界、持久消费、重复事件和退出路径已测 | 未执行；无目标 systemd 证据 | 未执行 | `.planning/phases/07-deployment/07-01-SUMMARY.md`、`07-VERIFICATION.md` |
| 07-02 | 离线通过 | 配置模板、健康检查、锁、心跳和资源边界已测 | 未执行；资源数值待 VPS 实测 | 未执行 | `.planning/phases/07-deployment/07-02-SUMMARY.md`、`07-VERIFICATION.md` |
| 07-03 | 离线通过 | 构建、manifest、CI 边界和备份/恢复工具已测 | 未执行；GitHub 与远程备份待验证 | 未执行 | `.planning/phases/07-deployment/07-03-SUMMARY.md`、`07-VERIFICATION.md` |
| 07-04 | 离线就绪 | 部署手册、验收表和恢复保护已完成 | 未执行；无目标环境演练 | 未执行 | `.planning/phases/07-deployment/07-04-SUMMARY.md`、`docs/deployment.md`、`docs/phase7-acceptance.md` |

状态使用：未开始、实施中、离线通过、目标环境通过、真实验收通过、阻塞、经确认不适用。不能用“代码已写完”覆盖真实环境待验收。

### 14.3 Phase 7 完成定义

- [ ] DEPL-01：Bot/Worker 独立受 systemd 管理，单实例、退出和恢复经验证。
- [ ] DEPL-02：Scheduler、SQLite、采集和研究能力状态真实可见，核心数据流闭合。
- [ ] DEPL-03：CI、构建、备份控制/验证和发布流程可执行，版本可追溯。
- [ ] DEPL-04：维护者能按文档完成安装、重启、日志、升级及恢复。
- [ ] DEPL-05：目标 VPS 的组合负载和连续运行通过资源验收。
- [ ] 发布前快照及异地恢复实际通过，RPO/RTO 有记录。
- [ ] C3/C4 完成或明确记录导致上线范围受限的原因；不掩盖待验收。
- [ ] 原有用户接受的测试例外保留，外部研究只在已验收范围内启用。
- [ ] 旧 CLI/AI Frontier/MCP/报告/通知兼容，没有双重调度。
- [ ] Phase 8 接手资料、剩余问题和启用能力清单已更新。

若目标 VPS 还未接入，只能关闭“部署代码和模板已就绪”，不能把四个工作包全部标为真实完成。

## 15. 可直接交给下一位 agent 的执行说明

请先读 AGENTS.md 和本计划，以当前代码及最新实际测试为准，复核 Phase 1–6 修复成果。先完成 W0，随后从 07-01 的角色拆分开始，复用 schema v6 的 EventLedger 和 DeliveryScheduler。

本轮必须保持：Bot 只接收持久化，Worker 只消费/回复，Scheduler 独立定时；VPS 采集写入同一生产 intelligence.db；release 与运行数据分离。不要把两个服务指向旧 combined 入口，不引入外部队列或新的数据库。

按照 07-01 至 07-04 交付代码、unit、测试、CI、备份恢复及操作文档。先在临时数据库和模拟 provider 中验证，再推进到对应授权范围内的真实环境。任何新命令、配置和状态必须在代码中实现并验证，不能只写在文档中。

不要覆盖其他 agent 的未提交改动，不清理 output/ 或 test/runtime，不启动第二个真实 Bot。当前任务范围内完成所有可安全审阅的代码和文档；真实切换、迁移、消息及提交行为遵循用户已明确授权的范围。

最终按工作包报告实际修改、实际命令和结果、未执行项目、可上线能力、必须关闭能力、备份/回退方式及 Phase 8 待办。不要只报告测试数，也不要把离线通过写成生产验证通过。

## 16. 依据与外部来源

项目依据为 2026-10-12 的本地源码和计划文件读取，以及此前同步的实际测试日志。本次编写计划没有修改项目源码、生产数据或远端服务，也没有重新执行项目测试。

- 本地依据：AGENTS.md；.planning/PROJECT.md、ROADMAP.md、REQUIREMENTS.md、STATE.md；codebase/ARCHITECTURE.md；docs/intelligence.md；docs/phase1-6-fix-audit.md。
- 运行依据：trendradar/integrations/feishu/__main__.py、ledger.py、scheduler.py；公开 lark 入口；主采集、AI Frontier 入口和 core/settings.py。
- 发布依据：pyproject.toml、现有 crawler.yml 与 ai-frontier.yml；前一份 Phase 1–6 修复计划。

外部资料核对日期为 2026-10-12；实施时还须匹配目标实际安装版本。S 编号用于本文中的对应技术依据，推荐架构与资源目标属于本项目设计，不是这些来源对本项目的验收结论。

| 编号 | 来源 | 本文使用范围 |
| --- | --- | --- |
| S1 | [SQLite Online Backup API](https://www.sqlite.org/backup.html) | 活动数据库一致性快照、并发与备份边界 |
| S2 | [SQLite WAL](https://www.sqlite.org/wal.html) | 同机存储、WAL 持久状态、多连接与文件复制限制 |
| S3 | [SQLite WAL 文档第 11 节](https://www.sqlite.org/wal.html) | 已公布 WAL-reset 缺陷、修复版本及目标运行库核对 |
| S4 | [systemd 官方 service 文档源码](https://raw.githubusercontent.com/systemd/systemd/main/man/systemd.service.xml) | Restart、TimeoutStopSec、服务生命周期 |
| S5 | [systemd 官方 timer 文档源码](https://raw.githubusercontent.com/systemd/systemd/main/man/systemd.timer.xml) | active unit 行为、Persistent 与 timer 语义 |
| S6 | [systemd 官方 exec 文档源码](https://raw.githubusercontent.com/systemd/systemd/main/man/systemd.exec.xml) | 写路径与进程限权 |
| S7 | [GitHub：Control deployments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments) | environment 与 concurrency 的边界 |
| S8 | [GitHub：Secure use reference](https://docs.github.com/en/actions/reference/security/secure-use) | 固定 action SHA、权限与不可信代码边界 |
| S9 | [restic：Preparing a new repository](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html) | S3/SFTP 后端、仓库口令与恢复依赖 |


