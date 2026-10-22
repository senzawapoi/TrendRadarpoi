---
phase: 05-feishu-assistant
status: in_progress
prepared: 2026-09-12
live_verified: false
---

# Phase 5 真实验收记录

操作流程：[Phase 5 真实验收与调试](../../../docs/phase5-live-acceptance.md)。
本文件区分已确认、证据不足与未执行的用例，整体验收仍未通过。历史章节记录当时的快照，
不代表实时进程或计数；阶段离线结论见 [VERIFICATION.md](VERIFICATION.md)。

2026-10-12 决策修订：此前记录中的“重放”测试按当时契约验证持久回复可再次发送；现行契约
已改为已送达的重复 `event_id` 本地抑制，不再发送或调用模型。下方历史证据保留原样，当前
实现与回归标准以 `already_delivered` 和无新增发送为准；失败交付仍可重试保存的回复。

## 当前结论速查

| 项目 | 最近已确认结论 |
|------|----------------|
| 离线回归 | 2026-09-13：含沙箱诊断测试共 406 passed、1 个既有警告，scoped Ruff 通过 |
| B1/B2、纯图片 | Lark 单聊、连续问答/引用和纯图片功能已获用户确认 |
| B3/B4 | B3 Gemini 成功/禁用对照和 B4 单条图文均已通过 |
| 受控故障测试 | C1/C3/C5/C6 的离线/模拟专项共 22 passed、1 个既有警告；真实部分仍按矩阵处理 |
| 群聊、故障与日报 | B5 已通过；B6 非白名单分支按用户要求跳过且总项保持 blocked；C2、C6 已通过；C3 真实断线未执行；C4 投递和同窗口幂等已取证，收件确认待用户确认 |
| 当前操作 | 当前无运行中的机器人；若继续 UAT，先按 `test/README.md` 核对实例描述、进程和数据库 |
| 运行定位 | C4 实例 PID 25780 已停止；描述文件指向 C4 日报日志和独立数据库，仅作历史定位，不代表进程在线 |

运行文件及证据保留规则见 [测试沙箱指南](../../../test/README.md)。各子项通过范围以本文件证据为准。

## 执行信息

- 操作者 / 日期 / Asia/Shanghai 时间范围：Codex，2026-09-13 15:21-18:15。
- 代码版本及未提交变更快照标识：`5a427ab`，测试时工作区有 68 个 dirty entries。
- Python / lark-oapi / google-genai 版本：3.10.11 / 1.7.3 / 1.73.1。
- 测试应用、白名单用户、非白名单用户、测试群：`lark-uat-app`；其余待提供。
- 独立数据库与私有证据目录：`test/runtime/intelligence.db`；未保存外部原始响应。
- 临时配置与恢复检查：凭据仅由仓库外文档注入短生命周期子进程；工作区凭据匹配数为 0。

## 当前离线证据

2026-09-13 Lark 域名及 UAT 缺陷修复后复跑 `python -m pytest tests -q`：401 passed、1 个既有 OpenTelemetry 警告；变更 Python 路径 Ruff 通过。
手册中的 synthetic Story 初始化片段已在临时目录执行验证：schema 5、2 条 ContentItem、2 条 Story。
只读快照片段已针对同一临时库执行，计数与空事件/会话/投递状态符合预期。
Lark/媒体专项回归 58 passed、1 个既有警告、无 skip；两组独立回滚开关的 `--check` 均验证关闭且不创建数据库。
真实 Lark 国际域 WebSocket 握手和白名单私聊消息收发成功。隔离库账本记录 5 个 completed 事件、0 个 failed 事件、1 个会话及 10 条成对消息；每个事件 attempts=1。首轮 `UAT` 正确返回两条 synthetic Story、预算 10/20、重要性 88 高于 42 及本地引用；同会话追问正确计算总和 30，但暴露历史引用校验缺口，修复后的线上复测又被 Gemini 限额阻塞。

