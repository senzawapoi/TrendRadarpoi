# TrendRadarpoi：Phase 7 剩余缺口修复计划

- 版本：1.0；编制日期：2026-10-13（Asia/Shanghai）。
- 项目位置：`C:/Users/DELL/Desktop/TrendRadarpoi-master`。
- 适用对象：接手修改代码、补充测试和更新验收记录的 agent。
- 定位：原 Phase 7 计划的增量修复清单，不重建 Phase 7，不新增 Phase，不重做已完成工作。
- 授权边界：本轮只交付计划；未修改项目、启动服务、发送真实消息、提交 Git、推送、部署或恢复生产数据库。
- 用户最新决定：VPS 的具体登录参数后补。本计划不要求现在提供参数，也不以缺少参数阻塞离线修复。

## 1. 结论与执行目标

目前应修的是“从离线实现到可安全部署之间的剩余闭环”，不是重新实现 Bot/Worker、FULL、健康检查或多库备份。

目标分为两个独立里程碑：

1. **离线修复完成**：发布失败可安全停住，代码与数据回退边界清楚，产物在干净 Linux 环境可运行，备份与健康指标不会误报，相关故障场景有测试。
2. **目标环境验收完成**：用户补充必要配置并授权后，完成 VPS、GitHub 工作流、异地恢复及 Lark 真实链路验收。只有此时才可宣称相应生产门槛通过。

完成第一项不等于完成第二项。Phase 8 的框架、质量指标和离线评估可继续准备；依赖长期运行、真实数据和交付效果的结论仍须等第二项证据。

## 2. 基线、证据与不确定性

### 2.1 本计划采用的事实基线

| 项目 | 已知事实 | 使用限制 |
| --- | --- | --- |
| 源码快照 | 上轮远程只读同步时间约为 2026-10-13 05:24 | 本轮补读设备超时；接手时需核对之后是否有新修改 |
| 最新实际全量测试 | 本地 Codex 日志：2026-10-13 01:11，521 passed、1 个既有 warning | 本轮没有重跑；不得复制成实施后的新结果 |
| 定向测试 | Lark/Feishu 78 passed；角色边界 5 passed；deployment 12 passed | 这些分组有包含关系，不可相加成新的总数 |
| 最新本地任务完成 | 约 2026-10-13 01:12 | 不等于当前仍无新任务或服务进程 |
| Git | main；HEAD 5a427ab；89 条工作区状态记录 | 89 不是文件数；大量实现尚未形成已核实的提交版本 |
| 项目记录 | 28/31 个 roadmap 计划，约 90%；Phase 8 为 0/3 | 这是计划进度，不是生产就绪率 |
| Phase 7 记录 | 四个实现工作包记录为离线就绪，VPS pending | 不应改写为已生产部署 |
| 运行现场 | 未验证当前 Windows 服务进程，也没有新的 VPS 现场证据 | 不假定无进程；不启动第二个 Bot |

本轮直接复核了上轮保留的源码全文，包括安装脚本、部署/CI 工作流、offsite 脚本、health、database、backup、maintenance；角色入口与 unit 部分为保留片段。项目规则来自已同步的 `AGENTS.md`。

本轮尝试补读 `PROJECT.md`、架构文档及 `docs/intelligence.md` 未成功。因此本计划保持已确定架构，只修运维闭环；接手 agent 必须先读取这些文件，不能据本计划擅自扩展业务架构。

### 2.2 已完成成果：保留并回归，不再列为“缺失”

| 已有成果 | 本次处理方式 |
| --- | --- |
| Bot、Worker、Scheduler 角色拆分与现有事件账本 | 复用，不另建 inbox/outbox 或第二套消息状态 |
| 统一库、AI Frontier 的 FULL 配置与 strict existing 模式 | 保留；补运行连接证据与安装链路验证 |
| 显式 database migrate/check | 纳入发布流程；复核锁域与命令语义 |
| 缺失心跳、队列等待、源数据与备份新鲜度检查 | 修正口径和发布就绪判定，不重写整套 health |
| 六份 env example 已取消忽略；CI 分支为 main | 保留；它们仍需随授权后的正确提交进入发布来源 |
| 发布构建、manifest、手动部署工作流、安装脚本 | 在现有实现上补安全闭环 |
| unified、AI、news/rss 发现与多库备份/恢复激活 | 保留；补跨库一致性说明和中断恢复证据 |
| 持久维护 guard 与 recovery cutover | 保留并加强事务归属、故障恢复；不随意清除 |
| 真实资源 slice 已被各服务引用 | 不再要求“新增 slice”；只做 Linux 验证与资源实测 |
| 已修复的 Phase 1–6 消息持久化、投递重试、硬超时等 | 作为必须保持的回归不变量 |

### 2.3 尚不能当作确定缺陷的项目

以下先检查当前文件和运行结果，再决定是否改代码；不得写成“已经证实不能运行”。

- 完整 `requirements.txt` / `pyproject.toml` 是否已安装项目本身；unit 是否统一提供有效导入路径。
- 完整 backup unit 的 `ExecStartPost`、超时、环境文件与 restic 实际接线。
- AI 迁移使用 AI 库路径取得 collector 锁，与运行 collector 的锁域是否一致。
- SIGTERM、子进程退出、SDK 重连、systemd 沙箱权限是否已被完整覆盖。
- 当前依赖是否已有适用于目标 Linux/Python 的锁定文件。
- 当前发布构建器对路径穿越、符号链接、目录数量与重复条目的防护程度。

这些检查如已通过，只补证据，不为了“完成计划”强行增加代码。

## 3. 缺口清单与优先级

P0：接入生产部署前必须修复或提供等效安全机制。  
P1：首次长期运行前必须补齐。  
LIVE：需要真实环境或用户授权才能验收，不冒充离线缺陷。

