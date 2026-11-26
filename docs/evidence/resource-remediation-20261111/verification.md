# Task 7 本地候选整合验证

状态：本地整合、回放和 dirty archive 安装通过；生产门槛保持独立。当前分支为 `fix/resource-remediation-20261111`，
基线 `a13c84e7342c4953b4a65d997d1cd3bbf4a54174`，工作树未提交。
本轮仅使用原生 Ubuntu WSL 的隔离源与 Python 3.12 venv，不操作 VPS、provider 或运行数据库。

## 不可合并的验收层级

- Task 1–6 的阶段测试存在重叠，不累加作为总测试数；本页以新运行的 JUnit 为准。
- D5 为 BLOCKED；默认采集等待为 0。正值 helper 不提供 FIFO、持久待办或容量保证。
  [待办补充方案](collector-pending-plan.md) 尚未实现，不能视作公平性、新鲜度或生产激活验收。
- 内存 `may_trial=false`；实际 AI 并发负载未验证，历史 Worker 原因与其他 SLI 未知。
  共享预算维持 512M/768M/50% CPU。
- 本地 dirty archive 的空 venv 安装不等于 clean candidate；本轮未提交，未触发新的 GitHub CI，
  CI 为 PENDING；未部署，真实投递、48 小时观察及内存试调仍独立验收。

## 证据边界

原始监控输入及数据库只存于忽略的 `output/resource-remediation-20261111/`；
本页只发布计数、状态与哈希，不导出消息正文、凭据或身份。
Story 回放使用闭合备份的独立副本与明确冻结的排名时间；不抓取上游、不调用 provider。
它验证指定输入的身份、成员、标题、聚类与排序一致性，不证明完整采集/翻译/投递流水线。
独立 Worker 的轮询竞争与恢复、维护保护和采集锁边界仍由对应测试覆盖。

## 闭合备份同输入回放（PASS）

备份大小 227237888 字节，流式 SHA-256：
`f0cdfd335234b0b9d30e9296864ae0c94494aa63c8e7b69797d892647d3035d3`，运行前后相同。
旧代码由本地 `git archive a13c84e` 导出；新代码为当前候选，各自使用独立数据库副本。
沿用既有脚本的“每来源最后观测时间前 15 分钟”选样；显式把排名 `now` 冻结为该来源的最后观测时间，
并使用相同 YAML 聚类/排名配置。`StoryService.process(persist=False)` 后构造同样的排名证据。
不持久化 Story，不导出正文；输入、完整 Story（含 ID/成员/标题）、聚类、排序、标题均以摘要比较。

| 输入前缀 | 输入条目 | Story | Cluster | 冻结 UTC 时间 | 旧/新所有摘要 |
| --- | ---: | ---: | ---: | --- | --- |
| `newsnow:` | 101 | 100 | 93 | `2026-11-10T08:30:11.992166+00:00` | 相同 |
| `ai_frontier:` | 459 | 427 | 427 | `2026-11-10T02:00:07.863297+00:00` | 相同 |

四次回放均逐行指纹核对 `lark_instant_batches` 1139 行、`lark_story_deliveries` 23857 行、
`feishu_events` 12 行、`feishu_deliveries` 0 行，前后与旧/新均相同；没有改写冻结批次。
这只覆盖该闭合备份，不代表当前线上库或额外批次。完整摘要在 `task7-replay.json`，
脚本在 `task7-replay.py`，旧源码在 `task7-baseline/`，副本在 `task7-replay-v2-*/`。
回放与测试同时运行时使用 nice 15；耗时只作运行记录，不据此声称性能提升。

辅助回放脚本首轮错误读取不存在的 `observation_count` 列，已改为实际 observation 行数；
失败日志 `task7-replay-first-failure.log` 和首轮副本保留。最初 exec 的 `__file__` 缺失与一次
PowerShell 引号错误亦属辅助编排失败；最终直接从原生 Linux 脚本文件执行成功，没有改产品代码。

## 静态检查（PASS）

基于 `git diff --name-only` 与未跟踪文件枚举的 18 个 Python 路径全部通过 scoped Ruff 和
内存 compile；`git diff --check` 通过。`task7-static.json` 列出精确路径。
`task7-source-freeze.json` 记录 builder 收录的 645 个路径的原始/归档 SHA；仅 shell 按 builder
规则归一化换行，Python 保留原始字节。最终源码绑定和归档对照在测试及安装后补齐。