`gemini-3.8-flash` 的最小文本和内存 PNG 探针成功。真实工具续轮发现 Gemini 3 返回的 opaque `thought_signature` 未被旧边界透传，导致 HTTP 400；代码已增加受限、脱敏的内存内透传。修复后已确认能捕获 signature，离线完整工具续轮通过，但 provider 随后返回 429 `RESOURCE_EXHAUSTED`：`GenerateRequestsPerDayPerProjectPerModel-FreeTier`，因此尚无修复后的真实最终回答证据。未保存消息正文、身份值、signature 或 provider 原始响应。

## 2026-09-13 模型切换复测

- 按用户要求保留同一 API key，将仓库外接口文档的 `GEMINI_MODEL` 改为 `gemini-3.5-flash-lite`；Google Models API 确认名称为 Gemini 3.5 Flash Lite，支持 `generateContent`。
- 真实最小文本返回预期结果；完整工具往返携带 thought signature，模型最终正确返回合成值 30，结束原因 STOP。该探针解除 P5-UAT-02 在新模型上的线上复测阻塞，不代表旧模型的额度已恢复。
- 用只读备份得到的内存数据库执行真实 Assistant 两轮问答：首轮预算 10/20、4 个有效引用；同会话追问总和 30、2 个有效引用、无空引用括号，两轮均非降级。原测试库保持 5 个事件、1 个会话、10 条消息。首次内存探针因连接采用默认隐式事务导致提交异常；改用与应用一致的 autocommit 后重测通过，未改业务代码。
- 已使用新模型恢复一个隐藏后台 Lark 实例，日志确认 connected。进程和日志定位见忽略文件 `test/runtime/lark-live.json`；继续前需核实进程仍存活，避免重复连接。
- 模型切换轮仅改配置与验收记录；401 passed 为既有离线基线，未重复全量测试。

## 2026-09-13 单聊确认与图片准备

- 用户确认收到 17:29:16 Asia/Shanghai 发起的追问回复：预算 10/20、总和 30、完整依据和来源链接，无降级标记。只读账本核对为 6 个 completed 事件、0 个 failed、1 个会话、12 条消息；最新 Assistant 与 event_id 账本关联成功，仍在原会话，4 个有效引用且 degraded=false。B2 功能验收通过，P5-UAT-01 的 Lark 客户端复测通过。
- B3 仍待逐事件 provider 元数据关联和显式禁用对照；本条 completed/非降级账本不替代该项证据。
- 已生成独立合成测试图 `test/runtime/phase5-visual-check.png`，1000x600、13047 bytes。新模型真实视觉探针正确识别编号 VIS-6427、金额 73.40 units 和蓝色矩形；模型为 gemini-3.5-flash-lite，结束原因 STOP，单图输入，total_tokens=1119。
- 图片探针未经过 Lark 资源下载链路，也未写入会话；下一步由用户在原私聊直接发送这张图片，再测试同一条富文本 post 的图片加指令。机器人保持单实例运行，图片/图文验收尚未通过。

## 2026-09-13 纯图片确认与图文准备

- 用户确认 17:37:27 Asia/Shanghai 发起的图片消息获得正确答复：标题、编号 VIS-6427 和金额 73.40 units 均与合成图一致，无降级标记。只读账本为 7 个 completed 事件、1 个会话、14 条消息；最新事件 attempts=1，回复 degraded=false。
- 本轮持久化输入仅为 `[Image attachment]`；此前该会话没有图片中的编号或金额，实际答复也不来自已有本地 Story。结合图片识别正确和客户端确认，纯图片收发/识别功能通过。图片字节、实时输入图片数量及 provider 用量未在原进程日志中记录，逐事件 provider 元数据仍作为 B3 的待验项。
- 最新回复没有本地 citation，符合本轮只描述用户图片的行为，不将图片虚构为 Story/observation 来源。
- 下一项使用新图 `test/runtime/phase5-post-check.png`（1000x600、13174 bytes），预期编号 POST-8519、金额 46.25 units、绿色矩形。该图未发送给 provider 或写入会话，用于排除沿用上一张图片的历史答案。
- 用户需将新图与“请读出本张图片中的 Reference、Amount 和矩形颜色。”置于同一条富文本 post 发送；B4 汇总项仍待图文混合和逐事件取证，不能标记整体通过。

## 2026-09-13 图文发送轮次核查