| 编号 | 优先级 | 证据与问题 | 修复目标 |
| --- | --- | --- | --- |
| P7-R00 | 前置 | 当前工作区未固化，补读部分文件失败 | 复核基线与改动边界 |
| P7-R01 | P0 | 安装脚本仅显式安装 requirements；Linux 包安装与依赖可复现性未验收 | 同一产物离开源码目录也能运行 |
| P7-R02 | P0 | install_release.sh 未串联停写、预发布快照、迁移后业务健康闸门 | 可诊断、可安全失败的发布状态机 |
| P7-R03 | P0 | 失败分支主要回切代码软链，未处理 schema 兼容；重启失败还可能打印已恢复 | 按数据兼容和是否恢复业务决定回退 |
| P7-R04 | P0 | deploy 工作流独立打包，无强制同版本测试门槛；两次解析可变 ref；现场 ssh-keyscan 建立信任 | 发布来源固定、已验证、受控且不依赖现在提供 VPS 参数 |
| P7-R05 | P1 | restic 脚本没有显式执行总时限；输出记录原 repository 与 stdout 尾部 | 有界、可追踪、脱敏的异地备份 |
| P7-R06 | P0/P1 | offsite 健康年龄取上传时间；health 的退出成功包含 disabled/maintenance；心跳报告配置值 | 正确区分数据新鲜度、上传成功、业务就绪和真实连接策略 |
| P7-R07 | P0 | 多库激活处理 Python 异常，但缺少已核实的进程中断恢复账本；逐库在线快照不是跨库同一时点事务 | 中断后继续保持保护，能明确回滚/续行 |
| P7-R08 | P1 | 仅有 Windows 离线证据，Linux 生命周期、权限、锁与资源边界尚未验证 | 干净 Linux 测试层及可执行的目标验证脚本 |
| P7-R09 | P1 | 状态、源码、原计划与真实验收的完成口径需统一 | 如实更新文档与交接证据 |
| P7-R10 | LIVE | VPS、真实 Actions、异地恢复、C3/C4 与连续运行证据未完成 | 参数到位后按清单验收 |

P7-R06 中“不能把 health 退出 0 直接当发布成功”是对新增发布闸门的要求，不要求破坏原有 disabled 模式的兼容退出语义。

## 4. 执行约束与前置检查（P7-R00）

接手 agent 先完成以下只读检查：

1. 阅读 `AGENTS.md`、`.planning/PROJECT.md`、相关 `.planning/codebase/`、`docs/intelligence.md`、`docs/deployment.md`、`docs/phase7-acceptance.md` 和 `07-VERIFICATION.md`。
2. 记录分支、HEAD、tracked/untracked 改动及当前测试结果；不 reset、不覆盖用户改动、不清理 `output/` 或 `test/runtime/`。
3. 比对本计划证据中的文件与最新版本；已修项改为“复核通过”，不要再改一遍。
4. 读取 requirements、pyproject、全部 Phase 7 units/timers、release/build/preflight 脚本、locking、heartbeat 和涉及的角色入口。
5. 如需 Windows UAT，先按 `test/README.md` 对照 descriptor 与实际进程；不得启动第二个 Bot。
6. 后续真实发布必须包含这些已验证改动的明确提交。当前旧 HEAD 本身不能代表“521 测试通过的工作区内容”；代码修复阶段不因此自动提交或推送。

固定边界：

- 保持 Python 3.10+、模块化单体与 SQLite；不引入 Redis、Celery、PostgreSQL、Kubernetes。
- 公开命令使用 `trendradar.integrations.lark`；内部 `feishu` 包和已有测试保留。
- 不重写聚类、Importance、Assistant 能力范围、原报告与消息去重。
- Research 默认关闭；没有授权，不调用真实模型、研究供应商或发送真实消息。
- SQLite 测试使用临时库；部署故障测试使用临时目录、虚拟 systemctl/restic 或一次性 Linux 环境。
- 不把新命令、配置或文件名写成已经实现。以下“建议新增”均由接手 agent 实施后确认。

## 5. 产物、安装与依赖闭环（P7-R01）

### 5.1 修改范围

现有：`scripts/deploy/build_release.py`、`create_manifest.py`、`install_release.sh`、`requirements.txt`、`pyproject.toml`（如存在）、`phase7-ci.yml`、`phase7-release.yml`。  
测试：扩展 `tests/deployment/`；必要时新增专门的 Linux 安装 smoke 测试。

### 5.2 实施要求

1. 核实项目本体安装方式。优先沿用已有打包元数据，采用 regular install 或 wheel；不能只安装第三方依赖后依赖仓库根目录恰好出现在导入路径中。[S1]
2. 如当前工程不具备合适打包结构，可选择明确、统一的只读 release 导入路径作为最小修复；必须覆盖所有 unit、运维命令和恢复命令，并在文档解释选择。不要顺手重构全项目包装系统。
3. 在目标 Linux/Python 组合生成和验证实际依赖锁定；包含必要的传递依赖与可核验哈希。开发范围声明可保留，生产安装必须绑定本次验证的依赖集合。
4. 无论安装方式如何，候选 release 的依赖准备、包安装和离线检查尽量在停业务之前完成。依赖下载失败不得先停掉现有健康版本。
5. manifest 增加或验证：release ID、解析后的 commit SHA、dirty 标志、产物哈希、依赖锁哈希、Python/平台信息、涉及数据库类型与 schema、最低可读取 schema、迁移/回退策略标识。
6. 服务实际 `TRENDRADAR_RELEASE_ID`、heartbeat 和 health 必须能对应被激活的 manifest；不能永久保留 `replace-with-release-id` 或前一版本值。
7. 解包前校验输入边界：允许目录内的真实路径、单一预期根目录、无绝对路径/父目录逃逸/越界链接/设备条目/目标覆盖。manifest 与 artifact 必须来自可信发布链；“二者一起被替换但哈希一致”不算来源认证。
8. 构建继续排除 secret、`.env`、数据库/WAL/SHM、`output/`、`test/runtime/`、运行日志和本地虚拟环境。保留必须的 env 示例、unit、迁移和运维脚本。
9. 同一 release ID 配不同 digest 必须拒绝。已成功安装的同一 ID/digest 可幂等返回；失败残留需明确标记，不能既覆盖又误报成功。
10. 生产 artifact 只接受干净、明确提交的构建；本地 dirty 构建仅可标注为开发验证产物，不冒充生产候选。

### 5.3 验收

- 从产物建立新 venv，清除外部 PYTHONPATH，离开 checkout/release 根目录，在临时运行目录执行导入、`--help`、离线 `--check` 和 `pip check`。
- 空环境下可解析必须的配置资源；未准备数据库时 strict 模式按预期拒绝，而不是因 import error 退出。
- 两个干净安装解析到相同的锁定版本；无需强求不同构建时间产生的压缩包字节完全相同。
- 错误哈希、恶意目录条目、缺依赖、重复 release ID 的结果可预测，且不触碰运行库或 current。

## 6. 发布安全状态机（P7-R02）

### 6.1 修改范围

