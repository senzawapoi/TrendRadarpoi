# TrendRadarpoi · Phase 7 Codex 交接操作指南

版本：2026-10-15

基线：2026-10-15 对实际工作区的只读核对；本文时间均为 Asia/Shanghai。

工作区：C:/Users/DELL/Desktop/TrendRadarpoi-master

用途：交给本地 Codex 继续修改、验证和整理交接。本文不是新的验收通过记录，也没有执行本文列出的后续命令。

## 0. 本轮任务与边界

**本轮目标：完成 Phase 7 / 07-05 已识别的剩余行为验证，修复被这些测试证实的实际缺陷，完成最终本地回归，并让阶段状态与证据一致。**

当前不是从头重做 Phase 7，也不是重新设计整个部署体系。优先补齐已有测试链，不重新发明框架。

允许在本轮执行：

- 阅读项目约束、计划、实现、测试和已有证据。
- 修改相关测试、必要的最小生产代码及活动交接文档。
- 在现有 Windows / Ubuntu WSL 隔离环境执行离线测试。
- 在明确属于测试的临时目录、子进程和 systemd unit 内进行故障注入。
- 生成明确标为 dirty 的隔离测试产物及新的本地证据。

本轮不包含：

- commit、push、PR、创建发布、触发远端 workflow 或生产部署。
- 使用真实 Lark、Gemini、采集源或远端 restic 做联调。
- 读取、复制或输出真实凭据，启动第二个 Bot，修改现有运行数据。
- 清理用户改动、缓存、历史失败目录、审计包、Linux 工具链。
- 将 PhaseGate Demo 接入设为 Phase 7 的新增强制前置条件。

**缺少提交、远端 CI 或 VPS 授权时，完成可做的本地工作后明确交接；不得为保持“持续推进”而重复相同测试、虚构通过或扩大范围。**

## 1. 接手时必须理解的真实基线

| 项目 | 已核实事实 | 正确解释 |
| --- | --- | --- |
| Git | main；HEAD 5a427aba5ded0c9c9c9e050413dcb41f17fa0e23；领先本地 origin/main 记录 42 个提交；大量 dirty / untracked 文件 | HEAD 不能单独标识本轮修复；未执行 fetch，ahead 不是远端实时状态 |
| 部署目录回归 | 2026-10-14 17:55 完成；466 passed、6 skipped；exit 0；pytest 耗时 1083.62 秒 | 命令覆盖 tests/deployment，不是整个 tests；6 个跳过不是通过 |
| 主会话 | 18:21 已读取上述终态；20:00 记录 interrupted；本次核对未发现后续执行记录 | 不要继续等待历史测试；中断原因未被确认 |
| ENV-03 | loader 已实际打开 CONFIG_PATH 并读取 1 字节；相关 Linux 三模块 48 passed | 已修复，不应按过期文档再次从零诊断 |
| RG-03 | 服务身份、restore guard 权限、回滚租约及严格 false 边界已有修复和专项证据 | 保留历史失败；后续部署全集通过，但仍需逐项核对覆盖和 skips |
| 历史全项目结果 | 2026-10-13 为 531 passed、1 warning | 早于本轮修改，不能冒充当前版本最终回归 |
| 阶段文档 | STATE / HANDOFF 等仍停在 2026-10-14 17:06 左右的旧检查点，继续写 ENV-03 失败 | 优先修正活动状态，不能改写历史失败日志 |
| PhaseGate | Demo portable 报告 15/15 个预期场景符合；fixture=true；production_phase7_verified=false | 样例判定验证，不是实际项目验收；真实项目模板五类检查仍是 manual |
| 发布与现场 | 干净候选、真实 GitHub 执行、VPS V-01～V-06 未闭环 | 不能宣布 Phase 7 已完成目标部署验收 |

已核实的历史部署命令：

~~~powershell
wsl -d Ubuntu --cd /mnt/c/Users/DELL/Desktop/TrendRadarpoi-master --exec /var/lib/trendradar-p7-gap-20261014/venv310/bin/python -B -m pytest tests/deployment -q -p no:cacheprovider --tb=short
~~~

结果来源是本地 Codex 日志中的 CommandExecution 完成事件，exit_code=0，不只是 agent 的口头总结。

主日志定位：

