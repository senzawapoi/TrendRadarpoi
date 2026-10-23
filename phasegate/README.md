# PhaseGate 0.2 — TrendRadarpoi 真实测试接入试点

这版运行真实仓库的 pytest 测试，不运行旧 Demo 的替代实现。它是独立、建议性工具，不增加 Phase 7 的强制前置条件，不修复业务代码、不更新 GSD 状态、不提交、不部署。

## WSL/Linux 快速使用

本项目日常回归使用 WSL/Linux；生产目标为 Python 3.12。
在原生 Linux 文件系统上的仓库副本中运行，激活已安装锁定依赖和 pytest 的虚拟环境。
避免从 `/mnt/c` 运行耗时 installer/systemd 测试。保留旧 Windows 证据，
`full-windows` 仅作历史/平台专项入口，不要求本轮重新执行。

```bash
python phasegate/phase7_gate.py inspect
python phasegate/phase7_gate.py freeze --out .phasegate/baseline-01.json
python phasegate/phase7_gate.py run --baseline .phasegate/baseline-01.json --suite health --out .phasegate/health-linux-01.json
python phasegate/phase7_gate.py run --baseline .phasegate/baseline-01.json --suite guard-portable --out .phasegate/guard-linux-01.json
python phasegate/phase7_gate.py summarize --baseline .phasegate/baseline-01.json --reports .phasegate/health-linux-01.json .phasegate/guard-linux-01.json --out .phasegate/summary-01.json
```

输出文件必须使用新名称，避免覆盖旧证据。根目录内的输出限定在 `.phasegate/`。JSON 报告同时生成 Markdown。

`inspect` 只检查 28+6 场景映射、原文锚点和测试节点存在；不执行测试。`freeze` 固定当前声明范围的文件字节哈希，并记录 Git 信息。工作区可以是 dirty；HEAD 不能替代内容指纹。

输入包括 AGENTS.md、CLAUDE.md、PROJECT/REQUIREMENTS、07-CONTEXT、07-01～05-PLAN、实际缺口测试计划，以及 2026-10-15 接续指南和当前 HANDOFF。交接中的历史失败不覆盖最新修复事实；H1-A～D 的未完成覆盖仍保留在对应场景说明中。

## Linux 特权测试

基准按内容指纹核对，允许不同挂载路径；不能混合不同基准或候选的报告。
使用 `/var/lib` 等原生测试目录，解释器须可供临时服务 UID 访问，且位于临时目录之外。

```bash
python -B phasegate/phase7_gate.py run --baseline .phasegate/baseline-01.json --suite environment-linux --out .phasegate/environment-linux-01.json
python -B phasegate/phase7_gate.py run --baseline .phasegate/baseline-01.json --suite permissions --out .phasegate/permissions-linux-01.json
```

需要 root 的 suite 只在已经具备权限的隔离测试环境运行；工具不会提权。systemd suite 还要求 PID 1 为 systemd，以及明确传入 `--allow-systemd`。不能将本命令用于生产主机。

## Suite 与边界

| Suite | 实际范围 | 环境/注意事项 |
|---|---|---|
| health | 真实 health CLI、transport/心跳、SQLite、完整本地策略 | Windows/Linux；provider 与远端收据为 fake |
| environment-parser | EnvironmentFile 解析 | Windows 会保留 POSIX-only 跳过为 BLOCKED |
| environment-linux | 固定入口、六路径、锁、缺键及不可读 YAML | Linux root |
| guard-portable | 无控制者的部署与 pending restore 的业务入口保护 | Windows/Linux |
| guard-linux | 控制者身份与授权正向入口 | Linux root；正向 sentinel 不等于所有独立服务已恢复 |
| restore | 真实 SQLite、多库恢复、崩溃与持久化故障 | Linux；绝不使用原运行库 |
| permissions | 实际 UID/GID、WAL、失败后的访问与目录不变性 | Linux root |
| installer | 真正执行 Bash installer | Linux root；pip/venv/systemctl 替代，可能耗时较长 |
| release-inputs | 归档/输入拒绝与 CI 接线 | Linux root；不调用真实 GitHub/SSH |
| systemd | 现有真实临时 units、备份参数与角色生命周期 | Linux root + systemd + 显式开关 |
| offsite | fake restic 的结果、进程及凭据脱敏 | 平台专属跳过仍保留；不证明远端备份 |
| compatibility | baseline、Feishu、Intelligence、Research | 不等于完整 tests；平台跳过不算通过 |
| full-windows | 完整 tests | 只在 Windows；Linux/现场测试的 skip 不变成 PASS |
| full-linux | 完整 tests | Linux root + systemd + 显式开关；归档安装仍不会自动开启 |

RG-04 干净候选/真实依赖安装和 V-01..06 保留外部证据缺口。本程序不复制 `.git`、不联网安装依赖、不自动接受旧日志，也不通过虚构 Git 元信息使产物测试通过。旧回归 466 passed / 6 skipped 作为历史事实保留，不导入为本轮执行结果。

## 两种结论，不能混淆

