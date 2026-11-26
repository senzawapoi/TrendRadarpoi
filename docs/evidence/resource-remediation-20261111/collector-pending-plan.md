# 两个采集器的待执行/合并语义补充计划（待评审，不实施）

前置：Task 5 D5 BLOCKED，默认等待0。撤回旧计划引用的唯一精确丢失次数；本机255实际会在服务结束后立即重臂逾期calendar。该能力不是逐刻度持久队列、FIFO或生产来源新鲜度保证。超容量证明独立成立：每120分钟两次55分钟main加一次18分钟AI需要128分钟串行业务时间。

范围仅 main/AI、现有同 OS collector.lock；不增加平台队列，不改timer、频率、预算、provider并发或Bot/Worker。

1. 先只读冻结目标主机的实际systemd版本、timer/drop-in、时区、Persistent、accuracy、重臂语义和boot/维护区间；绑定既有freshness阈值与真实运行时长。本机255结果不能代替目标事实。
2. 明确一次逾期重臂能覆盖哪些名义刻度。若最新快照允许合并，应明确最早/最新刻度、covered_count、实际started/completed和来源freshness；一次重臂不能宣称历史每次抓取都执行。若要求逐刻度执行，2×main+AI>120的持续负载直接阻断。
3. 是否需要每角色至多一个运行和一个持久pending，须先评估systemd现有逾期重臂与跨重启/维护恢复缺口，不能因为旧错误模型就默认新增队列。确需持久记录时，独立短触发入口、原子记录、崩溃恢复和覆盖语义需单独规格评审。
4. 设计公平性时考虑1秒抢锁轮询与新重臂任务抢先，不能假设FIFO。明确重启、维护fence、未知完成结果不重放、磁盘满/权限失败和时间调整的行为；不写live intelligence DB，不用延长锁等待制造容量。
5. 复用8组条件模型并增加角色相位、deadline同刻、wake/rearm竞争及真实缩时systemd。审计窗口内与窗口后排空分别对账 expected=completed+coalesced+timeout+pending；真实来源SLO单独验收，不能把有限窗口后排空当长期稳定。
6. 下一方案先规格/质量评审，再另行授权实施及启用。若无法满足原名义周期和freshness，继续BLOCKED，不改时刻、不无限等待、不静默丢弃。

本文件只提出后续设计，不授权 durable queue、unit/timer/env修改或上线。