- 用户确认的 17:45:12 Asia/Shanghai 回复正确给出 POST-8519、46.25 units、绿色，但自述沿用上一轮识别。只读核对发现 17:44:07 与 17:45:10 两轮输入均只有图片占位符；17:45:12 为单独的文字提问轮次（33 字符）。三轮均 completed、attempts=1、degraded=false；累计 10 个事件、1 个会话、20 条消息。
- 17:45:12 之前的 Assistant 历史已包含新图编号和金额，因此不能用答案正确判定本轮图文同时输入成功。旧记录未保存入站 message_type/图片数量，不能仅凭此账本断言最后一轮绝无图片；记录为混合输入证据不足，B4 保持 blocked。
- 再准备未进入会话的新图 `test/runtime/phase5-mixed-check.png`，1000x600、13752 bytes，预期 MIX-3962、58.70 units、红色矩形。通过 Lark 富文本/展开编辑器将图片与阅读指令放进同一条消息，只发送一次；发送后应作为同一气泡显示。机器人继续单实例运行，待复测。

## 2026-09-13 MIX 复核与脱敏诊断入口

- 用户回传 17:56:19、17:59:46 Asia/Shanghai 两轮回复，均正确给出 MIX-3962、58.70 units、红色。最新只读快照为 12 个 completed 事件、1 个会话、24 条消息，最新回复 degraded=false；17:59:46 输入含 29 字符的文字问题，不是图片占位符。
- MIX 图片事实已在历史中出现；旧账本不记录本轮图片数量和消息类型，因此只能确认本轮文字到达，不能据答案正确认定图片也同时输入。B4 保持 blocked，未认定生产解析器存在缺陷。
- 新增 `test/phase5_diagnostics.py` 沙箱入口，只允许 `test/runtime/intelligence.db`，复用原有生产执行流程。授权成功后记录入站类型/文字长度/媒体数量，以随机进程密钥派生的 HMAC 标签关联 Assistant 输入图片、实际有界 Gemini 输入、模型结果/结束原因/用量和投递状态。标签只在当前进程内稳定，不保存原始 ID、正文、图片字节、凭据、signature 或异常原文。`gemini_calls` 是逻辑生成次数，不代表 SDK HTTP 重试数。
- 新增诊断的关联/重复投递/拒绝/写入故障/模型失败/沙箱路径约束测试，并补强旧混合输入测试的文字保留断言。`python -B -m pytest tests test/test_phase5_diagnostics.py -q` 为 406 passed、1 个既有警告，三个变更 Python 文件 Ruff 通过。测试使用模拟 provider，不计为新增真实验收通过。
- 18:13 Asia/Shanghai：配置离线校验通过，旧账本无未完成事件；停止原测试实例后，启动一个隐藏的诊断实例。进程数量为 1，日志确认 connected，无 worker unavailable 或 traceback。模型仍为 `gemini-3.5-flash-lite`，key 未改；仅 p2p、日报关闭、原隔离数据库复用。定位信息已更新到忽略文件 `test/runtime/lark-live.json`。这是受控正常切换，不算断线恢复或未完成事件恢复验收。
- 准备新合成图 `test/runtime/phase5-combined-check.png`：1000x600、17282 bytes，编号 BOTH-7284、金额 91.35 units、黄色矩形。已本地目视核对，尚未发给 Lark 或 Gemini，不在机器人会话历史中。
- 当时下一步：用户在同一条富文本消息中放入该图和字段提取指令，只发送一次；同一关联标签需出现 `inbound` 文字及媒体、`assistant_input` 和 `gemini_input` 图片、成功 `gemini_result` 以及 `delivery.outcome=sent`，再核对客户端回复。该步骤已在下一节完成；B3 的显式禁用对照仍未执行。

## 2026-09-13 BOTH-7284 图文混合验收结果