以 `install_release.sh` 为入口；复杂状态可提取为固定参数的 Python 运维模块。复用 `ops/database.py`、`backup.py`、`maintenance.py`、`health.py`。不允许让 Assistant 获得任意 shell。

### 6.2 必须有的发布阶段

| 阶段 | 动作 | 出错时的安全结果 |
| --- | --- | --- |
| prepare | 校验来源、参数、空间、候选环境；记录旧 release 和服务/timer 状态 | 不改变现有业务 |
| acquire | 获取主机级部署互斥锁，写持久事务记录 | 第二个部署明确失败或有界等待 |
| quiesce | 标记本次发布维护状态，暂停触发源，停止所有相关 writer | 未确认停写则禁止迁移/替换 |
| snapshot | 对已有的统一、AI 和适用历史库建立完整预发布快照，记录配置版本 | 快照不完整则取消迁移；首次初始化另走明确分支 |
| migrate | 在停写状态显式准备/迁移所有必需库，核验 schema 与策略 | 保持维护，走兼容回退决策 |
| switch | 原子替换 current，安装已验证的 unit/非秘密配置变更 | 不留下可见的半切换 |
| pre_resume | 在不接单、不调用供应商、不发送的条件下完成候选检查 | 不为通过检查偷偷清除恢复保护 |
| resume | 记录“此后可能有外部业务”，仅解除本事务拥有的部署 guard，启动批准的角色 | 后续失败不得无条件恢复旧库 |
| verify | 有界等待业务就绪，核对新 release、schema、角色、队列及错误 | 失败停止相关角色，重新保护，保留证据 |
| finalize | 恢复批准的 timers，记录成功与保留位置 | 只有全部必要门槛通过才报部署成功 |

实施细节：

- writer 不只 Bot/Worker，还包含运行中的 Scheduler、main collector、AI collector，以及可能修改同库的旧任务。只停 timer 不会证明已运行的 oneshot 已停。
- 捕获运行状态，只恢复发布前启用、且本次批准继续启用的任务；不能顺便启用全部采集和消息发送。
- 确认旧 cron、Actions、Docker 不再承担相同生产范围；未完成唯一执行方切换时不要宣称 VPS 接管成功。
- 部署互斥锁与业务角色锁是不同职责。设计统一取锁顺序，避免安装器持锁再调用内部也取同一非重入锁的 migrate/activate 导致死锁。
- guard 和部署事务记录保存在稳定 control 目录，不随 release 软链漂移；记录 transaction ID、owner、阶段、旧/新版本、快照 ID、是否跨过业务恢复边界。
- 如果进入时已有 restore guard、未知维护事务或无效 guard，停止并报告；绝不能自动 clear。
- 普通代码发布不应设置灾备 recovery cutover；也不能清除既有 cutover。
- 迁移显式覆盖启用功能需要的 intelligence 与 AI Frontier 库。历史 news/rss 库没有对应迁移需求时只纳入备份与验证，不随意修改。
- 首次安装必须明确选择新建或导入：真正尚不存在的新库在事务中标记为待初始化，不伪造预发布快照；任何已有库仍先备份。本应存在但意外丢失的库不得自动当作首次安装重建。
- current 的更新采用同文件系统临时链接加原子 rename 等可靠方式；失败记录准确，不仅用 EXIT 清理 staging。
- 设置发布、取锁、停止、迁移、健康等待的分阶段预算；所有失败都应有非零退出和明确阶段，日志脱敏。

### 6.3 避免维护模式与健康闸门互相阻塞

现有 Bot 会在 guard 存在时拒绝启动，Worker 也会退出维护分支。不能一边要求 guard 全程存在，一边要求普通 Bot 正常就绪。

本计划默认采用上表的最小改动方案：

1. guard 内做包、配置、数据库等离线预检查；
2. 在清除本事务的部署 guard **之前**持久记录“将进入可能有业务写入的阶段”；
3. 启动服务后执行真实就绪检查；
4. 此后失败采用第 7 节的保守策略，不无条件倒回旧库。

如果接手 agent 改用“维护状态下允许初始化但禁止所有业务副作用”的专门就绪模式，需说明新增边界并补完整隔离测试；本计划不强制新增这种模式。

### 6.4 验收

任何阶段注入失败或中断，必须能从持久记录判断：当前代码、数据库、guard、服务和 timers 各是什么状态。不能出现“返回成功但进程已退出”“数据库被迁移而旧进程仍写入”“新旧发布混用”。

## 7. Schema 感知回退（P7-R03）

### 7.1 基本规则

代码软链回切不是完整回滚。必须同时考虑依赖、配置、全部相关数据库和外部副作用。

| 场景 | 默认处理 |
| --- | --- |
| 候选准备失败，尚未停业务 | 保持旧版本运行，保留失败摘要 |
| 已停写但尚未改变数据 | 恢复本事务改变的服务状态；保留预存 guard/cutover |
| 数据已迁移，旧代码明确支持新 schema | 可回切旧代码和兼容配置；保留当前数据，验证后恢复 |
| 数据已迁移且不兼容旧代码，尚未跨业务恢复边界 | 全部 writer 关闭时，可用已验证的预发布快照恢复相关库集合，再恢复旧版本 |
| 已跨业务恢复边界，可能接单、处理或发送 | 禁止默认回灌旧快照；停写、保留当前库，选择兼容代码回退或人工前向修复 |
| 数据/外部发送状态不明确、rollback 本身失败 | 维护状态不解除，退出非零并报告人工处理点 |
| 首次安装没有旧版本 | 保留失败候选、数据库和诊断信息；不得打印“已恢复上一版本” |

### 7.2 实施要求

1. 迁移前记录各库实际 schema 与旧代码兼容范围；不能只保存统一库的整数版本。
2. 在临时快照上先验证迁移和旧/新代码的读取边界；当前没有 schema 变化时，也要测试未来升级时的分支。
3. 回退恢复复用现有多库 restore/activate 机制并满足同样的停写、锁和 guard 约束；禁止直接覆盖活跃 DB/WAL。
4. 预发布快照带旧 release 和配置指纹；不把整个含密钥的配置目录打进普通 CI artifact。
5. 不自动把不确定投递重置为 pending；不清空 completed 事件；不补发已完成日报窗口。
6. 成功消息必须对应真实结果。当前失败分支里的 `systemctl restart ... || true` 不能吞掉失败后仍声称已恢复。
7. 释放部署 guard 之前，验证回退后的实际 release、schema、角色与数据库路径；遗留恢复 cutover 另行保留。

