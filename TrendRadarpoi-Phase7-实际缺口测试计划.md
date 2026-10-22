# TrendRadarpoi — Phase 7 实际缺口测试计划

版本：1.0  
编制时间：2026-10-13，Asia/Shanghai  
适用工作区：`C:/Users/DELL/Desktop/TrendRadarpoi-master`  
依据：本轮 Remote Desktop Commander 源码核对、实际执行日志，以及对读取源码进行的隔离诊断。  
用途：交给后续 agent 实现回归测试、修复缺口并复核。本文是测试计划，不代表新增用例已经执行或通过。

## 1. 本轮结论与测试目标

当前不能把 P7-R01～R09 整体关闭。需要补齐的核心是四类行为：安装器与服务配置一致、readiness 判断正确、恢复后的运行权限正确、发布或恢复中断后仍有有效保护。

测试必须回答以下问题：

1. 固定 sudo 入口启动的 installer，是否与 systemd 服务使用相同的数据库、心跳、控制目录和锁目录？
2. Bot 尚未连接、正在重试或处于冷却期，是否会被错误判为 ready？要求来源运行记录但没有任何记录时，是否会被放行？
3. 以 root 执行恢复或首次迁移后，真正的服务账号能否读取和写入数据库？
4. 部署或多数据库恢复被强制终止后，业务能否绕过保护；能否查明并完成一致的恢复？
5. 修复这些问题后，现有发布边界、备份和 Lark 兼容行为是否保持正确？

本计划包含 **28 项无需真实业务服务的测试场景、6 项目标环境验收场景**。场景可参数化成多个测试函数；这个数量不是 pytest 应当显示的测试数量，也不是完成率。

## 2. 已有证据及其边界

### 2.1 已核实的实际日志

时间均为 2026-10-13，Asia/Shanghai。

| 范围 | 实际结果 | 日志时间 | 可以证明的内容 |
| --- | --- | --- | --- |
| 全量 pytest | 531 passed，1 warning | 22:38 | 当时被执行版本的现有测试通过 |
| 部署测试 | 23 passed | 22:35 | 现有部署测试通过 |
| Feishu 兼容测试 | 78 passed，1 warning | 22:25 | 当时的离线兼容回归通过 |
| Phase 7 角色边界测试 | 5 passed | 22:25 | 现有角色隔离测试通过 |
| Scoped Ruff | All checks passed | 本轮执行日志 | 被检查路径通过对应静态检查 |

以上范围存在包含关系，不能将 531、23、78、5 相加。编写本计划时没有重新运行这些测试。执行 agent 应记录自己开始时的版本；修复后的最终结果必须重新生成。

工作区核对时是 `main...origin/main [ahead 42]`，且存在大量已修改及未跟踪文件。该状态不等于已形成可部署的干净候选版本。

### 2.2 已复现或从源码确认的缺口

| 编号 | 当前事实 | 证据强度 | 关联整改 |
| --- | --- | --- | --- |
| F-01 | installer 只加载 release.env；固定入口未加载 common.env。参考服务把心跳写到 /run/trendradar/health，独立 health 进程默认读取数据库旁的 health。锁目录也存在相同的配置传递风险。 | 心跳目录错位已隔离复现；配置接线已读源码 | R02、R06 |
| F-02 | health 新增了 disconnected 检查，但真实 transport 会使用 connecting、retrying、cooldown；这些新鲜、同 release 的心跳没有触发错误。 | 实际状态定义与心跳写入源码已核对；检查函数已隔离复现 | R06 |
| F-03 | require_source_runs=true，且 expected_sources 与 source_runs 都为空时，readiness 仍可为 healthy。 | 设置允许该组合；隔离 collect_health 诊断已复现 | R06 |
| F-04 | activate_restore 用 mkstemp 文件替换数据库，未保留目标属主及权限；隔离 POSIX 诊断中权限由 0660 变为 0600。sudo/root 恢复路径会产生服务账号访问风险。 | 权限位变化已复现；真实非 root 服务账号读写尚待 PERM-01 验证 | R03、R07 |
| F-05 | read_guard 不读取 deploy-in-progress.json；maintenance clear 不检查未完成恢复事务。存在部署标记或 pending restore 的情况下，保护读取仍可能返回无 guard。 | 源码与隔离诊断均已确认 | R02、R03、R07 |

本轮源码诊断置信度：**高**。真实 VPS 的安装、权限、systemd 生命周期、远端恢复及持续运行结果：**未知**。

### 2.3 已有测试不能替代的证据

- installer 的现有合同测试主要检查脚本是否包含某段文字，不会真实执行停写、启动失败、readiness 超时或强制终止分支。
- 恢复测试已检查成功后的 journal 和预先写入的中断记录，但这不等于在实际文件切换过程中杀死进程。
- Windows 通过不能证明 Linux UID/GID、文件模式或 systemd 行为。
- 单独执行提取函数适合定位缺陷；最终验收必须通过真实模块、CLI 或固定安装入口，不能只保留隔离诊断。

## 3. 测试环境与执行边界

