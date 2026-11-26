# Task 6 内存决策：维持当前预算

日期：2026-11-13。决策置信度 High；生产容量及调优收益 Unknown。

**唯一建议：现在维持 MemoryHigh=512MiB、MemoryMax=768MiB、CPUQuota=50%。不实施任何预算变更。** 512→640MiB 仅保留为未来单变量软阈值评审候选，未应用。不得同时改 MemoryLow、MemoryHigh、MemoryMax、CPU、timers、全局 swappiness 或其他应用。Task 5 的 D5=BLOCKED、等待默认0继续有效；内存试验不能绕过其容量、来源新鲜度及真实日程门槛。

## 冻结依据与同刻账本

只读取本地冻结 inputs 和 Task 1 baseline，不访问 VPS、真实配置、provider 或 live DB。正式版本60081d831805的953样本，UTC 2026-11-10 17:00:02.923808至2026-11-11 08:52:04.923500，跨度15.867222小时；不是一次覆盖所有业务的合格压力测试。输入两个 samples 文件的 SHA256 与 baseline 一致；baseline、代码和全部本轮证据哈希见 task6-manifest.json。

主机 MemTotal=1919.754MiB；可用内存最小736.3125MiB。slice memory.current范围395.547–512.066MiB，swap最大644.625MiB。memory.current含多类计费，不能与进程RSS当作同口径总和。RSS包含共享页，RssAnon也不是PSS；PSS/私有足迹 Unknown，本轮未读取smaps。各角色RSS最大值并不必然同刻发生，不能相加推导必需预算。Bot/Worker配置的MemoryLow各200MiB只是尽力保护，不是锁定预留；不能从512中直接扣除400来声称只有112MiB可用。

以下为同一个时间戳的账目（MiB，保留三位；delta为前一有效同boot样本至该时刻的计数增量）：

| UTC时刻 / 活动 | host available / used swap | slice current / anon / file / swap | high delta / refault anon / file |
| --- | --- | --- | --- |
| 11-11 00:11:03.623806 / scheduler（切换区间） | 736.312 / 366.840 | 511.082 / 454.910 / 41.469 / 195.195 | 3781 / 143042 / 27162 |
| 11-11 02:03:04.123443 / collect-main+collect-ai+scheduler | 762.844 / 815.414 | 511.539 / 456.574 / 37.156 / 644.625 | 2270 / 315637 / 0 |
| 11-11 04:32:04.124563 / collect-main | 776.605 / 182.234 | 511.727 / 427.582 / 78.980 / 12.141 | 16066 / 16883 / 1017426 |

对应角色的RSS / RssAnon / RssFile / VmSwap如下（KiB；缺失=Unknown，不能补0）：

| UTC时刻 | Bot | Worker | main | scheduler | AI |
| --- | --- | --- | --- | --- | --- |
| 00:11 | 200320/182196/18124/0 | 199524/181392/18132/0 | Unknown | 99936/81904/18032/33048 | Unknown |
| 02:03 | 200332/182208/18124/0 | 199592/181460/18132/0 | 34056/15592/18464/368840 | 86508/67812/18696/116092 | 31868/14344/17524/30020 |
| 04:32 | 201428/183296/18132/0 | 199696/181564/18132/0 | 134012/115920/18092/5828 | Unknown | Unknown |

完整953条同刻host/slice/所有角色anon、file、RSS、swap、refault/high增量见 task6-same-time-ledger.json；角色计数差分另要求PID/start_ticks一致，缺失、重置或跨身份记null，不补0。task6-memory-ledger.json提供极值同刻记录和活动摘要，task6-build-ledger.py可离线复算（从仓库根目录用runpy.run_path执行）。活动切换单列transition：162个gauge样本含首条无前置区间，只有161个有效delta；其余791个稳定活动区间。计数delta不是每秒速率，sample_mean也不是时间加权均值。

| 稳定区间活动 | n | anon/file/swap样本均值 MiB | high / refault anon / file 区间增量均值 | slice CPU秒增量均值 |
| --- | --- | --- | --- | --- |
| idle | 273 | 356.509 / 82.219 / 0.437 | 131.670 / 316.480 / 6972.648 | 1.856 |
| collect-main | 374 | 444.310 / 47.449 / 273.211 | 2869.733 / 115373.781 / 97632.457 | 24.210 |
| collect-main+scheduler | 120 | 452.175 / 40.527 / 469.455 | 3910.700 / 370107.033 / 37019.075 | 25.388 |
| scheduler | 20 | 452.514 / 42.727 / 189.949 | 3931.550 / 281634.150 / 45657.450 | 22.846 |
| collect-main+collect-ai | 1 | 458.719 / 37.242 / 462.773 | 3530 / 411906 / 10320 | 27.401 |
| collect-main+collect-ai+scheduler | 3 | 454.794 / 37.156 / 628.839 | 1930.333 / 251939.667 / 4290.333 | 28.736 |