- 用户回传的客户端回复时间为 `2026-09-13T10:20:02.236889+00:00`，正确识别 `BOTH-7284`、`91.35 units` 和黄色矩形。图片中的事实此前未进入该会话，满足新事实排除历史复用的前提。
- 脱敏诊断日志为同一事件生成 6 条记录，6 条记录只有 1 个进程内事件标签，并完整包含 `inbound`、`assistant_input`、`gemini_input`、`gemini_result`、`assistant_result`、`delivery` 六个阶段。没有保存原始 event ID、消息正文、图片字节或凭据。
- `inbound` 显示消息类型为 `post`、文字长度 33、媒体数量 1；`assistant_input` 与 `gemini_input` 均显示图片数量 1、图片字节数 17,282。由此确认文字和图片在同一条消息中到达，并同时进入 Assistant 与 Gemini。
- Gemini 结果为 `gemini-3.5-flash-lite`、`STOP`、`total_tokens=2137`；Assistant 结果 `degraded=false`、引用数量 0；最终投递阶段为 `sent`、该事件逻辑 Gemini 调用次数 1。
- 只读隔离库快照为 schema 5、13 个 completed 事件、1 个 session、26 条消息；最新用户输入为 33 字符文字，非 `[Image attachment]`，最新回复 `degraded=false`。机器人进程随后已退出，未执行重启。
- **B4 状态：pass。** 这项通过只覆盖新 BOTH-7284 单条图文 post；此前 MIX 轮次仍记录为证据不足，不影响本项结论。

## 2026-10-11 B3 Gemini 禁用降级对照结果

- 用户回传的客户端回复包含 `Gemini synthesis is unavailable`、`deterministic local-evidence answer` 和 `Degraded: Gemini is unavailable; deterministic local evidence is shown.`，符合禁用模式的预期；本地查询为空属于该条问题与当前时间范围没有匹配，不是模型调用失败。
- 诊断日志对应同一进程内事件标签，包含 `inbound`、`assistant_input`、`assistant_result`、`delivery` 四个阶段；没有 `gemini_input` 或 `gemini_result` 阶段。入站为普通文字，文字长度 29，媒体数量 0。
- `assistant_result` 为 `degraded=true`、引用数量 0；`delivery` 为 `sent`、`gemini_calls=0`。因此确认 `GEMINI_ENABLED=false` 已实际作用于运行进程，Assistant 使用确定性本地降级路径且没有调用 Gemini。
- 只读隔离库快照为 schema 5、14 个 completed 事件；最新事件 attempts=1、degraded=true。进程 PID 868 仍存活，stderr 为空且没有 traceback；当前日志为 `test/runtime/lark-b3-disabled-20261011-175227.stdout.log`。
- **B3 状态：pass。** 该结论包含正常 Gemini 成功证据（B4 事件关联的 Flash Lite `STOP`）和本次真实禁用对照；禁用模式不会消耗 Gemini 额度。

## 2026-10-11 受控故障与回滚专项进展

- 执行 `python -B -m pytest tests/integrations/feishu/test_idempotency.py tests/integrations/feishu/test_reconnect.py tests/integrations/feishu/test_scheduler.py tests/integrations/feishu/test_delivery.py tests/integrations/feishu/test_runner.py -q`，结果为 22 passed、1 个既有 OpenTelemetry 警告。
- 受控证据覆盖：同一 `event_id` 重复投递只调用一次模型且当前契约不再次发送、核心轮次持久化后的恢复、租约接管与 owner fencing、重连阈值和冷却、日报分片失败续传、空日报边界、关闭运行器不创建 provider/storage，以及兼容入口导入。
- 这次运行使用临时 SQLite、模拟 provider、假连接和假时钟，不接触当前 `test/runtime/intelligence.db`，不改变 PID 868 的 Gemini disabled 进程；因此只更新受控部分，不宣称真实租户验收完成。

## 2026-10-11 群聊文字收发与会话归属