| 层级 | 环境 | 用途 | 当前是否需要 VPS 登录信息 |
| --- | --- | --- | --- |
| W | Windows，临时目录和临时 SQLite | health、guard、恢复逻辑、已有兼容回归 | 不需要 |
| L | 可销毁 Linux VM 或容器；权限用例需要真实 root 与独立服务 UID | Bash installer、文件权限、进程锁、强制终止、安装产物 | 不需要 |
| S | 可销毁且真实运行 systemd 的 Linux 环境 | unit 语法、变量展开、生命周期和停止顺序 | 不需要；普通未启动 systemd 的容器不能替代 |
| V | 用户后续指定的 VPS、GitHub Environment 与备份目标 | 真实部署链路、远端恢复、Lark 和持续运行 | 需要，后补 |

“无需真实业务服务”指不连接真实 Lark、Gemini、采集来源或 restic 远端。安装依赖可以在受控构建环境访问配置好的包源；这不等于完全断网构建。

执行约束：

- 所有故障注入使用专属临时目录。不得使用或覆盖用户的 output、test/runtime、现有数据库、WAL/SHM、fixture 或日志。
- 不启动第二个真实 Bot。测试 transport、provider、send、collector 与 restic 远端接口使用 fake；断言外部调用计数。
- 只终止测试自己创建并记录的 PID／进程组；不得按宽泛进程名结束 Python、Bot 或 systemd 服务。
- 不用 root 运行的成功结果代替服务账号权限结果，不用 chmod 777 让测试通过。
- 环境和日志只记录允许公开的键及“已设置/未设置”。不输出整个环境，不输出真实凭证、消息正文或 provider payload。
- 本计划不要求提交、推送或部署。真正执行这些动作仍遵循项目 AGENTS.md 和当前任务授权。
- 用户已明确跳过的非白名单第二用户现场测试保持原有记录，不重新设为本轮阻断项；不能标记为已通过。

## 4. 开始执行前的基线记录

1. 阅读当前 AGENTS.md，以及本计划涉及的源码和现有测试。
2. 记录分支、HEAD、工作区状态、Python、pip、SQLite、OS；Linux 另外记录 UID/GID、umask、文件系统与 systemd 版本。
3. 因为当前工作区未提交，仅记录 HEAD 不足以标识测试对象。保存本轮改动文件清单及 SHA256；必要的补丁只包含本任务文件，排除凭证与运行数据。
4. 对照本计划的五个缺口，确认执行时源码是否又有变化；已修复的内容直接进入回归验证，不重复修改。
5. 在当前版本新增最小行为测试，先复现缺口，再修复。记录修复前后的断言差异；禁止以永久 xfail、扩大 skip 或删掉断言代替修复。
6. 当前没有这些新增测试的执行结果，初始状态统一记为 NOT_RUN。

建议先完成 ENV-01、HEALTH-01、HEALTH-03、PERM-01、GUARD-01/02 这组最小复现，然后补齐同组边界。

## 5. 测试支架与判定规则

### 5.1 通用夹具

- 使用独立的 runtime、control、health、locks、releases、current、backup 目录。
- 每个测试数据库写入唯一标识；多库恢复至少包含 intelligence、ai_frontier，以及一个 legacy 日期分区库。
- 数据完整性检查使用真实 SQLite 查询、integrity_check 和适用的 foreign_key_check。
- readonly 用例可比较文件字节哈希；经历正常 SQLite 写入的恢复场景应比较表内容、schema 与业务标识，不能要求文件字节完全相同。
- 时间阈值用受控时钟；不要依靠长时间 sleep。队列和来源年龄以配置的阈值判定。
- 无关指标先设为健康，让每个拒绝测试只改变目标条件，避免“因为另一个错误而失败”的假通过。

### 5.2 installer 行为支架

L 层必须真正执行 Bash installer，而不只是读取脚本文本。使用 fake systemctl 记录命令、单位名、顺序与返回值；明确模拟 active/inactive、启动失败和 timer 触发。

依赖安装可在纯控制流测试中替换为受控动作；这种替换必须标注。RG-04 另用真实安装产物验证打包和依赖。不得把“stub pip 成功”计入产物可安装证据。

入口级测试还要验证受控 sudo 环境：允许列表以外的调用者环境应被清除。测试应通过固定入口或其经过说明的隔离副本，不能靠测试进程手动导出缺失变量掩盖 F-01。

### 5.3 强制终止支架

用管道、事件或明确的测试 hook，让子进程在指定步骤通知父进程并等待；父进程收到通知后才发送 SIGKILL，或让子进程执行不会运行 finally 的终止动作。

不能用任意 sleep 猜测进程“应该已经执行到那里”。测试 hook 不得成为生产环境变量可随意触发的后门。

真实进程终止、普通异常、SIGTERM 是不同的测试路径。SIGKILL 测试不证明断电或存储设备故障下的数据耐久性；不要把这类结果写成断电验收。

### 5.4 统一结果标准

