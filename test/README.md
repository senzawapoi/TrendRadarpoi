# Phase 5 本地测试沙箱

此目录用于在 Windows 上隔离验证 Phase 5 Lark Assistant。它不是生产部署目录，也不会
修改 `output/`、根配置或系统级环境变量。测试数据库和临时运行文件位于
`test/runtime/`，由本目录的 `.gitignore` 忽略。

## 正在测试时先看这里

如果实例仍在运行，沿用现有实例，不重跑启动、种子初始化或 `-Reset`。实时 PID、入口和日志
位置以 `runtime/lark-live.json` 为准；检查进程是否匹配，不能仅凭文件存在判断机器人在线。
2026-10-11 核对结果：群聊诊断实例和 C4 日报实例均已停止；C4 实例 PID 25780
已完成真实投递和同窗口重启幂等观察。原 `intelligence.db` 的群聊 @、会话隔离和群聊未 @
取证已完成；非白名单账号测试按用户要求跳过。PID 25780 仅作历史定位，不能据此判断进程在线。C4 使用独立的
`runtime/c4-intelligence.db`，不要与原库混用。
描述文件保留 PID、入口和日志位置，仍需与实际进程核对，不能只看文件存在判断在线状态。
[phase5-combined-check.png](runtime/phase5-combined-check.png) 是已通过 B4 的历史证据；
新的图文验收应使用未进入会话的新图，不重复已完成用例。

验收结论统一维护在 [05-LIVE-UAT.md](../.planning/phases/05-feishu-assistant/05-LIVE-UAT.md)，
接续事项见 [.planning/STATE.md](../.planning/STATE.md)。文件和日志中的计数是时间点快照，
不是实时状态；不得用旧图片、历史答案或单个 `completed` 状态代替新用例证据。

## 文件用途

| 路径 | 用途与保留规则 |
|------|----------------|
| `run-phase5.ps1` | 离线构建、配置检查及普通 Live 入口；真实联调中不要再次启动 |
| `seed_phase5.py` | 新建合成 Story；`--verify` 只读检查已有库，不刷新旧数据日期 |
| `phase5_diagnostics.py` | 复用原运行器的脱敏诊断入口，替代而非并行于普通 Live 入口 |
| `test_phase5_diagnostics.py` | 诊断隔离、授权、重放及故障的离线测试 |
| `runtime/lark-live.json` | 单实例定位信息，启动/停止后由操作者核实更新；不包含凭据 |
| `runtime/intelligence.db*` | 测试库及 WAL/SHM，运行中不得移动、删除或仅复制主库备份 |
| `runtime/lark-diagnostic-*.log` | 诊断实例日志；当前文件可能仍在写入，原位保留 |
| `runtime/lark-lite-*.log` | 旧实例证据日志，验收结束前保留 |
| `runtime/phase5-*-check.png` | 合成视觉证据；combined 是本轮用图，其他图只供历史核对 |

## 前置条件

在仓库根目录安装并确认 Python 3.10+、`lark-oapi==1.7.3`、`google-genai`、pytest 和
项目依赖。入口不会自动安装依赖，也不会读取 `.env` 或仓库外的凭据文档。真实凭据由
操作者在进程环境中提供；现有受控启动流程已完成此步骤，无需再次手动注入。不要把
凭据写入脚本、仓库配置、日志或命令参数，不读取外部凭据文档进行工作区整理。

## 离线构建

```powershell
.\test\run-phase5.ps1
.\test\run-phase5.ps1 -RunTests
```

首次运行会创建两条当天的 synthetic Story，输出 schema 和数量，不输出正文或 ID；已有
数据库只读复用，不会静默覆盖。需要重建时才显式执行：

```powershell
.\test\run-phase5.ps1 -Reset
```

`-Reset` 会删除整个 `test/runtime/`，包括数据库、日志、测试图及实例描述文件。它不是
缓存清理命令，也不自动确认 bot 已停止；必须先停止全部相关实例、保留所需证据，再
明确决定重建。真实测试进行中禁止执行，不要把它用于生产目录。

## 配置检查与真实运行

只检查当前环境，不创建数据库：

```powershell
.\test\run-phase5.ps1 -Check
```

`-Live` 默认只启用 `p2p`、关闭日报，并强制使用 `test/runtime/intelligence.db`。
真实运行从当前进程读取 `LARK_APP_ID`、`LARK_APP_SECRET`、`LARK_IDENTITY_FIELDS`、
`GEMINI_API_KEY` 和 `GEMINI_MODEL`。确认单聊文本和图片后，再用 `-Group` 要求
`LARK_BOT_ID` 并启用群聊；用 `-Delivery` 和 `LARK_DELIVERY_TARGET` 做日报测试。
群聊和日报参数只在启动前读取。

脚本启动前会运行 `--check`，但这只验证配置，不验证 Lark 租户权限、长连接、Gemini
模型可用性或实际投递。真实验收的完整场景、取证和已知限制见
[`docs/phase5-live-acceptance.md`](../docs/phase5-live-acceptance.md)。

## 图文现场诊断

已配置上述进程环境时，可用以下入口替代普通 Live 入口；必须先停掉同一应用的旧实例：

```powershell
python -u -B test/phase5_diagnostics.py --config config/config.yaml
python -B -m pytest tests test/test_phase5_diagnostics.py -q
```

诊断入口仅接受 `test/runtime/intelligence.db`，复用原授权、队列、模型、重放和投递逻辑。
标准输出的 `UAT` JSON 行仅记录授权后的消息类型、文字长度、图片数量/字节数、模型结果、
token 用量及投递状态。随机进程密钥生成的事件关联标签不暴露真实 ID，且重启后不可关联。
它不记录正文、图片内容、身份值、凭据、工具参数或异常原文；诊断代码不额外读取被忽略
事件的内容或消息类型。
`gemini_calls` 计数是逻辑生成调用数，不是 SDK 内部 HTTP 重试次数。

图文验收需在同一个关联标签下同时看到 `inbound` 的文字与媒体、`assistant_input` 和
`gemini_input` 的图片、成功的 `gemini_result`，以及 `delivery.outcome=sent`，再与客户端
实际回复交叉确认。沿用历史图片事实的正确答案不能单独证明本轮上传了图片。

## 停止与清理

前台启动的实例在对应 UAT PowerShell 中按 `Ctrl+C`，等待进程完全退出。隐藏后台实例
不受另一个终端的 `Ctrl+C` 控制；先用描述文件核对 PID、命令和启动时间，协调停止发送
并确认无正在处理的工作后，由操作者安排停止。数据库没有 pending 行不代表内存队列为空。
不要按进程名批量结束 Python，也不要仅凭旧 PID 结束进程。

关闭启动终端不会结束已分离的后台子进程或清除其继承的凭据。进程未退出前保留数据库、
WAL/SHM、所有测试图和证据日志；不要轮转或移动正在写入的日志。验收未结束时保留
`runtime/` 的原路径，避免破坏证据链接。

没有 pytest/Ruff 在运行时，可以删除已确认的 `.pytest_cache/`、`.ruff_cache/`，以及
`test/` 内已知 `__pycache__/`。删除前检查绝对路径和重解析点；遇到拦截就停止并记录，
不换工具绕过。不要删除 `output/`，不要使用 `git clean`，不要提交运行文件或凭据。