- 用户提供 TrendRadar Daily UAT 群和 bot open_id 后，前一轮停止 PID 868 并启动群聊诊断 PID 26012。启用 `p2p,group`、Gemini Flash Lite，日报关闭；原隔离库及日志保留。本轮只读核查确认仅一个匹配的机器人进程，日志已 connected，stderr 为 0 bytes。
- 用户截图中的两条真实 @ 消息对应 `2026-10-11T12:47:47.494004+00:00` 和 `2026-10-11T12:48:13.770814+00:00`。当前日志的两个事件标签各有完整六阶段记录；文字长度分别 7、5，均无媒体，各调用 Gemini 一次，模型 `gemini-3.5-flash-lite`、`STOP`、`degraded=false`、`delivery=sent`。
- 使用 `mode=ro`、`query_only=ON` 和同一只读事务核查：schema 5、17 个 completed 事件、2 个会话、34 条消息、0 个日报账本。新群会话的 ID 与既有 principal、`group` 和用户提供的 chat_id 推导值一致；两轮各 attempts=1，共 4 条消息，序号 0-3。原私聊仍为 30 条消息，未混入群聊消息。未输出原始身份、事件 ID 或正文。
- 第二轮 Assistant 正文精确为“收到”，与截图一致。第一轮给出了检索时间范围而非当前时刻；本轮确认收发链路，不将其记为报时正确。该表现记录为回答质量待改进，不以非降级标志代替语义正确性。
- B5 群聊显式 @、模型调用、两次回复和群/私聊独立会话归属已有真实证据；私聊口令未泄漏到群聊，B5 状态为 `pass`。第二位白名单用户的跨用户隔离未单独复测。
- 2026-10-11 真实隔离复测：私聊先发送一条验收口令，Assistant 回复已记住；随后在群聊显式 @ 询问该私聊口令，Assistant 回复“不知道”。脱敏诊断记录两条对应事件：私聊事件 `post` 文字长度 20，群聊事件 `post` 文字长度 28；两者各调用 Gemini 一次并以 `STOP` 成功结束，`degraded=false`、`delivery=sent`。只读账本显示 schema 5、19 个 completed 事件、2 个会话、38 条消息；私聊会话新增序号 30-31，群聊会话新增序号 4-5，未发生跨会话内容泄漏。口令本身不写入日志或验收文档。
- **B5 状态：pass。** 本轮覆盖同一白名单用户的显式 @ 群聊收发，以及私聊/群聊按 chat scope 隔离上下文；第二位白名单用户的跨用户隔离未单独复测，但不影响本需求已验证的单用户多会话边界。群聊未 @ 属于 B6，已在后续用例中单独取证；非白名单拒绝按用户要求跳过。
- 用户本轮确认：非白名单账号分支跳过，不做验收。群聊未 @ 分支已实际发送并完成取证，不属于本次跳过项。
- 前一轮使用 `Stop-Process` 更换实例，只证明旧进程退出、新进程连通；不能记为优雅停止、未完成事件恢复或 C2/C6 整体通过。

## 2026-10-11 C 项进展

- 受控专项回归已执行：`22 passed`、1 个既有 OpenTelemetry 警告，覆盖同一 `event_id` 重复投递抑制、核心轮次恢复、租约接管、重连阈值/冷却、日报分片续传、空日报边界和运行器关闭兼容。该回归使用临时数据库、模拟 provider/连接和假时钟，不替代真实租户证据。
- C2 真实正常重启：旧后台诊断 PID 26012 在账本无非终态事件（19 completed、2 sessions、38 messages）时退出；同库同配置的新 PID 13264 启动并连接成功。用户随后在群聊显式 @，发送 17 字符测试消息；新进程记录 Gemini Flash Lite `STOP`、`degraded=false`、`delivery=sent`，账本增至 20 completed、2 sessions、40 messages。该结果确认重启后的会话连续性和新消息处理；由于旧实例是隐藏后台进程，本轮使用受控进程停止，未验证前台 `Ctrl+C` 的优雅关闭。
- C2 **正常重启子项通过**；受控未完成事件恢复已有证据，完整矩阵仍受优雅关闭和启动不扫描未完成事件的已知限制约束。
- C3 受控重连/冷却已由上述专项回归覆盖；真实断线需要隔离测试实例的网络路径。当前不关闭全局网络、不改防火墙或代理，因此真实断线与 300 秒冷却暂不执行。
- 原 `test/runtime/intelligence.db` 的两条 Story event_time 为 2026-09-13，不能直接用于本次当日日报；本轮保留原库不变，另建独立 C4 数据库和当日 fixture 完成日报测试。
- C4 真实日报复测：为避免改写原有历史库，创建独立 `test/runtime/c4-intelligence.db`，写入 2026-10-11 UTC/Asia/Shanghai 当日两条合成 Story，Importance 为 88.0、42.0。专用实例 PID 25712 在上海时间 21:25-21:35 窗口内连接成功并完成一片日报投递；账本记录 `status=completed`、`next_chunk=1`，生成内容包含日期、Daily digest、两条 Story 的排序、摘要、Importance 和证据链接。Gemini 摘要成功写入同一日报内容，服务端投递确认成功，stderr 为 0 bytes。
- C4 重启幂等复测：同一目标、窗口和 `c4-intelligence.db` 下停止 PID 25712，启动 PID 25780；新实例连接成功，投递账本的 `status=completed`、`next_chunk=1` 和 `updated_at` 均保持不变，未生成第二条 delivery 记录。窗口结束后专用实例已停止，数据库和日志保留。由于运行器没有 `already_claimed` tick 日志，幂等结论基于同库账本未变化、窗口内无第二次投递记录和客户端观察；不声称 SDK 层 exactly-once。
- C4 **服务端投递与重启幂等已通过，最终收件确认待用户确认**：若群成员确认收到第一条日报且未收到第二条重复日报，C4 可标记 `pass`；在此之前矩阵保持 `blocked`。实例已停止，不能据描述文件推断仍在线。