1. **run.status**：这次明确选择的测试是否全部执行成功。call 失败为 FAIL；setup/teardown 错误、skip、xfail、缺失事件、超时为 BLOCKED。退出 0 本身不够。
2. **summary.cases**：原计划每个场景所需的平台、测试和语义覆盖是否齐全。只有已审查映射、所有要求的平台及用例都有证据，才可为 PASS。

异常进程退出、事件退出码不一致、pytest 删选用例或缺少整段选定范围时，不能用已通过的少数节点补成 PASS。正常执行中的平台跳过只阻断相关节点，不会把无关已完整执行的场景一并抹掉。

`phase7.json` 逐条引用原计划的 34 个场景。当前 7 项映射的列明断言已检查源码；20 项仍标为 partial，7 项等待外部证据。这是映射审查进度，不是测试通过率或新增业务缺陷数量。对未审完的场景，即使 supporting tests 全绿，也不自动关闭。

完整测试目录不能由一个 health 子集冒充；同一个基准的失败也不会被后来一个 PASS 自动隐藏。Windows 证据不能填补 Linux 或 systemd 的缺口；不同 baseline/candidate 的报告拒绝合并。汇总默认只接受 24 小时内生成的报告；旧报告仍可人工阅读，但不作为当前放行。

## 整理后核对与 AI 审查

```bash
python phasegate/phase7_gate.py review-packet --baseline .phasegate/baseline-01.json --summary .phasegate/summary-01.json --out .phasegate/review-packet-01.json
python phasegate/phase7_gate.py close --baseline .phasegate/baseline-01.json --reports .phasegate/health-linux-01.json .phasegate/guard-linux-01.json --out .phasegate/closeout-01.json
```

`review-packet` 给现有 agent/人工提供真实来源、候选和逐项证据。0.2 不调用模型 API、不把填入的模型 PASS 自动转换成验收批准。独立审查须检查映射遗漏、正向路径、项目级约束、前序回归以及旧交接文字与新证据冲突。

`close` 会重新核对来源变化，但这版始终返回 `can_close=false`、退出码 2，表示没有安装 GSD 完成适配层。它不是在宣布 Phase 7 必须被新增工具阻断。原本的 Phase 7 验收按既有流程推进；这个工具提供可复现证据，不接管关闭权限。

后续试点位置：原生验证后生成证据；`/neat-freak` 后重新 summarize/close 核对。声明范围内任何代码、测试、约束或 PhaseGate 文件变化都要求重新冻结与重验。没有使用宽泛 Markdown 白名单。

## 隔离与证据边界

- 只复制清单声明的代码、测试、部署模板、普通配置和约束；不复制 `.env`、output、test/runtime、dist、数据库、缓存或 `.git`。
- pytest 在私有副本中执行，临时数据库位于 pytest 私有基目录。原项目只被读取；报告写入 `.phasegate/`。
- 子进程仅保留必要系统变量，清除现有 provider 凭据和 PYTEST_ADDOPTS，并关闭自动第三方 pytest 插件加载。已有测试会自行启用合成凭据/fake 边界。
- 若当前解释器启用了用户级 site-packages，保留其已激活的包目录供导入，并在报告中列出；不恢复真实 HOME/USERPROFILE、APPDATA 或原 PYTHONPATH，不安装依赖，也不复制用户配置。
- 这不是 OS 网络/文件访问沙箱；被选择的测试代码仍需审阅。普通测试中的 fake 不能证明生产服务行为。原测试自建的临时 systemd units 可能由其夹具清理，本工具不会广泛终止进程或删除旧证据。
- Linux root 的复制目录放在 `/var/lib/phasegate-run-*`，避免 PrivateTmp 隐藏解释器或源码；Windows 使用独立临时目录。保留每次新建 arena、日志和事件文件供排查，不删除已有历史目录。
- 超时时 Linux 仅终止本次新建的进程组；Windows 只终止本次 pytest 直接子进程，不能保证回收测试自行派生的后代。报告保留 BLOCKED 与 arena，需检查本次归属的进程；不运行广泛清理命令。
- 默认原始 pytest 日志留在本机 arena，报告仅含节点、阶段状态、耗时和哈希，不复制 traceback/payload。退出码 0/1/2/3 分别表示 PASS/FAIL/BLOCKED/REVIEW_REQUIRED。
- 输入快照不覆盖任意机器文件、未声明插件、安装依赖内容或真实部署文件权限。记录 Python/SQLite/平台版本不等于依赖可重现证明。
- SHA256 完整性用于发现意外篡改，不是签名；有源码和报告写权限的人可以伪造结果。可信 CI runner 与权限隔离是后续工作。

## 工具自身验证

```bash
python -B -m unittest discover -s phasegate/tests -v
python -m ruff check --no-cache phasegate
```

测试包括真实 pytest 插件集成、调用失败/跳过/xfail/缺事件、源码漂移、原文件不变、跨平台缺口、子集冒充全量、过期或混合版本证据等。不依赖 TrendRadarpoi 的实际运行数据库。
