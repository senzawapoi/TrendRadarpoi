# Task 5 采集等待决策（逾期重臂修订）

日期：2026-11-13。置信度：helper/入口和本机逾期重臂行为 High；模型各情景条件性计数 High；精确生产次数、有效历史日程、来源新鲜度 Unknown。

**D5 = BLOCKED。默认等待保持 0，1800 秒不启用。** 本轮没有发布、提交、VPS/provider/live DB 操作，未改生产 unit、timer、预算或环境。旧版精确结论“55/18 时 main 合并6次”“55/35 时 main 必然超时11次”均撤回，不可作为已验证事实。

## 修订原因与实际 systemd 证据

旧模型把 active 期间全部名义触发直接丢弃，并只在下一名义时刻再启动，漏掉服务进入 inactive 后的逾期立即重臂。旧脚本、JSON、决策和补充计划已完整保存为本地 task5-*-withdrawn-v1.*；它们只作历史证据。

本机为 systemd 255.4-1ubuntu8.18。[官方 v255 timer.c](https://github.com/systemd/systemd/blob/v255/src/core/timer.c) 中 timer_enter_waiting 使用 last_trigger 计算下一 calendar，timer_trigger_notify 在目标 inactive 后重入 waiting；不是为每个错过的刻度创建一个进程。[官方 timer 手册](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html#DeferReactivation=) 解释默认逾期立即再触发；DeferReactivation 选项在257才加入，不能假称本机255启用了它。

四份原有真实 fixture 的结束→下一轮开始间隔为约0.047–0.069秒。质量评审额外注入0.6秒Python启动延迟，复现旧测试把及时systemd激活误判为失败；该原始fixture日志保留。修订fixture采用5秒calendar、6.2秒业务体、明确0.6秒启动延迟，读取systemd的InactiveExitTimestampMonotonic，以实际服务激活而非Python日志时间验证早于下一5秒名义刻度；不再要求小于0.5秒。独立回归证明延迟Python记录可通过，而只在下一名义刻度激活必须失败。测试将同一条件模型应用于激活至结束的完整时长，验证逾期重臂关系。fixture等待上限40秒。隔离 UUID unit、nobody、PrivateTmp=true、/var/lib 解释器及755/644 fixture保持。journal、状态、事件、模型对应在本地 task5-systemd-*。

这是本机机制证据，不证明 VPS 版本、drop-in、timer offset、accuracy 或历史 calendar；这些仍为 Unknown。

## 模型边界与对账

模型实现位于已纳入 privileged CI 的 tests/deployment/test_collector_wait.py，避免 CI 依赖忽略目录。复算驱动与完整逐刻度明细为 output/resource-remediation-20261111/task5-timing-audit.py/.json。

采用 main 每小时 :30、AI 偶数整点 :00 模板；生成[0,1440)分钟刻度，1440时记录 pending，然后停止新增刻度并排空全部在途/逾期待执行工作，不在窗口边界截断。active 期间的刻度用于审计记账，不代表有实际进程调用；服务结束后一次逾期重臂代表已逾期刻度组，其余记 coalesced。选最早刻度作为记账代表，不能当成 systemd 提供的真实触发身份。

每情景采用与 helper 相同的1秒轮询，不假定释放锁立即移交等待者。分别使用0、0.05、0.2秒重臂开销及 waiter/reactivation 两种同刻事件顺序，共6情景。重新激活者可先于睡眠中的等待者抢锁；恰好达到 deadline 的等待者不再获取。真实 OS 抖动、锁公平、任意相位和延迟未穷举，表内范围只是这6个条件情景的样本范围，**不是全局上下界或生产保证**。

每角色、每情景在窗口和排空后均满足 expected = completed + coalesced + timeout + pending。deferred 与最终结果重叠，started 与 completed 也不能直接加入该等式。范围端点来自不同情景，不可交叉相加。

| main/AI分钟 | 1440时pending：main / AI | 排空completed：main / AI | 排空coalesced：main / AI | 排空timeout：main / AI |
| --- | --- | --- | --- | --- |
| 30/18 | 0 / 0 | 24 / 12 | 0 / 0 | 0 / 0 |
| 30/35 | 0 / 0 | 24 / 12 | 0 / 0 | 0 / 0 |
| 37/18 | 1 / 0 | 24 / 12 | 0 / 0 | 0 / 0 |
| 37/35 | 1 / 0 | 24 / 12 | 0 / 0 | 0 / 0 |
| 55/18 | 1 / 0 | 24 / 7 | 0 / 0 | 0 / 5 |
| 55/35 | 1 / 0 | 13 / 12 | 0 / 0 | 11 / 0 |
| 65/18 | 1 / 0 | 22 / 2–3 | 2 / 0 | 0 / 9–10 |
| 65/35 | 1–2 / 0 | 21–22 / 2–4 | 0–1 / 0 | 1–3 / 8–10 |

所有情景排空后 pending=0；这只表示停止新增触发后的有限集合清空，不表示持续负载稳定。65/35 中同一输入在不同调度情景产生不同结果，直接否定唯一精确次数保证。55/18 中 AI 失败说明不能只报告 main 成功；55/35 中 main 失败也不能被 AI 成功遮蔽。

## 独立容量判断与来源门槛

若要求逐名义触发执行，单共享锁下每120分钟至少需要2×main+AI分钟串行业务时间：30/18=78、30/35=95、37/18=92、37/35=109、55/18=128、55/35=145、65/18=148、65/35=165。这是不含等待和启动开销的工作量下界。大于120的持续输入无法逐触发按原周期清空，与 FIFO、抢锁顺序或 systemd 精确次数无关。低于120只证明未被此必要条件排除，不能证明时延或来源 freshness 合格。

因此保持 **BLOCKED / 生产可靠性未验证**。真实 source_runs、既有 strict health freshness 门槛、有效日程和持续负载仍 Unknown，不因模型或一次本地运行通过。等待不提供持久逐触发队列、公平保证或无限容量。后续仅评审 [两个采集器补充计划](collector-pending-plan.md)。

## 候选实现及验证

helper/两个入口生产代码未因本次审计修订改写。默认0、有限0..1800、只对确认OS争用等待、维护前后检查、业务体异常不重放、固定脱敏元数据、main False与AI0成功判定、正等待timeout非零等既有边界保持。

新增 RED：task5-rearm-red.log，4 failed；旧模型确实没有逾期重臂、窗口pending及deadline边界能力。首轮 GREEN 56 passed（含真实fixture）；新增全8组窗口/排空对账回归后，本模块在此次抖动修复后共66项通过；最终扩展回归197 passed、2条既有Authlib弃用警告，见task5-jitter-focused.log/xml；修复前195 passed保留在task5-rearm-focused.log/xml。完整CI选择测试模块同时运行，不因审计修订改变workflow登记。Ruff和diff check见最终task5-jitter-*证据，上一轮task5-rearm-*亦保留。

质量修复RED：task5-jitter-red.log，2 failed；原注入失败目录及旧断言复算见task5-jitter-injected-proof.json，修订后真实fixture和全部66项见task5-jitter-green.log。生产helper/入口/env未变，D5继续BLOCKED。