## 验收矩阵

状态只能填 `not_run`、`pass`、`fail` 或 `blocked`；模拟通过不得记为真实通过。

| ID | 场景 | 层级 | 需求 | 状态 | 脱敏证据 / 缺陷编号 |
|----|------|------|------|------|---------------------|
| B1 | 配置校验与真实长连接 | 真实 | FEIS-01/02/07 | pass | Lark 国际域连接、白名单入站、回复投递及本地 completed 账本已交叉确认 |
| B2 | 单聊文本、追问与本地引用 | 真实 | FEIS-03 | pass | 原私聊用户确认总和 30、依据与链接正确；6 个 completed 事件、1 会话、12 消息，最新回复 4 个引用且 degraded=false |
| B3 | Gemini 实际调用及禁用降级对照 | 真实 | FEIS-03 | pass | BOTH-7284 事件关联的 Flash Lite `STOP` 成功调用；2026-10-11 禁用对照无 Gemini 阶段、`gemini_calls=0`、degraded=true、delivery sent |
| B4 | 图片与图文混合 | 真实 | FEIS-03 | pass | BOTH-7284 单条 post：同一事件标签覆盖入站、Assistant、Gemini 和投递；post 文字 33 字符、媒体 1、图片 17,282 bytes、Flash Lite STOP、degraded=false、sent；客户端事实核对一致 |
| B5 | 群聊显式 @ 与用户/会话隔离 | 真实 | FEIS-03/05 | pass | 2026-10-11 两轮群聊 @ 均 Flash Lite STOP、非降级、sent；私聊/群聊各自独立会话。私聊口令随后在群聊询问，群聊回复“不知道”；账本为 19 completed、2 sessions、38 messages。第二位用户隔离未单独复测 |
| B6 | 非白名单与群聊未 @ 拒绝 | 真实 + 受控取证 | FEIS-05/07 | blocked | 2026-10-11 群聊未 @ 消息到达 `prepare` 并记录 `ignored`；无新事件、会话、消息或 Gemini 调用。非白名单账号分支按用户要求跳过，因此 B6 总项未完整验收 |
| C1 | 相同 event_id 重复投递、无新增发送或模型轮次 | 受控；真实重投单列 | FEIS-06 | pass | 受控重复投递抑制/租约/损坏回复测试通过；Lark 租户的同 event_id 真实重投仍未验证，当前没有事件重投 CLI |
| C2 | 重启与未完成事件恢复 | 受控 + 真实正常重启 | FEIS-06 | pass | 受控恢复测试通过；2026-10-11 旧 PID 26012 退出后，新 PID 13264 用同库恢复连接并处理群聊消息，账本 19→20 completed、2 sessions、38→40 messages，Flash Lite STOP、degraded=false、sent。停止方式为隐藏进程受控停止，未验证前台 Ctrl+C 优雅关闭 |
| C3 | 断线重连、阈值冷却与稳定复位 | 真实 + 受控 | FEIS-02/06 | blocked | 假连接/假时钟测试通过；真实断线、300 秒冷却和稳定复位尚未验证 |
| C4 | Story 日报、时区与重启不重发 | 真实 | FEIS-04/06 | blocked | 独立当日库真实投递已完成：PID 25712 生成并发送一片 Asia/Shanghai 日报，账本 completed/next_chunk=1；同窗口同库重启 PID 25780 后账本未变化、无第二条 delivery。等待群成员确认实际收件 |
| C5 | 部分投递失败和空日报 | 受控 | FEIS-04/06 | pass | 分片失败续传、空输出和 Asia/Shanghai 边界测试通过；未证明外部投递 exactly-once |
| C6 | 关闭飞书、完整回滚与旧 schema | 离线 + 真实进程停止 | FEIS-01/07 | pass | C4 专用 PID 25780 已核对后停止；LARK_ENABLED=false 与 INTELLIGENCE_ENABLED=false 的 `--check` 均退出 0 且不联网；基线/旧 schema 兼容测试 21 passed、1 个既有警告。未执行前台 Ctrl+C，隐藏实例停止已完成 |