验收重点：模拟迁移成功但服务失败、软链切换失败、回退重启失败、已产生新事件后的失败以及首次安装失败。后两者不得自动删除新事件或声称无损回退。

## 8. 工作流、信任与最小权限（P7-R04）

### 8.1 当前已确认问题

- package 与 deploy job 分别 checkout `inputs.ref`；如果它是移动中的分支，installer 可能不属于同一份代码。
- 手动 deploy 内未强制先运行同一代码版本的测试；输入描述里的“Validated”不构成机器门槛。
- 运行时 `ssh-keyscan` 的输出直接进入 known_hosts，缺少独立核验的信任来源。[S2]
- 工作流上传一个 installer 后直接 sudo 执行；应复核为部署身份提供的权限是否大于固定发布操作所需。

### 8.2 实施要求

1. ref 只解析一次，保存不可变 commit SHA；所有 checkout、构建、测试、manifest 和安装器均绑定该 SHA。
2. 默认在同一发布链内先跑共享的验证 job，再构建一次，后续 release/deploy 消费同一 artifact。也可消费已成功 CI 的确切 artifact，但必须核验 run、SHA、digest 与验证结论，不按模糊名称取“最近一次”。
3. 不通过“重新打包相同分支”代替“部署刚验证的产物”；CI 测试通过却部署另一组字节不能放行。
4. 安装器必须来自同一已验证产物或同 SHA 且哈希可核验的独立文件；避免第二次可变 ref 解析。
5. 部署仅手动触发；生产目标与可用 ref 有明确限制，防止选择未经保护的 environment 取得同等级权限。保留最小 token 权限和已有 action SHA 固定。[S3]
6. 接入预先核验的 known_hosts/主机公钥配置，强制 host-key 校验；缺失、变化或不匹配时失败关闭。具体值由用户后补，不在代码中假定。
7. HOST、USER、PORT、PATH、release ID 分别校验；参数通过安全传递方式进入远端固定入口，避免把未经验证的路径拼成远程 shell 语句。
8. 优先使用 root 管理、部署用户不可随意改写的固定发布入口，sudo 仅允许必要操作；运行服务使用非特权用户，不能修改 release、venv、unit 或 root 发布入口。
9. 限定解包/安装路径，验证目录所有者与 symlink 边界；不授予任意上传脚本无限 sudo 的能力。
10. job 配置总时限、环境对应 concurrency、失败证据和敏感信息清理。GitHub 并发限制不能替代 VPS 侧部署锁。
11. 加入无真实主机的 workflow/installer 测试：移动 ref、失败测试、错误 digest、未受保护目标、缺 host key、重复部署。

### 8.3 参数后补契约

本轮只实现字段读取、校验、文档和假数据测试：

| 后补项目 | 当前允许的工作 | 当前禁止的替代 |
| --- | --- | --- |
| VPS host/user/port/path | 配置接口与校验 | 猜测用户主机参数 |
| SSH 私钥/部署身份 | secret 引用与最小权限说明 | 写入仓库、文档、日志 |
| 已核验主机公钥 | known_hosts 输入接口、缺失失败测试 | 自动信任首次网络扫描 |
| GitHub Environment | 配置清单与检查脚本 | 声称 YAML 已自动配置真实审批人 |
| 首次初始化数据来源 | 新建/导入的可执行分支 | 默认复制整个 UAT 沙箱 |
| restic 目的地/恢复凭据 | 环境变量契约、模拟备份/恢复 | 为通过测试开通真实资源或上传私有数据 |

这些值没补齐时，离线修复可全部推进；真实发布及对应验收保持 pending。

## 9. 有界且可核验的异地备份（P7-R05）

### 9.1 修改范围与已确认边界

- `scripts/deploy/offsite_backup.py`、`trendradar/ops/backup.py`、backup unit/timer、backup env 示例。
- 当前脚本使用 `subprocess.run(..., check=True, capture_output=True)`，未给执行总时限。
- 当前成功回执保存原始 repository 和 stdout 尾部；这些字段可能携带敏感 URL/内容。这是输出风险，不是已经发生凭据泄漏的证据。
- backup unit 的完整兜底超时和实际 offsite 接线需先核实，不能仅凭 runbook 已写说明就视为接线通过。

### 9.2 实施要求

1. 只上传已完成且再次通过清单/哈希核验的快照；发现必需库缺失、损坏或 partial 时不上传、不写成功回执。
2. 明确必需库集合来自部署配置。配置启用 AI 时不能把缺失 AI 库默认为“可选”；不存在的历史日期库则按实际业务范围说明，不伪造。
3. 设置整体执行预算、终止宽限和有限重试；到时终止本次 restic 及其辅助进程，避免只取消等待却让上传持续运行。
4. 结合 systemd 的服务时限与子进程管理做兜底；脚本被单独调用时也必须有自己的有界行为。
5. 不将原始 repository URL、stderr/stdout、口令文件内容、token 或消息正文直接写入回执/日志。记录安全的 repository 标识、结果码、已清理错误分类和必要摘要。
6. 成功回执绑定：本地 backup ID、manifest digest、快照数据时间、上传完成时间、远端 snapshot ID、release ID、校验状态。上传失败不得生成或更新成功回执。
7. 防止旧回执被复用于另一份快照；同一不可变快照重传不改变其数据时间。
8. 本地快照成功和异地上传成功分别记录。启用异地要求时，上传失败应在作业结果和 health 中可见，不能被“本地已备份”掩盖。
9. 检查初次启动、重复触发和长时间作业是否互斥；保护上传中的快照免遭本地保留策略删除。
10. 为小 VPS 明确保留上限、磁盘预警与清理流程。清理先 dry-run，保留正在使用、当前回退所需和最后可恢复的快照；本计划不授权现在删除任何真实备份。
11. 密码/恢复凭据必须在主机丢失后仍可由用户取得；文档只说明保存位置与恢复流程，不记录值。

### 9.3 验收

通过 fake restic 覆盖成功、非零退出、认证失败、超时、子进程残留、无效 JSON、旧回执、含模拟密钥的输出。测试不得调用真实 repository。

上传成功仅证明上传过程成功；远端数据可解密、可下载、可恢复必须由 P7-R10 的隔离恢复演练确认。

## 10. 健康语义与发布就绪闸门（P7-R06）

### 10.1 修复 offsite 新鲜度口径