- ready 正向用例：真实 CLI 退出 0，状态符合 ready，所有必需角色、release 和数据条件匹配。
- ready 反向用例：退出非零，原因与目标条件对应，不能由异常堆栈或无关缺失项偶然制造失败。
- guard 用例：除了 guard 文件或返回值，还断言接收、消费、采集和外发接口没有执行。
- 权限用例：除 stat 外，必须由实际服务 UID 打开并写入目标数据库。
- 恢复用例：除 journal 外，必须检查全部目标库内容、保护状态和可重复的恢复步骤。

错误代码可以沿用或新增稳定名称；本文描述的错误含义不是对现有错误字符串的声称。

## 6. 环境加载与路径一致性 — ENV

定位：

- C:/Users/DELL/Desktop/TrendRadarpoi-master/deploy/bin/trendradar-install-release
- C:/Users/DELL/Desktop/TrendRadarpoi-master/scripts/deploy/install_release.sh
- C:/Users/DELL/Desktop/TrendRadarpoi-master/deploy/config/common.env.example
- C:/Users/DELL/Desktop/TrendRadarpoi-master/trendradar/core/heartbeat.py
- C:/Users/DELL/Desktop/TrendRadarpoi-master/trendradar/core/locking.py

| ID | 环境 | 操作与输入 | 必须通过的断言 |
| --- | --- | --- | --- |
| ENV-01 | L | 用最小 sudo 环境启动固定入口；按参考配置把角色心跳放在独立 run/health，准备同 release 的健康角色。安装器调用真实 health。 | 安装器与角色读取同一有效配置；心跳被找到；预期成功部署可达到 finalize，不依赖调用者手工 export。当前 F-01 应先被此用例暴露。 |
| ENV-02 | W+L | 将 database、AI database、control、health、lock、backup 路径全部改到非默认临时位置；执行部署检查、锁操作和恢复预检。 | 所有操作命中配置路径；默认位置没有新增数据库、锁或心跳；不会检查 A 库却迁移 B 库。 |
| ENV-03 | L | 缺少必需配置、格式错误、路径不可读，以及合法带引号的配置值分别输入入口。 | 非法生产配置在停写、迁移或切换前明确失败；合法格式按声明解析。不能静默退回开发默认值，也不能把任意 EnvironmentFile 当可执行 shell。日志无凭证值。 |
| ENV-04 | L | 测试角色用真实文件锁持有 bot/worker/collector/scheduler 锁；维护进程从安装入口解析配置后尝试迁移或激活恢复。 | 双方争用同一锁路径；冲突时有界失败且数据库不被改写；释放锁后同一路径操作成功。不能通过选用另一目录“解决”冲突。 |

关闭条件：四项通过；ENV-01 的证据包含角色与安装器生效路径的脱敏对比和真实 readiness 结果。只新增 source common.env 字符串断言不能关闭 F-01。

## 7. readiness 行为 — HEALTH

定位：

- C:/Users/DELL/Desktop/TrendRadarpoi-master/trendradar/ops/health.py
- C:/Users/DELL/Desktop/TrendRadarpoi-master/trendradar/core/settings.py
- C:/Users/DELL/Desktop/TrendRadarpoi-master/trendradar/integrations/feishu/transport.py
- C:/Users/DELL/Desktop/TrendRadarpoi-master/trendradar/integrations/feishu/__main__.py
- C:/Users/DELL/Desktop/TrendRadarpoi-master/tests/deployment/test_health.py

| ID | 环境 | 操作与输入 | 必须通过的断言 |
| --- | --- | --- | --- |
| HEALTH-01 | W+L | 对 Bot 的 connected、connecting、retrying、cooldown、stopped、disabled、unknown、maintenance 以及 disconnected 参数化；保持 release、时间和其他指标健康。另测 Worker running 与非运行状态。 | Bot 仅真实可接受业务的连接状态通过；连接中、重试、冷却及未知状态均拒绝 ready。Worker 使用自己的角色规则。至少一项由实际 transport 状态写入 RoleHeartbeat，再通过真实 health CLI 读取，不能只手写 disconnected。 |
| HEALTH-02 | W | 分别提供匹配、新旧不一致、缺失、unknown 的 release；缺失角色心跳和超龄心跳；随后恢复全部健康值。 | 匹配且新鲜时通过；错误 release、必需角色缺失或过期时拒绝。配置阈值等于和略超过边界分别验证，避免时间测量抖动。 |
| HEALTH-03 | W | require_source_runs=true 下测试：两个来源集合均空；明确来源但无记录；记录过期；真实失败状态；全部来源有新鲜成功记录。再测试 require_source_runs=false 的兼容行为。 | 要求来源时，空集合不能被当作已经证明健康；缺失、过期或失败均拒绝。全部有效时通过。关闭来源要求时不因单纯无来源记录误拒绝。当前 F-03 必须被单独暴露。 |
| HEALTH-04 | W | 构造真实可重试待处理事件，等待时间为阈值以下、等于、略高于；再构造已完成或已耗尽重试事件。 | 超过 queue_wait_seconds 的可处理积压拒绝 ready；健康队列通过；终态不会被误计为待处理积压。明确等待时间使用的业务语义，并让断言独立于待测函数内部计算方式。 |
| HEALTH-05 | W | 构造新鲜/过期本地快照、新上传但数据已过期的 offsite 收据、错误 digest/backup_id、数组 JSON 收据，以及完整有效收据。 | require_backup=true 时按数据年龄拒绝过期备份；新上传不能刷新旧数据的 RPO。坏收据不崩溃、不算成功；完整有效正向夹具可通过。关闭备份要求保留兼容行为。 |
| HEALTH-06 | W+L | 数据库缺失、schema 不符、intelligence disabled、maintenance，以及完整健康库分别走普通 health 和 --readiness。 | 缺库不创建文件、不自动迁移；生产 readiness 拒绝 disabled 和 maintenance。普通 health 的既有 disabled/maintenance 退出语义保持兼容；完整正向夹具退出 0。 |