~~~text
C:/Users/DELL/.codex-vscode-api/sessions/2026/09/13/rollout-2026-09-13T17-56-56-01a09872-323f-70f2-9aae-4d467afe46ef_01a09a32-d0de-74e3-9761-bc6265872ee2.jsonl
~~~

只读取需要的事件，不将整份会话、环境或潜在敏感内容复制进报告。历史 session 9378 和 PID 295 不是本次可直接复用或操作的活句柄。

## 2. 阅读顺序与事实优先级

先设置根目录，后续表中的相对路径均相对此目录：

~~~powershell
$ProjectRoot = 'C:/Users/DELL/Desktop/TrendRadarpoi-master'
Set-Location -LiteralPath $ProjectRoot
~~~

按顺序阅读：

1. AGENTS.md、CLAUDE.md，以及实际适用的目录级约束。
2. .planning/PROJECT.md、.planning/REQUIREMENTS.md。
3. .planning/phases/07-deployment/07-CONTEXT.md、07-01～07-05-PLAN.md。
4. TrendRadarpoi-Phase7-实际缺口测试计划.md。
5. docs/phase7-actual-gap-evidence/HANDOFF.md、case-matrix.md。
6. docs/phase7-actual-gap-evidence/env03-readability-fix-20261014.json、rg03-rollback-fix-20261014.json，以及相关终端结果。
7. 本指南第 4 节列出的实际测试与对应生产入口。

若需要改变架构，再按 AGENTS.md 阅读相关 codebase 文档和 docs/intelligence.md；本轮不预设需要架构调整。

判断原则：

- 目标、权限和验收要求来自用户决定与项目约束，不由测试数字决定。
- 当前实现状态以实际源码为准；“是否通过”必须绑定具体版本、命令、环境和断言。
- 活动状态文档与源码、可定位执行结果冲突时，校准状态文档。
- 历史证据保留原日期、原失败和适用范围；不覆盖为新的通过记录。
- 本指南补充接续顺序，不授权放宽已有安全条件或将未验证项改成 PASS。

## 3. H0：建立接续检查点，先消除过期状态

### 3.1 只读确认当前现场

逐条执行并检查退出码；若工作区已变化，先解释差异，再调整本文任务。

~~~powershell
git -c safe.directory=C:/Users/DELL/Desktop/TrendRadarpoi-master rev-parse HEAD
git -c safe.directory=C:/Users/DELL/Desktop/TrendRadarpoi-master status --short --branch
git -c safe.directory=C:/Users/DELL/Desktop/TrendRadarpoi-master diff --stat
~~~

注意：git diff 不包括 untracked 文件内容。当前许多 Phase 7 实现和测试尚未跟踪，必须结合文件清单与哈希识别候选，不能只保存 diff。

检查是否有其他 agent 或测试正在改动相同文件。存在重叠写入时暂停协调，不擅自关闭它们。检查测试进程时只记录必要的 PID、命令类别和归属，不导出完整环境。

### 3.2 校准活动交接

新增一份本轮接续记录，使用实际日期及唯一后缀，不覆盖旧检查点。至少记录：

- 当前 HEAD、dirty 状态、相关文件清单与基线哈希。
- ENV-03 已修复、48 项专项通过的证据位置。
- 部署目录 466/6 已完成，但全项目最终回归尚未完成。
- 本轮四组剩余任务和外部阻断。
- 哪些结论来自直接源码检查，哪些来自历史终端证据。

先更新 STATE / HANDOFF 中会误导执行顺序的关键段落；详细验收表在 H4 统一整理。原测试计划中“先复现并修复 F-01～F-05”的历史顺序，不应让接手者重做已完成工作。

H0 完成标准：下一位 agent 能直接找到正确起点，不会再次等待已结束测试或重新修 ENV-03。

## 4. H1：只补齐这四组剩余验证

下表描述的是已发现的验证不足，不等于已证实存在新的生产缺陷。先加强断言；出现真实失败，再定位并做最小修复。能用已有断言完整证明的项，补映射即可，不重复造测试。

### H1-A：正常完成与受控恢复后，所有角色能够重新运行

对应：GUARD-01，兼顾 GUARD-07。

主要文件：

- tests/deployment/test_remaining_gap_assertions.py
- tests/deployment/test_installer_behavior.py
- tests/deployment/installer_harness.py（仅在共享支架确有需要时调整）