当前 `_latest_backup(offsite=True)` 将 `created` 替换为 offsite `finished_at`，再计算 age。故“很旧的数据快照刚上传”可能显示很新。

改为至少分别返回：

- `snapshot_created_at` / `data_age_seconds`：用于数据恢复点是否过旧；
- `offsite_finished_at` / `upload_age_seconds`：用于最近一次成功上传距离现在多久；
- backup ID、manifest digest、远端 snapshot ID 与回执验证结果。

选择满足恢复要求的远端快照时，以数据时间和有效回执为依据，而非最新上传动作。重新上传一周前的快照不能刷新数据 RPO。

原计划的异地 RPO 24 小时是设计目标；现有 26 小时参数是告警/宽限口径，二者不能混称。文档与 health 明确目标、预警和失效阈值；真实 RPO 由可恢复数据时间测量。

未来时间戳、无时区、类型错误、非对象 JSON、回执与 manifest 不匹配均应产生可诊断异常状态，不被当作健康，也不让整个 health 命令崩溃。

### 10.2 不把 health 退出码 0 等同于可发布

原命令的 disabled/maintenance 可以保留退出 0，以兼容已有用途；发布闸门应使用明确的“预期运行配置 + 就绪判定”，例如新增 readiness 子命令或由发布器严格解析结构化报告。

生产启用配置的最低就绪条件：

1. 配置成功解析，实际 release 与候选一致；不接受 unknown、占位符或旧 release。
2. schema、数据库路径和所需文件匹配；统一库和启用 AI 的库都处于预期版本。
3. 所需常驻角色心跳存在、足够新、状态在允许集合；不能只检查 PID 存在或 `systemctl restart` 返回成功。[S4]
4. 对生产 Bot，长连接状态与运行预期一致；未连接、冷却和连续失败不能冒充 ready。离线测试使用模拟状态，不真实连租户。
5. guard/cutover 状态符合本次部署阶段；不能把遗留 maintenance 当业务就绪。
6. 必需数据源、队列进展与备份符合本次上线档位；首次安装允许显式 bootstrap 阶段，但不能长期豁免。
7. 错误配置不能因 fallback 到空配置而悄悄得到 disabled/成功。
8. 对明确要求禁用的 profile 验证“禁用且无副作用”，不能用它冒充启用系统验收通过。

### 10.3 实际 SQLite 策略证据

当前角色心跳片段填写 `_synchronous(settings)`，这是配置值；health 独立只读连接查询的 PRAGMA 也不能证明另一个 writer 的设置。

- 各关键 writer 在自己的实际连接初始化后取得 `connection_policy`，报告实际 synchronous、journal、schema 与 role/release 身份。
- health 区分配置期望、writer 报告值和自身探测连接值；未知、缺失、不匹配应按角色要求报告异常。
- 不为了探测策略让 health 建库、迁移或修改 journal。
- 如 `database check` 继续调用会配置 PRAGMA 的 `open_existing`，明确它不是纯只读 health。需要无副作用检查时用只读实现。
- 生产 FULL 方案保留；进程崩溃恢复不等于整机断电验证。[S5]

本轮仅在助手的临时共享内存 SQLite 做了连接隔离诊断：同一库的连接 A 为 NORMAL、连接 B 为 FULL。它说明“新探测连接的值不能代替 writer 值”，不代表用户 VPS 的 SQLite 已验收。

### 10.4 其他健康边界

- 生产必需源列表明确配置；不能在“要求采集健康”时因 expected_sources 与 source_runs 同时为空而直接通过。
- 对项目实际 source_run 状态做完整映射，验证失败、过旧、缺失与第一次运行。
- 定义队列指标：可执行任务等待、最老未完成事件和处理中租约不是同一概念；重试不能无限刷新时间而掩盖积压。
- 常驻 Bot/Worker 与 oneshot collector/scheduler 分别判断；不要求已正常结束的 oneshot 永久提供活跃心跳。
- schema 期望值复用权威常量/版本契约，避免 health 硬编码以后落后于迁移。
- 报告保持本地、只读、脱敏；health 不调用模型、不补采集、不发送修复消息。

## 11. 多库快照与中断恢复（P7-R07）

### 11.1 现有实现需要补强的地方

1. 当前 create_snapshot 逐库执行 SQLite Online Backup。它能得到各库一致副本，但“全部完成”不自动等于跨库同一业务时点。[S6]
2. 当前 activate_restore 用内存列表记录已移动/安装文件，可处理 Python 异常；SIGKILL、重启或主机中断不会走这一回滚分支。
3. 当前 pre-restore 的 create_snapshot 调用没有传 root，回执未必具有完整集激活需要的 relative_path；应核实并补齐恢复映射。
4. 临时 DB 已 fsync，不代表 guard、manifest、rename 与父目录元数据全部具有经验证的持久性。不能因此宣称任意掉电时刻多库原子恢复。

### 11.2 实施要求

- **两种快照模式分开**：日常在线快照记录各库时间范围与一致性边界；用于升级回退或完整集切换的快照，在所有相关 writer 静止后生成。
- 日常快照如果有跨库业务不变量，采用短暂协调停写或恢复后的显式协调检查；不能只用“每库 integrity_check=ok”代替业务一致性。
- 快照及 pre-restore 清单保留 root-relative 路径、库类型、schema、大小、哈希和目标映射；必需库完整、目的地唯一、不越界。
- 激活前取得与所有 writer 一致的锁域；专门确认 AI migrate 的锁键问题。若已一致则只补测试。
- 在稳定 control 目录记录持久恢复事务：事务 ID、目标集、旧文件保留位置、准备状态、每库切换状态和 cutover。先记录意图，再做不可逆的阶段动作。
- 对支持的平台正确同步文件和父目录元数据；Windows 与 Linux 的差异明确测试/标注，不以普通异常测试冒充掉电证明。
- 中断后重启先检测未完成事务。默认保持 guard，阻止 Bot、Worker、Scheduler 和 collector 接触混合库集合。
- 提供可审计的检查/续行/回退操作，复核目标内容与哈希后再行动；不得根据文件名猜测“应该删哪份”。
- 已确认旧 DB/WAL/SHM 均保留在记录位置；不中途清理。只有整个集合验证完成且用户接受后才进入保留策略。
- 回滚或续行失败时仍保持保护，报告受影响库，不自动解除维护。
- guard 的创建、修改、清除与 release 事务有归属规则，避免两个操作互相覆盖。
- 保留 recovery cutover 对旧事件、无可信创建时间事件及旧日报窗口的保护；不得在普通重启后自动清除。
- 不承诺平台发送端到端 exactly-once；无法确认的外部发送保留为需核对状态。