HEALTH-01 与 HEALTH-03 是本轮必须新增的缺陷回归。HEALTH-02/04/05/06 优先扩充或复用现有测试，避免重复实现同样断言。

不要为了满足新 readiness 而删除 expected_roles、关闭 require_backup，或关闭用户确实要求的来源检查。测试配置可以关闭无关指标以隔离单个断言；最终组合测试必须开启实际发布策略。

## 8. 恢复与首次安装权限 — PERM

定位：

- C:/Users/DELL/Desktop/TrendRadarpoi-master/trendradar/ops/backup.py
- C:/Users/DELL/Desktop/TrendRadarpoi-master/trendradar/ops/database.py
- C:/Users/DELL/Desktop/TrendRadarpoi-master/scripts/deploy/install_release.sh
- C:/Users/DELL/Desktop/TrendRadarpoi-master/deploy/systemd/trendradar-bot.service
- C:/Users/DELL/Desktop/TrendRadarpoi-master/deploy/systemd/trendradar-backup.service

PERM 用例必须在 L 层执行。先记录真实测试服务 UID/GID；若环境不支持用户身份切换，记为 BLOCKED，不能用 chmod 位检查代替全部验证。

| ID | 环境 | 操作与输入 | 必须通过的断言 |
| --- | --- | --- | --- |
| PERM-01 | L | 服务账号拥有既有 intelligence、ai_frontier 和 legacy 库；root 调用真实 backup restore/activate。覆盖服务账号独占 0600 和服务组可读写 0660 两种受控策略。 | 发布后的每个数据库具有正确 owner/group/mode；服务 UID 实际 SELECT、写入并提交成功，WAL 模式工作正常；其他无权限账号无法读取。不能留下 root 独占的 0600 数据库。 |
| PERM-02 | L | 临时 runtime/output 中不存在数据库，通过首次安装路径创建和迁移两类库，然后使用服务 UID 打开。 | 父目录、数据库和锁路径均符合服务账号运行需要；readiness 不依赖 root 的访问能力。root 侧 schema check 成功而服务启动 PermissionError 属于失败。 |
| PERM-03 | L | 分别由安装器创建发布前快照、由备份服务身份创建日常快照；fake restic 在规定账号下读取本次完整快照。 | 每种快照能被其实际使用者完整读取；服务账号能继续创建下一次日常快照；无全局可读的数据库或凭证目录；不以 root 的 fake restic 成功替代服务身份。 |
| PERM-04 | L | 在应用目标元数据、复制文件、切换前分别注入权限错误或 I/O 错误，覆盖新库和已有库。 | 失败退出；旧数据保留或可按 journal 明确恢复；guard 保持；不会发布“complete”但服务无法访问的库；不得递归修改无关目录权限。 |

建议实现方向是“以规定服务身份操作运行数据”或“发布前显式设置并验证目标元数据”。本计划不限定具体实现，但要求上述行为；切换后再盲目递归 chown 不能替代失败路径设计。

## 9. 部署与恢复中断保护 — GUARD

定位：

- C:/Users/DELL/Desktop/TrendRadarpoi-master/trendradar/ops/maintenance.py
- C:/Users/DELL/Desktop/TrendRadarpoi-master/trendradar/ops/backup.py
- C:/Users/DELL/Desktop/TrendRadarpoi-master/scripts/deploy/install_release.sh
- C:/Users/DELL/Desktop/TrendRadarpoi-master/tests/deployment/test_restore_recovery.py

### 9.1 测试前先明确状态约定

这里的状态约定是待实现、待验证的行为，不是声称现有代码已经满足。

| 场景 | 业务启动/接收/消费/外发 | readiness | 处置要求 |
| --- | --- | --- | --- |
| 正常运行，无未完成事务 | 按角色配置运行 | 条件满足可 ready | 无额外操作 |
| 发布停写、快照、迁移、切换阶段 | 被保护 | 不应 ready | 保留可识别的事务记录 |
| 受控 resume/verify，部署控制流程仍有效 | 只按明确的受控恢复协议运行 | 可验证候选版本 | 先持久化业务边界，再允许业务恢复 |
| resume/verify 中断或控制状态失效 | 禁止无审查地重新启动或继续接收新任务 | 不应 ready | 保留保护，识别需要人工处置的事务 |
| 恢复事务未完成或记录无效 | 被保护 | 不应 ready | 禁止通用 clear 直接解除 |
| finalize 已成功持久化但标记清理未完成 | 进入明确的完成确认流程 | 重新核对状态 | 不能只因残留文件永久卡住，也不能仅凭文件名自动放行 |