## 新运行自动化结果（PASS）

| 运行 | passed | skipped | failed/errors | 秒 |
| --- | ---: | ---: | ---: | ---: |
| focused | 1217 | 6 | 0/0 | 703.744 |
| full | 1862 | 6 | 0/0 | 730.784 |
| install | 1 | 0 | 0/0 | 68.653 |

以上运行范围存在重叠，不累加。focused 覆盖 deployment、Feishu integration 与 baseline；full 为 `tests` 全树；
install 单独 opt-in。完整命令与耗时在 `task7-test-receipts.json`；各运行保留 `.log/.xml`。
- focused: `test_popen_failure_closes_windows_job`：Windows Job Object lifecycle
- focused: `test_job_attachment_failure_reaps_the_actual_suspended_process[False]`：Windows Job Object attachment
- focused: `test_job_attachment_failure_reaps_the_actual_suspended_process[True]`：Windows Job Object attachment
- focused: `test_pre_fix_entry_drops_trusted_configuration_and_health_reads_wrong_database`：requires isolated Linux root and explicit retained-audit reproduction
- focused: `test_pre_fix_root_restore_removes_service_ownership_and_readability`：requires isolated Linux root and explicit retained-audit reproduction
- focused: `test_locked_artifact_installs_into_empty_venv_and_runs_without_checkout`：requires opt-in isolated Linux dependency installation
- full: `test_popen_failure_closes_windows_job`：Windows Job Object lifecycle
- full: `test_job_attachment_failure_reaps_the_actual_suspended_process[False]`：Windows Job Object attachment
- full: `test_job_attachment_failure_reaps_the_actual_suspended_process[True]`：Windows Job Object attachment
- full: `test_pre_fix_entry_drops_trusted_configuration_and_health_reads_wrong_database`：requires isolated Linux root and explicit retained-audit reproduction
- full: `test_pre_fix_root_restore_removes_service_ownership_and_readability`：requires isolated Linux root and explicit retained-audit reproduction
- full: `test_locked_artifact_installs_into_empty_venv_and_runs_without_checkout`：requires opt-in isolated Linux dependency installation

两个既有 Authlib 弃用警告分别来自 fastmcp 的 authlib.jose 导入与 Authlib 的 httpx 兼容层；原始警告保留在日志，本轮没有修改相关依赖。

## 真实 dirty archive 安装与绑定（PASS）

实际 fixture：`/var/lib/trendradar-resource-20261111/task7-install/test_locked_artifact_installs_0/installation-evidence.json`。归档 SHA-256 `6a3e1ac528103d905854c11978f61f472f7e3028c4d53c1fe7593f006b7ec46f`；大小 6238626 字节；完整 artifact 字段与依赖指纹见 `task7-installation-evidence.json`。
本轮未传 supplied clean archive；从当前工作树实际构建，`git_dirty=true`、`clean_candidate=false`。
安装在 checkout 外新建空 venv，先安装固定 build/runtime lock，再安装归档；`pip check` 无破损依赖，
站外导入来自新 venv，release_smoke 通过，指定缺失数据库未被创建。安装只访问公开依赖下载。

归档逐字节比对 644 个当前路径（shell 仅按 builder 规则处理），包含新增 SQLite helper、轮询模块、采集 env 与文档资源；无 output/runtime/.env/DB/WAL/cache。
`task7-final-binding.json` 记录精确 archive、fixture、原始/归档绑定与跳过原因；`task7-diff.patch`、
`task7-status.txt`、`task7-newfiles.txt` 记录基线后的差异。冻结后仅本验证报告回填发生变化；
安装归档包含回填前报告，不能声称归档中的报告具有安装完成后的回执。产品源码、配置、依赖、其他文档与归档相同。
32 个相对 Markdown 目标均存在；无新增断链。AGENTS/CLAUDE 各仅净增 6 行。

置信度：上述本地回归、摘要与归档绑定 High；生产持续负载、SLI、历史故障根因 Unknown。
新 GitHub CI PENDING，生产未部署；没有 stage/commit/push/PR 或全局设置修改。