现状：

- test_controlled_or_completed_deployment_reaches_real_entrypoint_sentinels 已覆盖 None、resume、verify、finalize 四个参数。
- None 只代表没有部署标记，不证明执行过真正的 finalize 或回滚确认。
- 正向 sentinel 目前覆盖 collector、AI Frontier、Lark combined；不能据此声称独立 bot、worker、scheduler-once 的入口均已验证。
- assert_restart_protected 已有真实入口反向保护断言，可复用其边界设计。

操作：

1. 在现有支架附近增加或抽取共享的正向入口检查函数。assert_restart_accepting 是建议名称，不是声称现有 API。
2. 使用实际入口 main 和实际 guard 检查；只把客户端、网络、业务循环替换为有界 sentinel。
3. 覆盖 collector、AI Frontier，以及 Lark combined / bot / worker / scheduler-once。
4. 将正向检查接到以下真实完成路径之后：
   - 正常 installer 成功。
   - finalize 中断后的公开完成确认成功。
   - 合法的部署回滚确认成功。
5. 保留有效控制进程下 resume / verify / finalize 的正向测试，以及失效控制器、非法记录的反向测试。

验收：

- 应允许的每个角色实际到达对应 sentinel；不是仅看 read_guard 返回 None。
- 被保护时不能触及客户端、接收、消费、采集或外发边界。
- 活跃 rollback 阶段仍阻止业务，不因新增正向测试而放行。
- 不新增“state=complete 就自动放行”等与现有协议不符的捷径。
- collector.main() 和 AI Frontier main() 按当前真实签名调用；后者通过 sys.argv 传参，不再调用 main(argv) 制造伪失败。

### H1-B：真正崩溃产生的 pending journal 阻止业务入口

对应：GUARD-05，保留 GUARD-06 的恢复一致性覆盖。

主要文件：tests/deployment/test_restore_crash_recovery.py。

现有基础：

- 五个中断点：prepared、operation_planned、old_moved、new_placed、first_complete。
- Linux 实际 SIGKILL；Windows 使用跳过 finally 的突发退出。两者证据分开。
- 已有多库映射、真实 WAL/SHM、schema、父子外键、原本缺失目标及重复恢复检查。

操作：

1. 在真实子进程中断、journal 已出现、recover_restore 尚未调用时，复用真实业务入口保护检查。
2. 为它构造纯测试配置和隔离的 DB / control / lock / health 路径；不要用重新初始化 installer 的方式覆盖崩溃现场。
3. 清理子进程继承环境中的无关配置，并使用合成身份；不要让实际 .env 或外部 provider 参与测试。
4. operation_planned 补断言：计划中的原 DB/WAL/SHM 仍在，计划保留路径尚未出现，尚未发生切换。
5. 继续验证 old_moved 和 new_placed 的实际文件位置、pending 状态、恢复后的完整集合及重复操作幂等性。

验收：

- 所有业务入口在 crash-generated pending 状态下被保护，外部调用为零。
- 不依赖 except/finally 执行清理才能通过。
- new_placed 时目标 DB 已存在且是新放置的文件；不能再次错误要求“所有 original 路径都不存在”。
- 物理 rename 与后续 journal 标志可能处于故意注入的中断窗口；测试应验证可恢复性，不要求错误的瞬时同步。
- 原本不存在的库及 WAL/SHM 在回滚后保持不存在；不能因验证时连接 SQLite 而悄悄创建。
- SIGKILL 结果不能写成断电耐久性验收。

### H1-C：恢复完成后通过公开 maintenance clear 解除保护

对应：GUARD-02。

主要文件：tests/deployment/test_restore_recovery.py。

当前 test_restore_journal_contains_per_database_operations_and_pre_restore_mapping 在成功 activate 后，直接调用内部 clear_guard。

操作：

1. 保留 activate 完成后 guard 仍存在的断言。
2. 增加公开 maintenance.main(["clear", "--database", ...]) 调用及退出码断言，参数以当前实现为准。
3. 验证 journal 已处于允许解除的终态、pending 为空、公开 clear 成功后保护消失。
4. 与现有 prepared / installing / 损坏或非对象 journal 的公开 clear 拒绝测试配对。