不能简单让“只要 deploy-in-progress.json 存在就永远阻塞所有角色”：安装器在 readiness 成功后才删除它，这会造成正常部署永远无法完成。应设计受控 resume 与中断恢复的可验证规则，并同时测试成功和中断路径。

若实现依赖租约、控制进程存活或 watchdog，应记录检测上限并使用受控时钟验证；不能只依据 state=verify 字符串长期放行。状态中的 PID 必须指向其声明的真实控制对象，不能把已经退出的辅助写文件进程当成活跃 installer。

### 9.2 必测场景

| ID | 环境 | 操作与故障点 | 必须通过的断言 |
| --- | --- | --- | --- |
| GUARD-01 | W+L | 写入发布各阶段的真实格式事务；在没有 restore-guard 的情况下分别启动 Bot、Worker、Scheduler、collector 的入口或真实 guard 调用链；补充无效 JSON/未知状态。 | 未受控的未完成事务仍阻止业务；无效记录按保护处理；外部调用为零。正常已完成状态及有效受控 resume 的正向路径可执行，不产生永久阻塞。 |
| GUARD-02 | W+L | 构造未完成的真实恢复事务，再调用公开 maintenance clear；覆盖 prepared/installing、损坏或非对象 journal。 | clear 非零失败并说明需恢复；guard 与事务证据保留；角色仍不能处理业务。完成或经验证已回滚后才能解除；不能仅检查 activate_restore 拒绝重试。 |
| GUARD-03 | L | 真实执行 installer，在清除 guard 前、清除后但启动前、首个角色启动后、readiness 验证期间分别强杀；重建进程，模拟自动服务重启。 | 持久化的业务边界不落后于实际放行；中断被识别；角色重启继续受保护，不能因 guard 文件已删而直接工作。保留旧/新 release、快照和阶段证据。普通异常与 SIGTERM 另做对应参数。 |
| GUARD-04 | L | 一个角色启动成功后，另一个启动失败；另测 readiness 一直失败、超时和健康命令异常退出。 | 安装器非零退出；已启动的受管业务停止或按保护协议停止接收/处理；保护保留。越过业务边界后不自动覆盖数据库；边界前需要回退时恢复一致的代码、数据和 release 身份。 |
| GUARD-05 | L | 多库真实 activate 子进程在“操作计划已持久化、旧库已移走、新库已放置、第一库完成而第二库未完成”等位置强杀；WAL/SHM 使用真实 SQLite 夹具。 | 不依赖 except/finally；journal 足以定位原文件、保留文件、目标与已安装集合；pending 可见且角色被保护；不存在误报 complete 的混合数据状态。对声明支持的恢复路径执行完整重放或回退。 |
| GUARD-06 | W+L | 对实际中断产生的 journal，按实现提供的恢复程序或精确运行手册执行；再对相同中断状态重复操作。使用 pre-restore 快照，并覆盖恢复前某个目标库不存在的情形。 | 数据恢复为明确的一致集合；不存在的目标不能悄悄残留为新版本；所有映射、schema 和内容匹配；重复操作不再次破坏数据。解除保护前复核齐全。当前只有 recovery-status 不能自动视为已完成恢复。 |
| GUARD-07 | L | 正常部署完全通过；另在 finalize 持久化后、删除活动标记前终止，再按明确完成确认流程恢复。 | 成功路径确实可 finalize，身份与数据不漂移；残留标记可以被安全核对和处理；不会把真正未完成事务误判成成功。禁止测试直接 rm 标记来制造通过。 |

GUARD-03/05 是本轮关键：至少提供一次真实子进程强制终止的证据。手工预置一个 JSON 文件只能证明解析和拒绝逻辑，不能关闭这两项。

GUARD-06 的恢复接口由 agent 根据现有实现确定。新增 CLI 必须先实现并测试；不得在验收文档中编造当前不存在的 resume/rollback 命令。

## 10. 已修复控制的回归与 Linux 组合验证 — RG