### 11.3 验收

在临时多库目录中对每个关键阶段故障注入，至少包括：

- 第二个库切换前/后进程被杀；
- 一部分旧 DB/WAL 已移动但新 DB 尚未全部安装；
- 记录文件损坏、库清单重复/越界、目标空间不足；
- 重新启动后读取未完成事务并保持阻断；
- 恢复集合、pre-restore 集合都能按完整映射重新恢复；
- 普通异常回滚与进程中断恢复分开验证。

SIGKILL 测试只证明进程中断处理；目标机重启/文件系统持久性证据仍在 LIVE 阶段补充。

## 12. Linux 生命周期与运行边界（P7-R08）

### 12.1 离线可做

1. 在干净 Linux 环境运行 full pytest、部署定向测试和产物安装 smoke；不是只在 Windows 使用文件存在性断言。
2. 校验实际安装后的 unit/timer/slice、绝对解释器、工作目录、运行用户、环境文件、读写目录和日志位置。
3. 用 systemd 可用的一次性 VM 验证时才宣称生命周期通过；普通容器中没有 systemd 时，结果只能标为包/脚本验证通过。
4. 检查 SIGTERM 路径：停止接新工作、限制在途等待、清理子进程、释放锁/租约、保存可恢复状态。
5. 切换或停止过程中，已生成回复不再次请求模型；已完成事件不重发；未确认外部发送不草率改回 pending。
6. 配置并验证合理的 stop/start/runtime 限制、重启节流和 cgroup 子进程覆盖。强制终止作为兜底，不声称等于优雅退出。
7. 验证相同 DB 的同角色互斥、combined 与拆分角色互斥、collector 互斥；锁冲突不能伪装成一次成功采集。
8. 保持 service、ops 命令和部署脚本的 DB/control/lock/heartbeat 路径一致；从不同 cwd 调用不能分裂成两套运行状态。
9. 在实际非特权用户下验证服务能写运行目录、不能改代码/venv/units；只用 root 跑通不算。
10. 明确首次生产启用时应填的健康源列表、备份策略、角色开关；保留默认 Lark/Research 关闭，不能靠默认关闭绕过生产验收。

### 12.2 现场才能证明

CPU、memory、task、FD、磁盘/inode、WAL 增长和供应商并发下的实际表现属于 P7-R10。

已有 slice 的 MemoryHigh=1G、MemoryMax=1250M、TasksMax=128 是初始配置，不是已测资源余量。目标约 1 CPU/1.87 GB 也只是规划值，需读取真实主机。不要在本地测试结果中伪造“低配 VPS 稳定”。

## 13. 文档与证据收口（P7-R09）

必须同步更新：

- `docs/deployment.md`：真实可执行的安装、正常升级、失败回退、恢复、guard/cutover 和参数后补流程。
- `docs/phase7-acceptance.md`：按场景记录通过/失败/未执行/接受例外。
- `.planning/phases/07-deployment/07-VERIFICATION.md`：新增测试的实际结果和未完成门槛。
- `.planning/STATE.md`、`.planning/ROADMAP.md`：增量整改状态与目标验收分别列出，统一时间与完成口径。
- 相关 `07-01` 至 `07-04` 的 SUMMARY/PLAN：引用本次修复成果，不另建 Phase 9 或重排历史编号。
- 建议新增 `docs/phase7-remediation.md`：P7-R00 至 P7-R10 的闭环索引、变更摘要与证据链接。

每条证据至少记录：

| 字段 | 要求 |
| --- | --- |
| 场景 ID / 执行时间 | 时区明确；旧测试结果不能写成新执行 |
| 代码与环境 | commit SHA 或 dirty-worktree 标识、artifact digest、OS、Python、SQLite、systemd（适用时） |
| 数据与配置范围 | 使用临时/测试/生产中的哪一种；schema、配置档位；不含密钥 |
| 操作与预期 | 实际命令/注入点、允许的外部调用范围 |
| 结果 | 退出码、关键断言、相关日志位置 |
| 副作用与恢复 | 是否写库、发消息、改服务；测试后处于什么状态 |
| 未覆盖边界 | 未运行的 Linux、VPS、供应商或掉电项目 |

文档不得出现以下替代关系：

- “测试数量增加”代替“关键故障用例通过”；
- “有 deploy YAML”代替“真实审批和部署成功”；
- “上传成功”代替“异地数据可恢复”；
- “有 heartbeat”代替“writer 正确且业务可用”；
- “代码回切”代替“数据兼容或完整回退”；
- “维护 guard 文件存在”代替“已确认所有 writer 停止”；
- “28/31”代替“生产部署完成度”。

## 14. 参数到位后的现场验收（P7-R10）

这些项目现在可以准备脚本和证据模板，但执行应等待用户补参及对应授权。不要因未执行而伪造通过，也不要因此卡住 R01–R09。

| 场景 | 验证内容 | 对应门槛 |
| --- | --- | --- |
| LIVE-01 | 核对主机、OS/架构、Python 链接的 SQLite、systemd/cgroup、CPU/RAM/磁盘/inode/swap | DEPL-01、DEPL-05 |
| LIVE-02 | 使用真实受保护环境跑同 SHA 的 CI→artifact→受控部署；保存 run、digest 与主机实际版本 | DEPL-03 |
| LIVE-03 | 非特权用户下 Bot/Worker 启停、重启、异常退出；确认单实例、锁与恢复 | DEPL-01 |
| LIVE-04 | timer 调度、主/AI 采集、源新鲜度、队列前进、日报窗口与旧执行方停用 | DEPL-02 |
| LIVE-05 | 在隔离目标上执行升级失败及 schema 不兼容回退演练；不拿生产库首次试错 | DEPL-03、DEPL-04 |
| LIVE-06 | 从异地 repository 下载、解密并恢复到新目录/隔离主机，校验全部库与账本 | DEPL-03、DEPL-04 |
| LIVE-07 | 验证机器重启/进程中断后 guard 与恢复事务仍可识别，未完成切换不会恢复收发 | DEPL-01、DEPL-04 |
| LIVE-08 | Phase 5 C3：真实断连、有限重试、冷却与恢复，确认无第二 Bot/无重复处理 | 既有 C3 |
| LIVE-09 | Phase 5 C4：指定接收方确认实际日报/回复，核对消息 ID 和持久投递状态 | 既有 C4 |
| LIVE-10 | 至少连续 48 小时且覆盖两个日报窗口；采集、队列、备份、资源和异常恢复有记录 | DEPL-02、DEPL-05 |

