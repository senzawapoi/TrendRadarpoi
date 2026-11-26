# 历史资源采集基线（2026-11-11）

置信度：观测事实高；原因归属低至中。此处仅重算本地保存证据，不表示当前线上状态，也未打开业务数据库、重启监控或访问 VPS。

## 输入保存与审计

原始证据及旧脚本、旧摘要、损坏的 REPORT.md 共 9 个文件逐字节复制至被 Git 忽略的 `output/resource-remediation-20261111/inputs/`，副本权限 0444；未重写原件。SHA256 与字节数见下表。`input-manifest.json` 保存复制时间、采样截止、观测版本和启动信息，仅留本地。旧清单 8 条记录全部匹配，未发现内容或长度差异；旧清单没有自身摘要，这次另行补记。旧脚本和报告属于派生物，不作为原始观测输入。

| 文件 | 类别 | 字节 | SHA256 |
|---|---|---:|---|
| `REPORT.md` | 旧派生物 | 3333 | `43f9d807df4ecf977210913f091fd6c801b25be0158ce77d8751945e3d42d759` |
| `analysis.json` | 旧派生物 | 15298 | `0c91c35fadc3168c30f6c1c55b5402e1cf522b8f4f311e731b25567f1459c233` |
| `analyze.py` | 旧派生物 | 4961 | `089374378f8f645ca23b3a1c2272efa5321672724f0e0db5b5cad5b2e267052a` |
| `files.sha256.json` | 旧派生物 | 1167 | `7c64ec7d981f17eea091289496a723d2d130aae9cef5949c24bd63547e7dad44` |
| `live-status.json` | 原始观测 | 36891 | `61aa4dba4b436cd9e3dcd27e703e64e41c84de33fcbc54e98c8f66d20923e6ce` |
| `recent-health.json` | 原始观测 | 1387 | `d53237b7bba2320a81fd0a93e8bfeb79fc864a2238baa8d7ccf7741191d171e0` |
| `runtime-events.json` | 原始观测 | 16631 | `ce0563e98b7a15c012a131f550bae898f60fed550ded875995fbbb6487bba564` |
| `samples.jsonl` | 原始观测 | 3634492 | `6dbdac959f0cd24995abcbfc2d12e6ae145456ca673d7418aec13d2c6ca2b5d3` |
| `samples.jsonl.1` | 原始观测 | 8384440 | `d59495458c97f32bb8d02abf6f20b000c835c9626614729e509c328cf60a6f05` |

## 范围与方法

原始 JSONL 共 977 行：initial 7、ee395488c7de 10、a9c76e227236 7、正式版本 60081d831805 为 953。正式窗口是北京时间 2026-11-11 01:00:02.923808 至 16:52:04.923500；排除 7 行缺失版本和 17 行其他版本。原件未丢弃。重复、冲突及损坏行均为 0。952 个相邻间隔最大 62.921540 秒，无超过 90 秒间隔。

复算命令（项目 Linux venv）：

```bash
python -B -m scripts.ops.resource_analysis \
  --samples-dir output/resource-remediation-20261111/inputs \
  --events-file output/resource-remediation-20261111/inputs/runtime-events.json \
  --version 60081d831805 \
  --output output/resource-remediation-20261111/baseline.json
```

CPU 以累计 CPU 秒差除以 monotonic 秒差乘 100，单位为单核百分比。逐进程要求相同且有效的 boot/pid/start；版本切换、启动变化、负数/回退/非有限数及缺失计数均记 UNKNOWN，绝不补零。共享 cgroup CPU 计数重置时，该区间共享计数率全部排除。宿主换入换出页按已捕获的 4096 字节页大小换算，不能套用分析机页大小。PSI some avg10 的两个样本占比分开报告：任意停顿使用 avg10>0，原有告警阈值使用 avg10>=10。两者分母均为有效 PSI 样本数；缺失、负值、布尔和非有限值排出分母并另计 UNKNOWN，不补零。样本占比不是精确持续时间或压力大小。