验收：正常完成确实可解除，未完成或损坏记录仍拒绝；不能删除 journal 或直接 rm 标记制造通过。

### H1-D：正常发布和 finalize 确认不改变既有双库数据与发布身份

对应：GUARD-07。

主要文件：tests/deployment/test_installer_behavior.py。

现状：正常成功节点及 finalize + SIGKILL 节点仅为 intelligence 数据库种入并比较 deployment_probe。

操作：

1. 使用现有 make_installer(..., ai_present=True)，使两个目标库原本都存在。
2. 在 intelligence 和 AI Frontier 两库分别写入可区分的测试数据。
3. 使用现有 probe 或等效检查记录内容、schema、integrity_check、foreign_key_check。
4. 正常发布按预期迁移版本检查；不允许无解释的数据变化。
5. finalize 中断后，在公开完成确认前后比较两个库，以及 current 链接目标和 release.env 身份。
6. 接入 H1-A 的“确认后入口可运行”检查。

验收：

- 两库的内容和预期 schema、完整性/外键结果正确。
- 完成确认本身不能再次迁移数据、改写 release 身份或切换到另一候选。
- 当前 release / 心跳 / pending 不匹配等负向场景仍拒绝确认并保留保护。
- 已有缺失 AI 库场景继续保留；双库正向覆盖不能替代“原本不存在”的回滚检查。

### 不再扩大成新任务的项目

- 不重复启动 ENV-03、RG-03 已解决根因的全套排查。
- PERM-01 现有 legacy 库覆盖不能擅自升格为额外“必须日期分区”要求。
- HEALTH-04 不新增原计划未要求的 multiple-pending 组合门槛。
- 不要求无依据的全 DDL 等价、额外 installer metadata 故障组合或全仓格式化。
- PERM-04 已有 chown/chmod/copy/switch × 目标存在/缺失的八组合证据；先核对映射，不重复实现。
- 若发现新的真实风险，记录“现象—最小复现—影响—必要修复范围”，再判断是否属于本轮，不能无限外扩。

## 5. H2：按依赖顺序运行聚焦验证

先完成共享支架，再依次处理 H1-A～D。每次只跑受影响节点或模块；全部收口后再跑最终全集。

### 5.1 环境预检

已保留的服务测试解释器：

~~~text
/var/lib/trendradar-p7-gap-20261014/venv310/bin/python
~~~

历史运行环境是 Ubuntu WSL、真实 systemd、root、Python 3.10.22 / SQLite 3.53.1。接手必须重新核对，不把旧版本记录当现场检查。

~~~powershell
python -B -c "import sys,sqlite3; print(sys.version); print(sys.executable); print(sqlite3.sqlite_version)"
if ($LASTEXITCODE -ne 0) { throw 'Windows interpreter check failed' }

wsl -d Ubuntu --cd /mnt/c/Users/DELL/Desktop/TrendRadarpoi-master --exec /var/lib/trendradar-p7-gap-20261014/venv310/bin/python -B -c "import os,sys,sqlite3; from pathlib import Path; print(sys.version); print(sys.executable); print(sqlite3.sqlite_version); print(os.geteuid()); print(Path('/proc/1/comm').read_text().strip()); assert os.geteuid()==0; assert sys.version_info[:2]==(3,10); assert Path('/proc/1/comm').read_text().strip()=='systemd'"
if ($LASTEXITCODE -ne 0) { throw 'Linux acceptance environment is not ready' }
~~~

同时核对 venv 解释器与基础解释器的解析后路径、目录可遍历性及服务 UID 65534 的执行权限。两者都不能位于 /tmp 或 /var/tmp；不能关闭 PrivateTmp 掩盖 203/EXEC。

原 /var/tmp/trendradar-p7-gap-20261014 工具链和 wheels310 保留用于复现/安装缓存，不作为 PrivateTmp 服务解释器。环境缺失时记录 BLOCKED，不偷偷换成 Windows 或 stub 代替 Linux/systemd。

### 5.2 四组相关模块

从项目根目录执行。以下是模块级聚焦命令，不代表它已经在本轮运行：

