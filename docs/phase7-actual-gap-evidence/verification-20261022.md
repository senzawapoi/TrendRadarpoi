# Phase 7 本地整改与回归记录

日期：2026-10-22，Asia/Shanghai。按 2026-10-15 交接指南执行；本轮可授权的本地整改已完成，完整 Phase 7 生产验收尚未完成。

## 候选与修改

HEAD：`5a427aba5ded0c9c9c9e050413dcb41f17fa0e23`，`main`，dirty。领先的是本地 `origin/main` 记录的 42 个提交；本轮没有 fetch。

[v6 输入清单](final-inputs-v6-20261022.json) 固定 301 个源码、测试、部署脚本、units、workflow、锁文件及配置资源；12 个约束文件另列。清单 SHA256：

```text
236de09722e23237d99aee0b1680ec020709ce61066e57ca85779e57d47ca4cf
```

Windows/Linux 全量及产物安装结束后，301 个输入哈希未变。归档内对应 301 个成员也全部匹配。活动状态/验收文档在测试之后校准；[最终核对](post-run-verification-v6-20261022.json) 单独记录这些叙述变化、链接、空白检查与进程状态，不冒充完全相同的归档字节。

[相对接续基线的变更](source-delta-20261022.json) 共 12 个原有输入路径：

- 生产依赖：`requirements.txt`、`pyproject.toml` 为 Windows 声明 tzdata，`requirements.lock` 固定 2026.2。干净 Windows 环境原有 7 个上海时区用例失败；补齐后通过。[复现](tzdata-reproduction-20261022.json)。
- 生产租约：`trendradar/ops/maintenance.py`、`scripts/deploy/install_release.sh` 对新记录使用同 boot 的 `CLOCK_BOOTTIME`，保持 15 秒上限、PID/start/boot、release、阶段及业务边界校验。无效、未来或过期值拒绝；旧记录继续严格 UTC 校验。实际诊断捕获到 UTC 倒退 1.706797 秒，具体校时来源未知。[调查](guard-clear-investigation-20261022.json)。
- H1 覆盖：`test_installer_behavior.py`、`test_remaining_gap_assertions.py`、`test_restore_crash_recovery.py`、`test_restore_recovery.py` 补齐六入口、崩溃后保护、公开 clear 和双库身份断言。
- 测试夹具：`installer_harness.py` 移除临时诊断写入，合成服务心跳使用有效窗口内的时间；`test_runtime_guards.py` 保留旧 UTC/新 boottime、严格类型、身份和边界覆盖；`test_systemd_quiesce_linux.py` 的过期租约注入同时使新时钟过期。H1 正向控制器夹具改为当前安装器格式。[夹具证据](positive-lease-fixture-20261022.json)。

没有降低生产健康规则、放宽租约、删除事务记录或扩大 skip。

## H1 验证

| 项 | 已验证行为 | 对应节点/模块 |
| --- | --- | --- |
| H1-A | 正常发布、公开 finalize、合法回滚后，六个真实入口到达 sentinel；失控记录阻断 I/O | installer success/rollback/finalize、remaining assertions |
| H1-B | 五个真实中断点 × 第二库存在/缺失；恢复前六入口受保护；DB/WAL/SHM 与 journal 对应 | abrupt restore death |
| H1-C | activate 后 guard 仍在；公开 maintenance clear 在终态成功，未完成/损坏记录拒绝 | restore recovery、pending clear |
| H1-D | intelligence/AI 双库内容、schema、完整性/外键正确；确认前后 current 和 release.env 不变 | installer success、sigkill-finalize |

[H1 聚焦](h1-focused-20261022.json)：22 passed，123.23s，exit 0。全部节点另有 v6 全量执行映射，见 [28 项审计](case-results-20261022.json)。安装器控制流模拟 pip/venv/systemctl；真实 systemd、UID 和实际产物安装另有证据。Linux SIGKILL、Windows abrupt exit 分别报告，不是断电耐久性验收。

## 最终执行

命令、环境、终态、日志/JUnit 路径见 [v6 运行记录](final-run-v6-20261022.json)。下列范围有重叠，不能相加。