现场注意：

- SQLite 版本以服务实际 Python 链接的库为准，核对当前官方 WAL 修复/发行信息；不因版本号相近直接假定含补丁。
- C3 的故障注入不能切断唯一远程管理通道；先有安全恢复入口，再限定测试服务的故障范围。
- 恢复演练默认禁用发送与模型/研究调用；验证数据和重复边界后才按明确授权解锁。
- RPO 按被恢复的数据时间计算；RTO 记录下载、解密、校验、激活和业务恢复的实际耗时。24 小时 RPO、30–60 分钟 RTO 是原计划目标，不是本次已达成指标。
- 已由用户接受跳过的“真实第二用户/非白名单”分支保留原例外记录，不重新强制打开；若历史记录中还有 B6 等编号，先核对原定义和裁定，不混同 C3/C4。
- 未取得平台精确重投同一事件的能力时，记录该限制；离线去重用例不伪装成平台真实重投。
- 现场发送、恢复覆盖、变更计划任务、Git 提交/推送各有独立副作用边界，不从“实施修复”推导出无限授权。

## 15. 离线验收矩阵

以下是验收场景，不是要求机械新增同等数量的 test 函数。已有测试满足要求时复用；一个参数化测试可以覆盖多个场景。所有新测试默认无真实网络和租户副作用。

### 15.1 产物与工作流

| ID | 场景 | 必须观察到的结果 |
| --- | --- | --- |
| OFF-A01 | 干净 Linux venv，在非源码 cwd 执行入口 | 导入、配置资源和离线检查成功 |
| OFF-A02 | 必需依赖缺失/安装失败 | 切换前失败，旧业务状态不变 |
| OFF-A03 | 锁定依赖重复安装 | 解析版本一致，pip check 通过 |
| OFF-A04 | 产物哈希错误或 manifest 缺字段 | 不解包/不激活 |
| OFF-A05 | 绝对路径、父目录、越界 symlink 等压缩条目 | 无越界写入，失败可诊断 |
| OFF-A06 | 检查 release 内容 | 无凭据、运行库、WAL/SHM、UAT 内容；必要模板存在 |
| OFF-A07 | 相同 release ID 的成功重跑与不同 digest | 同 digest 幂等；不同 digest 拒绝 |
| OFF-A08 | 构建后输入分支移动 | installer、代码、manifest 仍绑定同一 SHA |
| OFF-A09 | 测试失败、未验证 artifact 或错误 environment | 不进入真实部署步骤 |
| OFF-A10 | 缺失/变化 host key、异常路径/端口输入 | 失败关闭，不自动信任、不执行注入内容 |

### 15.2 发布与回退

| ID | 场景 | 必须观察到的结果 |
| --- | --- | --- |
| OFF-B01 | 两个安装器并发 | 主机侧互斥，状态不交叉 |
| OFF-B02 | 已有 restore guard 或未完成事务 | 拒绝自动发布，不清除保护 |
| OFF-B03 | timer 已停但 collector/scheduler 仍运行 | 不进入迁移；有界等待/安全失败 |
| OFF-B04 | 安装器与 migrate/activate 的嵌套锁 | 无死锁，锁冲突明确 |
| OFF-B05 | 预发布快照不完整、空间不足 | 禁止迁移，数据保留 |
| OFF-B06 | intelligence/AI 首装与严格启动 | 必需库显式准备；运行角色不隐式迁移 |
| OFF-B07 | 迁移成功，软链或启动失败，旧 schema 不兼容 | 业务恢复前可整体回退；证据完整 |
| OFF-B08 | 服务启动后立即崩溃/旧 release 心跳残留 | 就绪失败，不报发布成功 |
| OFF-B09 | 已跨业务恢复边界，出现新事件后失败 | 不自动回灌旧快照，不丢新事件 |
| OFF-B10 | 回退重启失败/首次安装无旧版本 | 退出非零，保留维护，不打印虚假恢复成功 |
| OFF-B11 | 成功发布与失败恢复 timers | 只恢复预存且已批准的状态 |
| OFF-B12 | 部署清理和 cutover | 只清本事务的部署 guard，不清灾备 cutover |

### 15.3 备份与健康

| ID | 场景 | 必须观察到的结果 |
| --- | --- | --- |
| OFF-C01 | 旧快照刚上传/重复上传 | 数据年龄仍旧，不能刷新 RPO |
| OFF-C02 | 最新上传时间属于更旧数据 | 按有效数据时间判断可恢复点 |
| OFF-C03 | 回执伪配、缺字段、未来/无时区时间、非对象 JSON | 明确异常，不健康、不崩溃 |
| OFF-C04 | restic 超时或留有辅助进程 | 总预算内终止本次进程树；不写成功 |
| OFF-C05 | stdout/stderr/repository 带模拟敏感串 | 回执与日志不泄漏 |
| OFF-C06 | 本地成功但异地失败 | 两个结果区分，健康不宣称异地满足 |
| OFF-C07 | 启用功能所需 DB 缺失或损坏 | 备份失败，不发布 complete |
| OFF-C08 | health 为 disabled/maintenance 但生产应启用 | 普通兼容语义保留；发布闸门拒绝 |
| OFF-C09 | 配置 FULL，真实 writer 被测试替身设为 NORMAL | 正确报策略不匹配，不以探测连接代替 |
| OFF-C10 | 角色缺失、过期、错误状态/旧 release | readiness 不通过 |
| OFF-C11 | 必需源列表为空、失败、缺失或过旧 | 生产策略下不能静默通过 |
| OFF-C12 | 队列反复重试/oneshot 正常结束 | 不掩盖积压，不误判已结束任务为常驻失联 |
| OFF-C13 | 启用 profile 下无 DB 或损坏配置运行只读 health | 不建库、不迁移、不发送、不误报成功 |

### 15.4 恢复与生命周期