~~~powershell
wsl -d Ubuntu --cd /mnt/c/Users/DELL/Desktop/TrendRadarpoi-master --exec /var/lib/trendradar-p7-gap-20261014/venv310/bin/python -B -m pytest tests/deployment/test_remaining_gap_assertions.py tests/deployment/test_restore_crash_recovery.py tests/deployment/test_restore_recovery.py tests/deployment/test_installer_behavior.py -q -ra -p no:cacheprovider --tb=short
if ($LASTEXITCODE -ne 0) { throw 'Phase 7 focused regression failed' }
~~~

调试单个问题时，将命令缩小到相关节点；参数化 node id 先从当前收集结果确认，不凭记忆拼写。保持相对测试导入，避免 Linux/Windows 采集差异。

若修改了生产 restore / maintenance / installer 逻辑，再补跑与之相关的 deployment_rollback、restore_durability、restore_permissions_linux、systemd_quiesce_linux 模块；仅新增文档不要求重跑这些模块。

### 5.3 失败分类与退出条件

| 失败类型 | 下一步 |
| --- | --- |
| 真实实现不满足已确认约定 | 保留失败证据，做最小生产修复，重跑受影响范围 |
| 测试接口调用错误、夹具权限错误、断言与中断时点不符 | 修测试并解释原因；不得记成“修复了生产漏洞” |
| 环境缺少 root / systemd / 可执行工具链 | 修正已授权隔离环境，或报告 BLOCKED；不能改断言或扩大 skip |
| 外部授权、目标参数或干净候选缺失 | 记录依赖，转做其余本地任务；全部可做任务完成后停止交接 |
| 相同失败再次出现且无新诊断、代码或环境变化 | 不重复空跑；先定位，无法定位则报告具体阻断 |

长测试启动后保留一个活动句柄，轮询该句柄。工具观察超时不等于测试超时；不要重复启动另一套 installer/systemd 测试。实际完成后记录终态，不再轮询历史句柄。运行期间不编辑本轮正在测试的源码。

## 6. H3：冻结修改，完成最终回归

### 6.1 冻结与结果绑定

所有必要实现和测试修改合并后：

1. 确认没有并行写入者或未结束的相关测试。
2. 对生产代码、测试支架、部署脚本、units、workflow、依赖锁文件及相关配置模板建立清单和 SHA256。
3. 记录项目约束/phase plan 的版本，和代码输入哈希分开保存。
4. 每次最终测试开始、结束后核对测试输入是否变化。
5. 结果记录候选标识：HEAD + dirty 状态 + 本轮文件清单摘要；不得只写 HEAD。

全量测试过程中如输入变化，该结果不能代表单一最终候选。先确认变更，再决定重跑范围；不要把不同版本结果拼接成一次全通过。

### 6.2 Windows 全项目

~~~powershell
Set-Location -LiteralPath 'C:/Users/DELL/Desktop/TrendRadarpoi-master'
python -B -m pytest tests -q -ra -p no:cacheprovider --tb=short
if ($LASTEXITCODE -ne 0) { throw 'Windows full regression failed' }
~~~

### 6.3 Linux 全项目

~~~powershell
wsl -d Ubuntu --cd /mnt/c/Users/DELL/Desktop/TrendRadarpoi-master --exec /var/lib/trendradar-p7-gap-20261014/venv310/bin/python -B -m pytest tests -q -ra -p no:cacheprovider --tb=short
if ($LASTEXITCODE -ne 0) { throw 'Linux full regression failed' }
~~~

这里刻意是 tests，不是 tests/deployment。最终通过数量以真实结果为准，不要求等于历史的 466 或 531。

对两端所有 skips 逐项写明节点、理由和替代环境证据。重点确认 Linux UID、真实 systemd、强杀恢复场景确实执行；Windows 专属进程控制测试由 Windows 结果支持。不能仅凭“无失败”关闭矩阵。

### 6.4 独立的 dirty 产物安装验证

本轮修改测试/打包输入后，应按实际依赖变化判断旧 dirty 包证据是否仍适用。若重建验证，使用独立输出，不覆盖旧 dist 审计包。

先确认 wheels310 目录实际存在并足以安装所需锁定依赖；不可将以下路径存在视为已验证：