activity只是观察到的进程组合，不能证明业务执行成功。正式窗口内没有成功真实AI负载的充分证据；8次锁忙跳过/进程重叠不能算AI业务负载。历史Worker SQLite故障实际根因仍 Unknown；Task 2–4离线修复并未追溯证明历史因果。其他程序的请求延迟/错误SLI Unknown，不能仅用可用内存断言互不影响。

在00:11同刻，前一区间host steal=20.726%、iowait=15.225%，host I/O PSI some avg10=57.31%；它们与slice进程CPU计费是不同观测维度。idle区间host steal/iowait样本均值3.760%/0.843%，main+scheduler为20.148%/31.198%。这些相关变化不能证明是谁导致steal、I/O、SQLite错误或延迟，也不能证明提高MemoryHigh将消除它们。CPU秒增量不能解读成墙钟耗时。

## SDK纯导入实验

脚本 scripts/ops/profile_sdk_import.py 仅标准库驱动，在main guard下动态import lark_oapi；不读取真实配置、不启动Bot、不构造client、不调用网络/API，不升级SDK或安装依赖。仅Linux接受ru_maxrss的KiB口径；其他平台fail closed，已加载SDK的进程也拒绝。导入脚本本身没有SDK副作用。

三个独立新进程使用现有Python3.12.3 venv及现有lock，lark-oapi=1.7.3，各加载10623个lark模块。逐份JSON含版本、PID、脚本/lock哈希、RSS单位和CPU时间：

| 进程 | 导入前 / 后 ru_maxrss KiB | 差值 KiB | import process CPU秒 |
| --- | --- | --- | --- |
| 367 | 20480 / 172400 | 151920 | 1.717725 |
| 368 | 20480 / 172448 | 151968 | 1.021268 |
| 369 | 20480 / 172288 | 151808 | 1.024348 |

证据 task6-sdk-import-{1,2,3}.json。ru_maxrss是进程历史峰值，差值约148.25–148.41MiB只是本机纯导入实验，不是当前私有RSS，也不是每个生产进程可以释放的内存额度。WSL、生产内核及业务执行条件不同。调整SDK加载边界、减少冗余仅为未来工程提案，本任务没有实现或宣称可直接回收该差值。

## 纯策略结果与未来门槛

may_trial(hours,min_available_mib,all_workloads,worker_explained,other_sli_known,oom)只有hours≥6、min_available_mib≥512、三个布尔证据均为精确True、oom为整数0才返回True。缺项、字符串、布尔数值、负值、非有限数及非法类型均返回False；没有subprocess、systemctl、sysctl或网络。阈值是保守评审候选，不是容量保证，也不授予变更权限。

本次实际输入为15.867222小时、736.3125MiB、False/False/False、OOM增量0，结果 **False**。三个False分别表示未证明全部真实工作负载（尤其AI）、Worker历史根因未解释、其他应用SLI未定义/测量。纯策略即使在12小时、736MiB且前两证据True，只要other_sli_known=False仍返回False；测试明确覆盖。

未来必须先验证完整实际负载与headroom，完成Worker根因评审，并冻结其他服务SLI及基线，再另行授权单变量512→640MiB软阈值试验。试验保护候选：host available连续3个样本<384MiB，或出现OOM/其他服务新增错误，停止试验并复核。请求样本<30时延迟p95为Unknown，不能记0；p95退化10%停止阈值尚需冻结口径和批准。以上未应用，不代表已经设计或执行生产验收。

## 离线验证与限制

TDD RED先于策略实现，task6-red.log记录缺模块收集失败；GREEN、CI动态模块覆盖和现有预算合同测试见task6-green-final.log：105 passed，其中新模块73项。新部署模块在privileged CI仅登记一次，Task 1与Task 5登记保留。profile测试使用假的resource/version/import，验证Linux数值输出、禁止重复导入、非Linux拒绝及导入脚本无SDK副作用；三个真实纯导入JSON另行检查。

Ruff、diff check、完整源/证据哈希及自审分别见task6-ruff-final.log、task6-diffcheck.log、task6-manifest.json和task6-selfreview.md。本机离线测试不构成VPS/provider/真实AI/其他服务SLI验收。没有staging、commit、push、部署或配置变更。