## 缺陷与复测

| 编号 | 复现步骤 / 实际与预期差异 | 影响 | 修复路径 | 复测结果 |
|------|-------------------------|------|----------|----------|
| P5-UAT-01 | 追问沿用上一轮有效引用时，旧校验仅接受当前检索引用；引用被删除并残留空括号，回复被标为 degraded | 连续问答可读性及真实验收 | 仅恢复已持久化、服务端验证且出现在已加载历史文本中的引用；继续拒绝伪造引用，并清理空分隔符 | 离线回归、新模型真实 Assistant 探针及 Lark 原私聊复测通过；4 个有效引用、无降级，用户已确认 |
| P5-UAT-02 | Gemini 3 工具请求返回 thought signature；旧 provider-neutral 转换丢失该值，工具结果续轮返回 HTTP 400 INVALID_ARGUMENT | Gemini 工具调用无法完成第二轮 | 在 `GeminiToolCall` 内存内受限透传 opaque bytes，provider part 原样回送，repr 不显示值且不持久化 | 离线及 gemini-3.5-flash-lite 真实完整续轮通过，合成值 30 且 STOP |
| BLOCK-01 | 旧模型复测期间 Google 返回 429 RESOURCE_EXHAUSTED，限额桶为单项目、单模型、免费层每日请求 | 曾阻塞 B2/B3 修复后的线上证据 | 按用户要求保持 key 不变，切换至 gemini-3.5-flash-lite | 新模型真实调用成功，当前测试已绕过旧模型限额；旧模型额度状态未重查 |

只保留错误类别、状态码、脱敏摘要及私有证据编号。未经核实不要把“无回复”归因为权限，也不要把“有回复”归因为 Gemini 成功。

## 结论

- 真实会话链路：Lark WebSocket、白名单私聊、会话持久化、Story 检索与连续问答、纯图片、单条图文混合识别，以及群聊 @ 文字收发和私聊/群聊会话隔离均已有通过证据。
- B6 的群聊未 @ 子项已有真实拒绝证据；非白名单账号子项按用户要求跳过，不能将 B6 总项标记为通过。
- 权限/故障/日报：B6 非白名单分支按用户要求跳过；C2 正常重启和 C6 回滚已通过，C3 真实断线未执行，C4 等待外部收件确认。
- 无法现场复现的场景、模拟证据及残余风险：文本引用修复、纯图片、BOTH-7284 图文识别和 Gemini 禁用降级均有真实证据；工具 signature 和 B4 provider 关联证据通过；仍需完成群聊、拒绝、重复投递抑制、冷却和日报验收。
- 当前代码限制：无完整逐事件生产审计/replay CLI；外部调用与本地提交不是原子事务。2026-10-12 后持久接收、启动扫描和运行中账本轮询已有离线修复，见 `docs/phase1-6-fix-audit.md`，不补写为本轮真实崩溃验收通过。
- 后续阶段：用户已另行授权并推进 Phase 6/7；本表真实验收缺口和 B6 跳过例外继续保留，不因后续开发自动关闭。
- 当前不做 commit、push、部署或生产数据库迁移。