分位数改为 nearest-rank：排序后取 ceil(q*n)-1，空集合返回 None。旧脚本取 floor((n-1)*.95)，且使用采样器已算好的速率并把区间计入右端活动；本次从累计计数重算，只有两端 activity 一致才归稳定组，其余 161 个区间单列 transition。因此旧 P95 不应强行对齐。JSON 中 sample_mean 明确表示有效样本的算术均值；对速率而言，这是区间样本等权均值，不是按持续时间加权的物理平均速率。举例：1 秒 CPU 100% 加 99 秒 CPU 0%，sample_mean=50%，持续时间加权均值才是 1%。nearest-rank P95 仍是样本分位数。版本筛选在完整有效样本时间序列分段后进行；中间被排除的其他版本仍保留边界，不能把 v→w→v 两端拼成跨版本区间。activity 仅是捕获的进程状态标签，不证明执行过实际 AI 工作；整个分钟内短任务仍可能未被采到。

## 两个区间手算

| UTC 区间 | 前累计 CPU µs | 后累计 CPU µs | monotonic 差秒 | 单核 CPU % |
|---|---:|---:|---:|---:|
| 2026-11-10T17:00:02.923808+00:00 → 2026-11-10T17:01:02.823052+00:00 | 254839035399 | 254866681427 | 59.899271260947 | 46.154197569 |
| 2026-11-10T17:01:02.823052+00:00 → 2026-11-10T17:02:02.723956+00:00 | 254866681427 | 254883204896 | 59.900901140179 | 27.584675164 |

公式：(后累计−前累计)/1,000,000/秒差×100。独立核对值与生成摘要一致；详细数值保存在本地 hand-checks.json。

## 观测结果

PSI some avg10 任意停顿：660/953=69.255%；原有告警阈值 avg10>=10：361/953=37.880%。有效 PSI 样本 953，UNKNOWN 0；avg10 P95=28.26%。总 cgroup 内存 P95=511.85 MiB，swap P95=535.69 MiB。

| 活动组 | 有效区间 | CPU P95（单核 %） | memory.high 事件率 P95（次/秒） | PSI some 累计停顿区间占比 P95 | 宿主 swap-in P95（MiB/秒） | 宿主 steal P95（%） |
|---|---:|---:|---:|---:|---:|---:|
| transition | 161 | 48.458 | 118.974 | 0.3003 | 22.560 | 24.475 |
| collect-main | 374 | 49.804 | 191.033 | 0.1978 | 20.038 | 22.770 |
| collect-main+scheduler | 120 | 47.599 | 103.361 | 0.3234 | 35.031 | 24.687 |
| scheduler | 20 | 47.399 | 87.868 | 0.2878 | 21.444 | 24.889 |
| idle | 273 | 6.158 | 0.017 | 0.0002 | 0.000 | 12.800 |
| collect-main+collect-ai | 1 | 44.773 | 57.680 | 0.3253 | 26.677 | 23.937 |
| collect-main+collect-ai+scheduler | 3 | 48.690 | 37.897 | 0.4188 | 20.521 | 26.430 |

PSI 区间占比来自累计停顿 µs 差除以该区间时间，和上面的 avg10 阈值样本比例是不同指标；memory.high 列为事件计数速率；swap-in 为宿主换入字节速率。

Bot 和 Worker 的采样 RSS 分别约 195.5–196.7 MiB、194.5–195.2 MiB。RSS 不能等同 SDK 独占成本，更不能直接相加当作私有内存。