| 范围 | passed / failed / skipped / warnings | 时间 | 退出码 |
| --- | --- | --- | --- |
| 隔离 Windows 全 tests | 683 / 0 / 342 / 2 | 46.20s | 0 |
| Ubuntu WSL 全 tests | 1019 / 0 / 6 / 2 | 1060.42s | 0 |
| 独立 Linux dirty 空 venv 安装 | 1 / 0 / 0 / 0 | 41.23s | 0 |
| Linux 全量内真实 systemd 停写/回滚 | 11 / 0 / 0 / 0 | 包含于全量 | 0 |
| Linux 全量内真实 systemd 备份 unit | 2 / 0 / 0 / 0 | 包含于全量 | 0 |
| Linux 全量内安装器控制流 | 60 / 0 / 0 / 0 | 包含于全量 | 0 |

Windows：Python 3.10.11 / SQLite 3.40.1；Linux：Python 3.10.22 / SQLite 3.53.1，root、真实 systemd，服务 UID 65534。解释器位于 `/var/lib`，保留 `PrivateTmp`。所有本轮测试句柄已结束。

[逐节点 skip 审计](skip-audit-v6-20261022.json) 已解释全部跳过。Windows 的 Linux/POSIX/root/systemd 跳过由 Linux 执行支持；Linux 的 3 个 Windows Job Object 跳过由 Windows 实测支持。2 个 opt-in 历史 pre-fix 用例保留原归档复现，不算当前源码通过；1 个安装跳过由独立安装补齐。两条 warning 为 FastMCP 引入的 Authlib jose/httpx 弃用提示，未抑制。

八个受影响 Python 路径 Ruff 通过，253 个 Python AST 通过；四份 Bash 文件及三 workflow 的 17 个 run 块沿用未变哈希的有效静态证据。workflow 表达式语法占位与真实 argv 接线检查分别报告，不代表 GitHub 执行。两端隔离环境及空 venv 的 `pip check` 通过。全局 Windows 既有包冲突未修改；隔离 venv 没有 Ruff，使用已有主机 Ruff 后通过，初始工具错误日志保留。

## 产物身份

[实际安装证据](artifact-install-evidence-v6-20261022.json)：

```text
trendradar-isolated-install.tar.gz
SHA256 480430d8976ac499c7cd1e9dc35c0a37cab4ed4acf1fcdf7801c0f954a13c255
bytes 11880521
git_dirty=true
clean_candidate=false
```

空 Python 3.10 venv 实际安装 build/runtime 锁与项目，`pip check`、checkout 外导入及 release smoke 成功；归档无运行数据库、真实 .env、缓存；负向 readiness 未创建缺失数据库。wheelhouse 仅用于本地依赖缓存，没有调用业务 provider。产物与原失败现场仍保留。

## 结果与交接

[矩阵](case-matrix.md)：**27 PASS、1 BLOCKED（RG-04 干净候选）**。原需求行、审查过的正反断言、参数节点、执行环境和限制逐项写入 JSON；这不是产品完成百分比。

- G1：PASS，仅限已执行的逻辑回归。
- G2：BLOCKED，缺获授权形成的干净生产候选。
- G3 / V-01..06：NOT_RUN/BLOCKED；至少 48 小时、两个真实日报窗口及受控故障恢复证据尚无。
- DEPL-01..05：目标生命周期、数据流、CI/发布/异地备份、运维演练及资源证据仍待现场或远端执行。
- Phase 5：B6 非白名单分支保留用户接受的跳过；C3 真实断网、C4 收件确认仍开放。

下一步先由用户授权形成提交候选，再绑定真实 GitHub run/job/artifact。目标验收还需 VPS/SSH/known_hosts、运行配置、备份访问与隔离恢复目标以及执行授权；凭据不写入仓库或报告。受控演练不能替代规定的长期运行窗口。

没有 commit、push、创建发布、触发远端 workflow、生产部署、真实 provider/远端 restic 调用或凭据读取。`output/`、`test/runtime/`、WAL/SHM、缓存、审计包、故障目录和工具链均保留。未重试此前被策略拒绝的缓存删除。

v3 临时诊断的 UID 权限失败、v4 最终 health generic 失败、v5 旧格式正向夹具失败保留原日志；后两次没有捕获具体失败时钟年龄，不补写未经证明的根因。它们不作为当前候选的通过记录。

置信度：已执行的本地范围高；生产设备、网络、租户及长期运行未知。