~~~powershell
wsl -d Ubuntu --cd /mnt/c/Users/DELL/Desktop/TrendRadarpoi-master --exec /usr/bin/env PYTHONDONTWRITEBYTECODE=1 TRENDRADAR_P7_ARTIFACT_INSTALL=true TRENDRADAR_P7_WHEELHOUSE=/var/tmp/trendradar-p7-gap-20261014/wheels310 /var/lib/trendradar-p7-gap-20261014/venv310/bin/python -B -m pytest tests/deployment/test_release_install_linux.py -q -s -ra -p no:cacheprovider --tb=short
if ($LASTEXITCODE -ne 0) { throw 'Dirty artifact installation verification failed' }
~~~

验证必须是真正空 venv、实际依赖/项目安装、pip check、离开 checkout 且不借 PYTHONPATH 的 smoke。保存 artifact SHA、大小、Python/SQLite、锁文件哈希和真实安装结果。

**dirty=true 必须保留。安装机制通过不关闭 RG-04 的干净生产候选部分。** 不得修改 manifest 标志、删除用户改动或未经授权提交来制造 clean。

如果实际测试实现会覆盖既有审计文件，先将测试输出隔离；不要先运行再补救覆盖。

### 6.5 静态检查与 CI 接线

- 对本轮修改的 Python 文件跑 Ruff，使用 --no-cache；不要修与本轮无关的全仓旧债。
- 做不写 pyc 的 AST/内存编译检查；Python -B 不能阻止显式 compileall 写 pyc，不能把它当作无写入保证。
- 对固定入口、install_release.sh、linux_smoke.sh、release_smoke.sh 做 bash -n。
- 解析三个 phase7 workflow，并校验其中实际 Bash run 块。
- 运行当前 tests/deployment/test_ci_acceptance_scope.py，确认新 helper/测试文件可被收集、实际 CI 选择覆盖了要求；本地 wiring 通过不等于 GitHub run。
- 执行 git diff --check，并为本轮新增的未跟踪文件另做等效格式检查。不得静默忽略未跟踪输入。
- 在 Windows 和 Linux 相应解释器上做 pip check；记录失败和版本，不自动全局升级依赖。
- 核对本轮测试自己的进程与 units 是否正常结束。只处置已确认归属本轮的对象，保留故障目录和证据。

可执行的基础检查：

~~~powershell
python -B -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Windows dependency check failed' }

wsl -d Ubuntu --cd /mnt/c/Users/DELL/Desktop/TrendRadarpoi-master --exec /var/lib/trendradar-p7-gap-20261014/venv310/bin/python -B -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Linux dependency check failed' }

wsl -d Ubuntu --cd /mnt/c/Users/DELL/Desktop/TrendRadarpoi-master --exec /var/lib/trendradar-p7-gap-20261014/venv310/bin/python -B -m pytest tests/deployment/test_ci_acceptance_scope.py -q -ra -p no:cacheprovider --tb=short
if ($LASTEXITCODE -ne 0) { throw 'CI wiring regression failed' }

git -c safe.directory=C:/Users/DELL/Desktop/TrendRadarpoi-master diff --check
if ($LASTEXITCODE -ne 0) { throw 'Tracked diff check failed' }
~~~

不要为了补“最终一次”的字样机械重跑已绑定同一候选的相同范围。只有输入、语义约定、环境或未解决风险发生相关变化时才重跑相应范围。

## 7. H4：逐项证据与文档校准

### 7.1 完成原 28 项的映射，不新增数字目标

按原计划核对 ENV-01～04、HEALTH-01～06、PERM-01～04、GUARD-01～07、RG-01～07。

每项至少填写：

| 字段 | 内容 |
| --- | --- |
| requirement_id | 原计划编号和对应原文要求 |
| candidate | HEAD、dirty、输入清单/哈希 |
| environment | Windows / Linux / systemd；Python、SQLite、UID；真实与模拟边界 |
| command / node | 实际命令、测试节点及参数 |
| assertions | 正向/反向行为、业务副作用、数据/权限/状态不变量 |
| result | PASS / FAIL / NOT_RUN / BLOCKED / WAIVED；精确退出码与 skips |
| provenance | 本轮直接执行、历史终端记录或 agent 报告，不能混为一类 |
| evidence | 日志路径、时间、摘要、必要的产物 SHA |
| limits / next | 未覆盖部分及解除阻断所需动作 |