| ID | 环境 | 操作与输入 | 必须通过的断言 |
| --- | --- | --- | --- |
| RG-01 | L | 用受控输入执行 workflow 中实际校验片段及固定入口：合法部署路径/release_id；相对路径、目录穿越、空白、引号、分号、反斜杠、换行、非法 release 字符；host key 不匹配。 | 非法输入在远端变更前拒绝；合法输入能到达预期步骤；校验不执行输入里的文本；固定入口保持 root 控制，部署包不能替换实际执行的 installer。真实 SSH host key 链路另由 V-02 验证。 |
| RG-02 | L | 用小型真实 archive/manifest 测试 SHA 不符、release 不符、dirty 候选、越界成员、符号链接和合法包。 | 无效包在迁移与切换前拒绝；不能写出暂存边界；合法包可继续。生产默认拒绝 dirty；测试如需使用离线 dirty 包，必须独立标记，不能计入生产候选证据。 |
| RG-03 | L+S | 同时模拟或实际运行 Bot/Worker，以及 scheduler、main/AI collector、health、backup 的 oneshot 与 timer；在停写过程中触发一个 timer 到期。 | 快照/迁移前所有受管写入者停止；timer 不重新拉起写入者；只恢复事先 active 或明确配置的初始单位；原本 inactive 的单位不被意外启用。stub 顺序测试与真实 systemd 结果分别记录。 |
| RG-04 | L | 用干净候选打包；新建空 venv，按 requirements.lock 和项目安装步骤安装；离开 checkout，unset PYTHONPATH，用安装产物导入 trendradar/mcp_server、执行离线 CLI 和 release smoke。 | 目标 Python 版本下真实依赖安装与 pip check 成功；包无运行数据库、真实 .env 或缓存；从独立工作目录可运行；负向 readiness 不创建数据库。Windows 安装或 --no-deps 的 dry-run 不能替代本项。 |
| RG-05 | W+L | fake restic 正常成功、非零退出、超时、派生子进程不退出；输出内放入合成 secret sentinel。 | 失败和超时有界结束且无测试子进程残留；不生成成功收据；成功收据绑定 backup_id、manifest digest、远端 snapshot 标识与数据时间；日志中没有 sentinel。 |
| RG-06 | W+L | 修复完成后运行部署/角色重点测试，再运行完整 tests；按变更路径运行 Ruff、编译检查及 diff 检查。 | 无新增失败或未解释 warning；保留 Intelligence-off、Lark-off、角色隔离、完成事件去重、保存回复后重试、重连界限等既有行为。全部业务 provider 均为 mock/fake。 |
| RG-07 | S | 在真实 systemd 的隔离环境校验 units；用受控 helper 接收备份 unit 参数，分别测试默认值与环境覆盖；验证 release.env 与实际服务身份读取。 | 默认 timeout=900、kill-grace=10 正确传参，覆盖值生效；服务组读取 release 身份成功；unit 启停行为与退出结果正确。只做 YAML 解析或搜索字符串不算通过。 |

RG-04 的 Python 版本至少覆盖当前 workflow 声明的 3.10；若 VPS 实际选用其他版本，在拿到主机信息后增加该版本。不要提前假定锁文件在所有 Python/OS 组合均可安装。

当前工作区仍为 dirty，且本任务不授权提交。可以先用明确标为 dirty 的本地包验证安装机制；但 RG-04 的干净生产候选部分应保持 BLOCKED，直到有获准形成的候选版本。不得修改 manifest 的 dirty 标志、删除用户改动或绕过安装器检查来制造通过。

RG-07 的 helper 只能部署在可销毁环境，不能修改真实生产 unit。实际 backup unit 对 fake restic 的集成应保留真实参数和进程退出语义。

## 11. 等主机信息补齐后的验收 — V

以下六项先保留 NOT_RUN/BLOCKED。它们不阻止开始前述 28 项测试，但在完成前不能宣布“Phase 7 已部署验收完成”。

| ID | 场景 | 必需证据与通过标准 |
| --- | --- | --- |
| V-01 | VPS preflight | OS/架构、Python/SQLite、systemd/cgroup、内存/swap/磁盘/inode、服务账号和目录权限、现有调度器、DNS/TLS/WSS 可用性。实际值与部署要求相容；旧 cron/Docker/Actions 的重复运行范围已处理。 |
| V-02 | GitHub → SSH → 固定 installer | 在已配置的目标/Environment 上跑完整工作流；记录唯一 revision、artifact SHA、manifest、固定入口的 owner/mode、受控 sudo 范围和 host key。错误 key 必须失败；成功部署的 revision 与测试/构建对象一致。 |
| V-03 | 真正的安装、升级与失败处理 | 目标服务身份下完成首次安装及升级；记录 current、release.env、角色心跳、队列和 readiness。先在可恢复的验收范围演练启动失败/超时；验证 guard、停写和回退边界，不在唯一生产数据上做故障试验。 |
| V-04 | 远端备份与隔离恢复 | 完成真实 restic 上传，从远端取回指定 snapshot，在隔离目标恢复全部库；校验 schema、业务标识、权限、cutover 与 journal。仅有上传成功收据不能算恢复验收。 |
| V-05 | Lark 现场遗留项与角色协作 | 经授权的测试范围验证 Bot→持久化→Worker→实际收件；完成 C3 真实网络中断/恢复及 C4 收件确认。保留已接受的 B6 跳过状态；若有同 event_id 重传证据，再验证已完成事件抑制，不声称平台级 exactly-once。 |
| V-06 | 持续运行与资源 | 至少 48 小时，并覆盖两个实际日推送窗口及一次受控故障恢复。记录 cgroup 峰值、OOM/重启、队列等待、来源新鲜度、备份年龄、实际收件和重复情况。满足所配置阈值，无未解释中断或未恢复积压。 |