独立 journal 文件覆盖范围比正式采样窗口更宽：Main 17 次开始、16 次服务完成、末轮尚未完成；AI 9 次开始和 9 次服务完成，其中 8 次明确 lock-busy 跳过。唯一未记录跳过的 AI 轮次开始于北京时间 00:00，早于正式采样窗口；Finished 只证明服务结束，不证明产出成功。因此短暂 AI 进程重叠不能作为成功 AI 负载基线。Worker 在完整 journal 中有 2 次退出和 2 次计划重启，其中一次退出早于正式窗口。2 次开始都保留为独立轮次；后续 Started 到来前未捕获完成事件的前一轮保留 UNKNOWN，并注明 completion_not_captured_before_next_start。分类 ledger 和完成轮次仅保存在本地 JSON，未发布消息正文。

历史有效 timer/calendar 未被捕获：预期触发次数、漏触发率及完整 calendar 审计均 UNKNOWN。仅报告 journal 中实际开始，不拿模板推定运行现场。没有请求时延输入，用户请求 P95 为 UNKNOWN。

截至历史健康证据的北京时间 16:56，health 为 degraded，4 个 AI 来源陈旧；delivery completed=1189、backlog=0、failed=0、expired=0。该历史状态不能代表当前线上健康。

## 待验证假设矩阵

| 假设 | 支持 | 反证或限制 | 未知与后续验证 | 置信度 |
|---|---|---|---|---|
| memory.high 引发回收和换页 | 采集组 high 事件率、压力、换入明显高于 idle，和受限 cgroup 一致 | 时间相关不能证明因果；宿主竞争、CPU 配额和应用访问模式并存 | 需受控更改阈值后对比同等完整采集轮次、PSI 和换页 | 观测高，因果中 |
| SDK 驻留开销 | Bot/Worker RSS 均约 195 MiB | RSS 含解释器、其他模块和共享页；无导入前后对照 | 需离线隔离启动/导入剖析及 USS/PSS，不能据 RSS 归因 SDK | 低 |
| idle poll 持有 writer lock | Worker journal 两次退出，历史存在并发角色 | proc/cgroup 无锁持有时长；退出本身不证明是 idle poll 锁冲突 | 需静态路径核查和可控并发事务实验 | 低 |
| collector 饥饿 | 8 次 AI 明确因 collector lock-busy 跳过；Main 轮次长 | 无有效 calendar 记录，不能声称所有应运行的 AI 均已核对；服务 Finished 不证明业务产出 | 消除冲突后需观察真实 AI 完整轮次及来源新鲜度 | 跳过事实高，完整饥饿归因中 |
| steal / 上游耗时 | 采集及 scheduler 活动时 steal 明显；Main 16 个完整服务轮次约 30.4–54.5 分钟 | steal 为宿主统计，不能直接归因本项目；没有逐请求上游耗时 | 需分离 CPU、网络等待、上游重试和虚拟化争用 | steal 事实高，上游归因未知 |

## 验证记录

先写测试并保留缺少模块的初始 red：`task1-red.log`。随后保留行为 red：`task1-red-filter.log`（缺少版本筛选）、`task1-red-gauges.log`（缺少 gauge 输出）。另保留 `task1-red-time-order.log`（混合时区偏移的乱序排序）。初轮 `task1-green.log`：资源分析和 CI 选择范围共 46 passed。规范审查纠正轮先保留 `task1-red-spec.log`（8 failed, 27 passed），然后 `task1-green-spec.log` 共 55 passed，覆盖双压力阈值、嵌套容器类型损坏、合法空进程及显式 UNKNOWN 漏触发指标。质量纠正轮保留 `task1-red-quality.log`（4 failed, 35 passed），最终 `task1-green-quality.log` 共 59 passed，覆盖版本筛选边界、未完成 journal 轮次、sample_mean 标签及超大整数。`task1-ruff-quality.log` 保存最终 scoped Ruff；`baseline.json` 和同名 UTF-8 Markdown 是重算产物，断言“采集”原样往返。没有进行 commit、staging、push、部署、provider 调用、线上数据库读取或 VPS 操作。privileged CI 选择增加该测试一次，用于满足已有动态范围检查；全项目回归由集成阶段统一执行。