| ID | 场景 | 必须观察到的结果 |
| --- | --- | --- |
| OFF-D01 | 多库 root-relative 映射，包括 pre-restore | 可完整定位和恢复，不只覆盖统一库 |
| OFF-D02 | 多库中途 Python 异常 | 保留旧集合，可回退，guard 不误清 |
| OFF-D03 | 多库中途 SIGKILL 后重启 | 识别未完成事务，不启动业务接触混合集合 |
| OFF-D04 | 损坏事务、越界/重复目标、空间不足 | 安全停住，保留证据与旧 DB/WAL |
| OFF-D05 | AI migrate 与 collector 竞争 | 同一锁域实现实际互斥 |
| OFF-D06 | guard/cutover 跨 cwd、release 和进程重启 | 指向同一稳定控制目录，保护仍生效 |
| OFF-D07 | 旧/无可信时间事件及旧日报窗口 | 保持隔离，不自动调用/发送 |
| OFF-D08 | SIGTERM 时存在在途处理或子进程 | 有界退出，恢复语义保持 |
| OFF-D09 | 非特权用户与沙箱权限 | 可写数据，不可改 release/venv/unit |
| OFF-D10 | 正常与 INTELLIGENCE_ENABLED=false 回归 | 既有行为和禁用无副作用语义都保持 |

共 45 个离线场景，加 10 个现场场景。此数量不是测试统计，也不替代原 Phase 7 计划中仍适用的验收项。

## 16. 推荐实施顺序与提交边界

| 顺序 | 工作内容 | 依赖/说明 |
| --- | --- | --- |
| 1 | R00 基线核对 | 所有工作前置；保留用户修改 |
| 2 | R01 产物与安装闭环 | 后续发布测试使用同一可安装产物 |
| 3 | R05、R06 备份回执与健康语义 | 发布闸门所依赖的证据先可信 |
| 4 | R07 恢复事务与锁域 | 为失败回退提供可靠恢复基础 |
| 5 | R02 发布状态机 | 接入已经验证的备份、迁移和健康 |
| 6 | R03 schema 回退决策 | 在各失败阶段验证数据/外部副作用边界 |
| 7 | R04 工作流 | 只部署已测试产物；参数仍可留待补充 |
| 8 | R08 Linux 集成与故障注入 | 覆盖真实安装路径、权限、进程和锁 |
| 9 | R09 文档与全量回归 | 每项有证据，再收口离线里程碑 |
| 10 | R10 现场验收 | 用户补参及授权后执行 |

若接手 agent 获准提交，可按“产物安装 / health 与 backup / restore / release 与 workflow / Linux 与文档”划分小提交；未获授权只保留工作区 diff 和说明，不自动 commit/push。不要为交接便利抹掉既有用户改动。

建议新增测试文件（名称可按仓库习惯调整）：

- `tests/deployment/test_install_release.py`
- `tests/deployment/test_release_rollback.py`
- `tests/deployment/test_workflow_contracts.py`
- `tests/deployment/test_offsite_backup.py`
- `tests/deployment/test_restore_recovery.py`

扩展既有 `test_health.py`、`test_backup.py`、`test_deployment_contracts.py` 和角色测试，不另建平行测试体系。

## 17. 离线完成定义与交接输出

R01–R09 满足以下条件才可标记“离线修复完成”：

- P0 已修复或有经验证、书面说明的等效安全方案；没有以“以后再填 VPS 参数”掩盖代码缺口。
- 适用的 OFF 场景通过；无法执行的 Linux/systemd 场景明确 pending，不能伪称全通过。
- Windows 兼容性与干净 Linux 产物验证均有相应记录；systemd 生命周期单列。
- 相关定向测试、全量 pytest、改动范围 Ruff、语法/构建检查通过；不要求清理无关全仓 Ruff 历史债。
- 核心不变量不回归：先授权后处理、completed 去重、已存回复重试、日报检查点、媒体/研究限制、禁用模式与恢复 cutover。
- 无真实凭据/运行数据进入 artifact、测试 fixture、Git diff 或日志。
- 新逻辑已写入 runbook；接手者可按说明判断发布失败后的真实状态。
- 本地代码与说明明确列出尚未提交、尚未部署及所有 LIVE 未完成项。

建议实际回归命令（从仓库根目录运行；先按变更范围调整）：

~~~text
python -B -m pytest tests/deployment -q -p no:cacheprovider
python -B -m pytest tests/integrations/feishu -q -p no:cacheprovider
python -B -m pytest tests -q -p no:cacheprovider
python -m ruff check <本次修改的 Python 路径>
git diff --check
~~~

Linux 增加实际候选产物安装、shell 语法/静态检查、systemd unit 验证及故障注入。以上命令不是本计划已执行的结果。

接手 agent 最终必须交付一页摘要：

1. 实际修改文件与 P7-R 编号映射。
2. 原问题、修复机制、失败时的安全状态。
3. 新增/复用场景及真实测试输出。
4. 代码、schema、配置、备份格式的兼容性影响。
5. 是否进行了真实外部调用、服务操作、提交或部署；未进行也明确写明。
6. 待用户补充的配置名称，不含值。
7. 剩余 LIVE 项及下一项最小安全操作。

建议收口结论用语：

> Phase 7 增量修复已完成离线验证；生产参数与目标环境验收待补。未宣称已经部署、异地恢复已成功或 Phase 7 已通过全部生产门槛。

## 18. 官方依据与证据使用边界

以下官方资料于 2026-10-13 查阅；它们用于解释安装、就绪和恢复边界，不证明本项目或 VPS 已满足要求。实现时仍需核对目标版本。

- [S1 pip：Local project installs](https://pip.pypa.io/en/stable/topics/local-project-installs/) — CI/部署优先 regular install；本计划据此要求离开源码目录验证实际安装结果。
- [S2 OpenBSD：ssh-keyscan](https://man.openbsd.org/ssh-keyscan) — 未经核验的扫描结果不能建立可信主机身份；具体可信公钥由用户后补。
- [S3 GitHub：Secure use reference](https://docs.github.com/en/actions/reference/security/secure-use) — 工作流依赖与 secret/Environment 权限边界；保留既有 action SHA 固定，并验证真实环境保护。
- [S4 systemd：systemd.service](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html) — service 启动状态不自动等于应用就绪；停止超时与应用恢复语义需分别验证。
- [S5 SQLite：PRAGMA synchronous](https://www.sqlite.org/pragma.html#pragma_synchronous) — WAL 的 FULL/NORMAL 持久性区别；不把应用崩溃测试描述成主机断电验证。
- [S6 SQLite：Online Backup API](https://www.sqlite.org/backup.html) — 单库在线一致备份；本计划据此区分单库一致性和跨库业务时点。

本计划不声称进行了完整渗透测试、依赖漏洞扫描或生产负载测试。已确认缺口来自同步源码；待核验项和现场项已分别标注。