VPS host、port、user、path、SSH key、known_hosts、GitHub Environment、运行配置和备份凭证后续提供；不要在计划或测试产物中填入凭证值。

## 12. 推荐实施顺序与停止条件

### 第一步：添加能失败的行为回归

顺序：ENV-01 → HEALTH-01/03 → GUARD-01/02 → PERM-01。

记录当前缺口，不先批量修改所有文件。每个失败应能由对应原因解释；若某项在最新源码已通过，保留正向/反向覆盖并注明版本变化。

### 第二步：按依赖顺序修复并扩充同组测试

1. 配置和路径统一：完成 ENV。
2. 状态协议和 guard：完成 GUARD 的正常/失败路径设计。
3. readiness：完成 HEALTH，组合验证 guard 不造成正常发布永久失败。
4. 数据文件元数据与实际服务身份：完成 PERM。
5. 使用同一候选运行 RG。

权限和中断测试涉及替换数据库与服务身份，必须在隔离环境做；它们可以在拿到 VPS 参数前完成。

### 第三步：最终回归一次

局部修复迭代使用聚焦测试；全部修复合并后，对最终版本做一次完整回归。只有发生新的实质变更或出现未解决风险时才重跑对应范围。

不要为了增加测试数量而重复写字符串断言，也不要为了得到一个绿色数字反复重跑相同失败而不定位原因。

### 第四步：冻结证据并进入目标验收

满足下节 G1/G2 后再将结果写入验收记录。真实目标相关项仍保持待执行，待参数齐全后按 V-01～V-06 执行。

若出现运行数据库路径误指、真实网络调用、非测试 PID 被命中、错误数据覆盖或测试前后出现无法解释的文件变化，应立即停止该轮并保留证据；不得继续测试扩大影响。

## 13. 发布门槛

| 门槛 | 可以给出的结论 | 必需条件 |
| --- | --- | --- |
| G1：逻辑回归完成 | 本轮已知逻辑缺口已修复并有回归测试 | ENV/HEALTH/GUARD 中可在对应环境执行的行为断言通过；真实模块/CLI 覆盖；没有用 xfail/skip 掩盖必测分支 |
| G2：Linux 离线部署验证完成 | 可进入受控 VPS 验收 | 全部 28 项场景完成所需 W/L/S 证据；实际服务 UID 权限、强杀恢复、真实安装产物与 systemd 检查通过；最终完整回归通过 |
| G3：Phase 7 目标验收完成 | 可按记录确认目标部署和运维验收 | 六项 V 场景全部满足，遗留 live 例外单列；至少 48 小时与两个日推送窗口证据完整 |

Linux 环境缺失时，可以完成 W 层并交付结果，但 G2 必须保持 BLOCKED。不能把 Linux-only 的 pytest skip 算成该场景通过。

已接受的现场测试例外应记录“跳过/未验证及影响”，不能为了关闭 G3 把例外改成“通过”。若最终决定保留其他风险，需要具体列明，不能写成“全部完成”。

## 14. 文件布局和命令

### 14.1 已存在并建议扩充的测试

| 文件 | 本轮职责 |
| --- | --- |
| C:/Users/DELL/Desktop/TrendRadarpoi-master/tests/deployment/test_health.py | HEALTH 各正反向条件及真实 CLI 结果 |
| C:/Users/DELL/Desktop/TrendRadarpoi-master/tests/deployment/test_restore_recovery.py | pending 处理、实际中断 journal 与一致恢复 |
| C:/Users/DELL/Desktop/TrendRadarpoi-master/tests/deployment/test_backup.py | 快照、恢复内容及多库映射 |
| C:/Users/DELL/Desktop/TrendRadarpoi-master/tests/deployment/test_offsite_backup.py | fake restic、超时、子进程与收据 |
| C:/Users/DELL/Desktop/TrendRadarpoi-master/tests/deployment/test_deployment_contracts.py | 保留必要静态合同检查，不将其当行为证据 |

### 14.2 建议新增的测试文件

以下路径是建议新增，不能声称当前已存在；也可按项目现有组织方式合并。

- C:/Users/DELL/Desktop/TrendRadarpoi-master/tests/deployment/test_installer_behavior.py
- C:/Users/DELL/Desktop/TrendRadarpoi-master/tests/deployment/test_runtime_guards.py
- C:/Users/DELL/Desktop/TrendRadarpoi-master/tests/deployment/test_restore_permissions_linux.py
- C:/Users/DELL/Desktop/TrendRadarpoi-master/tests/deployment/test_release_install_linux.py
- C:/Users/DELL/Desktop/TrendRadarpoi-master/tests/deployment/test_systemd_contract_linux.py

Linux/root/systemd 条件须明确标记并在缺少条件时报告原因，同时给出真正运行这些用例的 job。marker 或 job 名由实现新增后再写入命令，不引用尚不存在的测试开关。

### 14.3 可使用的现有命令