模块总数不等于场景覆盖；重叠命令计数不相加。已有充分证据可被引用，不为凑数重做。28 项是原计划的核对范围，不是额外架构需求清单。

### 7.2 应更新的活动文档

优先更新：

- .planning/STATE.md
- .planning/PROJECT.md
- .planning/phases/07-deployment/07-05-PLAN.md
- .planning/phases/07-deployment/07-VERIFICATION.md
- docs/phase7-actual-gap-evidence/HANDOFF.md
- docs/phase7-actual-gap-evidence/case-matrix.md
- docs/phase7-acceptance.md
- docs/phase7-remediation.md

再检查 docs/README.md、docs/deployment.md、证据目录 README、codebase/CONCERNS.md 与 TESTING.md 是否仍有会误导接续的“ENV-03 未修复”“测试仍在运行”等当前状态描述。只改需要校准的段落，不无差别重写所有文档。

保留历史失败 JSON、旧 source hash 和旧 cleanup 报告；为本轮新增记录，不用新哈希覆盖旧报告的输入身份。不要全局把 FAIL 替换成 PASS。

### 7.3 /neat-freak 的使用边界

如接续流程使用 /neat-freak，应在行为修复和证据整理后进行有限整理：

- 纯描述、导航、排版变化：检查链接、引用和状态一致性，不机械重跑全集。
- 约束/验收语义改变：重新核对受影响要求，不擅自降低门槛。
- 实现、测试、依赖、units 或 workflow 改变：旧候选证据可能失效，更新输入并重跑受影响范围。
- 不清理 output、test/runtime、dist 审计包、失败目录或 Linux 工具链。
- 之前缓存递归删除曾被策略拒绝；不得换命令或工具绕过。

## 8. 本轮完成标准与外部阻断

### 8.1 可以关闭的本地工作包

只有满足以下条件，才能报告“本轮本地整改与验证收口完成”：

- [ ] H1 四组剩余要求有逐项证据，或以现有等效证据明确说明已覆盖。
- [ ] 所有发现的本轮真实缺陷已修复；没有用 skip/xfail/弱化断言制造通过。
- [ ] 最终 Windows 和 Linux 全项目结果绑定明确候选，skips/warnings 已解释。
- [ ] 必须的实际 UID、systemd、强制终止、恢复一致性场景在对应环境执行。
- [ ] dirty 安装机制的结果与干净候选结论严格分开。
- [ ] 活动状态文档、28 项矩阵、运行证据和剩余门槛相互一致。
- [ ] 用户改动、运行数据及历史证据保留；无未经授权的外部调用或生产变更。

如果仍有本地失败或未验证项，明确列出，不能只因“剩下 CI/VPS”就提前宣布本地完成。

### 8.2 不能在当前授权下关闭的项目

| 外部事项 | 当前应有状态 | 后续需要 |
| --- | --- | --- |
| 干净发布候选 | BLOCKED | 用户批准整理并形成明确提交；候选来源、artifact SHA 和测试对象一致 |
| 真实 GitHub CI | NOT_RUN 或无当前候选证据 | 授权提交/推送或执行 workflow；保存 commit、run、job 和 artifact 对应关系 |
| V-01～V-06 | NOT_RUN/BLOCKED | VPS/SSH/known_hosts、运行配置、备份访问、隔离恢复目标及明确执行授权 |
| Phase 5 C3 | 现场验证仍开放 | 经授权的真实断网/恢复测试 |
| Phase 5 C4 | 收件确认仍开放 | 用户确认实际收到对应日报，不能只凭发送 ledger |
| B6 非白名单分支 | 已接受的跳过 | 保留例外与影响，不改成 PASS |

不要把本轮离线完成等同于 G2/G3 或 DEPL 全部完成。G1/G2/G3 继续按原计划的具体条件判定；缺少干净候选或现场证据就保留相应未完成状态。

受控 Linux 验证无需等待 VPS 参数；是否开展受控 VPS 试运行属于另一次授权决策。即使获准试运行，也不能把试运行自动写成正式目标验收通过。

原 V-06 要求至少 48 小时、两个实际日推送窗口和一次受控故障恢复；不能在本轮离线任务中伪造或缩短成几分钟测试。

## 9. PhaseGate 分支的定位