先在 PowerShell 进入项目，再逐条执行；每条都检查退出码，不要让后一个成功掩盖前一个失败。

~~~powershell
Set-Location 'C:/Users/DELL/Desktop/TrendRadarpoi-master'

git -c safe.directory=C:/Users/DELL/Desktop/TrendRadarpoi-master rev-parse HEAD
git -c safe.directory=C:/Users/DELL/Desktop/TrendRadarpoi-master status --short --branch

python -B -m pytest tests/deployment tests/integrations/feishu/test_phase7_roles.py -q -p no:cacheprovider
python -B -m pytest tests -q -p no:cacheprovider

python -m ruff check trendradar/ops trendradar/core/heartbeat.py trendradar/core/locking.py scripts/deploy tests/deployment
python -B -m compileall -q trendradar mcp_server scripts/deploy

git -c safe.directory=C:/Users/DELL/Desktop/TrendRadarpoi-master diff --check
~~~

Ruff 范围应补上实际修改的其他 Python 文件。全树存在历史 lint 债务，不要为本轮清理无关文件。

Bash 语法检查仍保留，但必须理解它只证明语法：

~~~bash
bash -n scripts/deploy/install_release.sh
bash -n scripts/deploy/linux_smoke.sh
bash -n scripts/deploy/release_smoke.sh
~~~

Linux 产物测试应通过专用临时 harness 执行，不能把上面的 Windows 路径直接当作 Linux 路径。真实服务、路径和账号在 L/S 环境内单独配置。

## 15. 证据模板与交付要求

每个场景至少记录如下字段。建议使用独立 evidence 目录；目录由执行 agent 创建并记入报告，不复用 test/runtime。

~~~yaml
case_id: HEALTH-01
result: NOT_RUN
source:
  git_head: 待执行时填写
  worktree_dirty: 待填写
  tested_file_hashes: 待填写
environment:
  layer: W/L/S/V
  os: 待填写
  python: 待填写
  sqlite: 待填写
  uid_gid: 不适用或待填写
execution:
  command_or_test_node: 待填写
  fault_point: 无或明确位置
  config_public_keys: 仅非敏感值
  exit_code: 待填写
assertions:
  expected: 待填写
  observed: 待填写
  provider_calls: 待填写
  send_calls: 待填写
evidence:
  log_path: 待填写
  journal_path: 不适用或待填写
  db_content_check: 不适用或待填写
  ownership_check: 不适用或待填写
limits: 待填写
~~~

允许状态：NOT_RUN、PASS、FAIL、BLOCKED、WAIVED。WAIVED 必须关联既有明确决定或本次具体接受的例外；不能由执行 agent 自行把失败改为豁免。

执行 agent 最终交付：

1. 仅涉及本轮修复和测试的变更清单。
2. 五个缺口 F-01～F-05 的修复前失败与修复后通过证据。
3. 28 项测试场景逐项结果；参数化测试注明覆盖的输入集合。
4. 真实 Linux 账号访问、强制终止、恢复一致性、干净安装和 systemd 证据。
5. 最终全量 pytest、Scoped Ruff、编译与 Bash 检查结果及版本标识。
6. 六项 V 场景的当前状态和缺少的条件，不能预填 PASS。
7. 验收文档、remediation 记录及规划状态中与本轮有关的准确更新。

需要同步的现有记录：

- C:/Users/DELL/Desktop/TrendRadarpoi-master/docs/phase7-acceptance.md
- C:/Users/DELL/Desktop/TrendRadarpoi-master/docs/phase7-remediation.md
- C:/Users/DELL/Desktop/TrendRadarpoi-master/docs/deployment.md
- C:/Users/DELL/Desktop/TrendRadarpoi-master/.planning/phases/07-deployment/07-VERIFICATION.md
- C:/Users/DELL/Desktop/TrendRadarpoi-master/.planning/STATE.md

不要把历史 531 passed 覆写成新增测试数量，也不要把测试计划的存在写成测试通过。状态更新必须由执行证据驱动。

## 16. 可直接交给执行 agent 的任务说明

请按本计划处理 TrendRadarpoi 的 Phase 7 测试与整改。先读取当前 AGENTS.md 和工作区实际源码，保留既有改动与所有运行数据。

先用行为测试复现 F-01～F-05，再修复并补齐 ENV、HEALTH、PERM、GUARD、RG。不要以脚本字符串断言替代安装器执行，不要以手写中断 JSON 替代实际强制终止，不要以 root 能访问替代服务账号能访问。

在无需 VPS 参数的范围内完成 Windows 和可销毁 Linux/systemd 验证。当前若没有相应 Linux 能力，完成可执行部分并明确标记其余场景 BLOCKED；不得虚构现场或跨平台结果。

业务 provider、Lark、collector 和 restic 远端默认使用 fake。不得启动第二个真实 Bot，不得触碰现有 output/test/runtime，不得自动提交、推送或部署。

最终按本计划证据模板报告逐项结果、版本、剩余阻断及 V-01～V-06 的状态，并据实更新验收记录。