当前目录 phase-gate-demo 的 portable 15/15 只证明 Demo 预期行为；其中一些场景预期就是 FAIL、BLOCKED 或 REVIEW_REQUIRED。

examples/trendradarpoi/gate.template.json 的五类检查仍是 manual 占位。若用户另行要求真实接入：

1. 从已确认的项目约束与 phase plan 映射真实要求。
2. 接入现有真实测试节点，不复制一份简化业务逻辑冒充被测系统。
3. 绑定候选哈希、环境、断言和 skips；明确语义审查来源与范围。
4. Demo fixture、部分契约验证和完整 phase 验收分别报告。

这属于独立工具工作包。本轮 Phase 7 修复不等待它完成，也不因它的样例通过而减少实际验证。

## 10. 必须立即停止的情况

- 路径指向真实 output、test/runtime、生产备份或非测试数据库。
- 发生真实 provider / Lark / 采集 / 远端 restic 调用。
- 将要操作的 PID、进程组、unit 或目录无法确认属于本轮隔离测试。
- 发现无法解释的数据变化、并行文件修改、凭据泄露风险或用户改动冲突。
- 收到权限拒绝、审批要求或保护策略阻断。
- 需要 commit、push、远端协作或生产操作才能继续。

停止相关动作并保留现场，说明具体阻断和需要的用户决定。不得删除 guard/journal、重置数据库、放宽目录权限、关闭 PrivateTmp、降低断言或更换工具绕过限制。

## 11. 最终交接格式

Codex 最后应输出以下内容，而不是只说“测试都绿了”：

1. 本轮实际修改文件及原因：区分生产修复、测试修正、覆盖补齐、文档校准。
2. H1-A～D 各自的结果、对应节点和证据。
3. Windows / Linux / systemd / dirty 安装各命令的真实 passed、failed、skipped、warnings、退出码与日期。
4. 最终输入清单/哈希和 artifact 标识；声明是否 dirty。
5. 28 项矩阵的未完成项及原因，不将比例称为产品完成度。
6. G1/G2/G3 与 DEPL 状态，明确哪些不能关闭。
7. 下一步只剩哪些具体动作，需要用户补什么或授权什么。
8. 置信度：已执行范围高；未验证现场未知；推断另标。

建议结论形式：

> 本轮本地整改：完成 / 未完成。最终候选：……。Windows：……；Linux：……；跳过项及解释：……。仍开放：……。未 commit、push、触发远端工作流或部署。完整 Phase 7 目标验收尚未完成。

## 12. 可直接交给 Codex 的启动指令

~~~text
请在 C:/Users/DELL/Desktop/TrendRadarpoi-master 按《TrendRadarpoi-Phase7-Codex交接操作指南-2026-10-15.md》继续 Phase 7 / 07-05。

先读取项目约束和当前源码，确认现场是否已变化。已知 ENV-03 已修复，2026-10-14 部署目录回归为 466 passed / 6 skipped；不要按过期 HANDOFF 重新修复它，也不要等待历史 session 9378。

本次授权范围：相关代码/测试/活动文档的必要修改，以及现有 Windows/Ubuntu WSL 中的隔离离线验证。先校准接续状态，再完成 H1-A～D：真实完成后全部角色正向入口、真实崩溃后的入口阻断、公开 maintenance clear 成功路径、双库与发布身份一致性。发现真实实现缺陷时做最小修复。已有等效覆盖则补证据映射，不重复造测试。

局部迭代用聚焦测试；收口后冻结输入，执行最终 Windows/Linux 全项目回归及必要的 UID/systemd/产物安装检查，解释每个 skip，更新 28 项矩阵和验收文档。保留全部用户改动、运行数据、历史失败证据、审计包和 Linux 工具链。不要并发修改同一测试输入，不要重复启动仍在运行的测试。

不得 commit、push、创建发布、触发远端 workflow、部署、调用真实 provider、启动第二个 Bot、读取或输出真实凭据、清理受保护数据或绕过审批。干净候选、真实 GitHub CI、VPS 及 Phase 5 现场遗留项单列为后续阻断。不要把 PhaseGate Demo 接入新增为本轮前置条件。

完成所有可做的本地任务后给出明确交接；若只能通过新授权或目标参数继续，报告具体阻断并停止，不反复重跑。不要将离线收口写成 Phase 7 生产验收完成。
~~~
