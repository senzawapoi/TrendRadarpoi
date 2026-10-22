# Phase 5 真实验收与调试流程

状态：真实验收尚未整体通过；现场记录截至 2026-10-11，运行契约维护至 2026-10-14。
后续持久化恢复修复见 [Phase 1-6 修复审计](phase1-6-fix-audit.md)；文档整理不补造现场证据。
实际结果以 [05-LIVE-UAT.md](../.planning/phases/05-feishu-assistant/05-LIVE-UAT.md) 为准；本文是操作手册，不是全部用例已通过的证明。

真实运行目标为 Lark 国际版，固定使用 `https://open.larksuite.com`。
本文命令使用 `trendradar.integrations.lark` 和 `LARK_*`；旧 `FEISHU_*` 配置别名、
`tests/integrations/feishu/`、`feishu_events` 等内部兼容路径和 schema 名称保持不变。
已有 Windows 测试现场时先读 [test/README.md](../test/README.md)，沿用现有实例与数据库，
不要重复执行初始化或启动命令。本地验收不代表 Linux VPS 已部署。

## 1. 目标、边界与执行顺序

验证 `Lark -> 身份/会话 -> Assistant -> Gemini -> 回复` 的真实链路，以及 Story 日报。沿用现有配置与兼容路径，不引入 Phase 6、部署编排或新的工具权限。

| 顺序 | 验收层 | 能证明什么 |
|------|--------|------------|
| A | 离线预检与临时数据准备 | 安装、导入、代码契约、隔离配置、测试数据有效 |
| B | Lark/Gemini 真实会话 | 租户权限、长连接、文本/图片、群聊 @、真实模型与投递可用 |
| C | 受控故障复现 | 重复投递抑制、租约、冷却、部分投递和回滚契约；必须注明是否使用模拟组件 |
| D | 证据归档与复测 | 每个结论有对应证据，失败项修复后重测，决定是否进入 Phase 6 |

真实验收会调用外部服务、消耗额度并发送测试消息，执行前由维护者确认测试应用、账号、群和费用范围。只执行已确认的用例，文档整理不触发外部调用或新测试发送。缓存删除不是前置条件；不绕过工具安全策略，不删除 `output/`。

所有命令从仓库根目录执行。A1 及后文 pytest 命令使用不带真实凭据和 UAT 开关的预检 PowerShell；A2 起的真实操作使用另一独立 UAT PowerShell，并保持该会话的路径和配置。不要让 pytest 继承真实 key 或正在使用的 UAT 数据库路径。只运行一个连接该测试应用的本地 bot 实例；避免其他机器上的同应用实例抢收事件。保留当前未提交工作，不提交凭据、原始消息、截图中的身份信息或测试数据库。

## 2. A 层：离线预检

### A1. 固定环境与基线

```powershell
python --version
python -c "from importlib.metadata import version; print({p: version(p) for p in ['lark-oapi', 'google-genai', 'pytest']})"
python -m pytest tests -q
python -m trendradar.integrations.lark --help
git -c core.safecrlf=false diff --check
```

要求 Python 3.10+、`lark-oapi==1.7.3`。缺依赖时先按 `requirements.txt` 安装；pytest/Ruff 另用 `python -m pip install pytest ruff`。不要为了排错随意升级 SDK，桥接依赖该固定版本的内部接口。

本次流程编制时全量回归为 397 passed、1 个既有 OpenTelemetry 弃用警告。执行验收时记录自己的命令、时间、版本和结果，不直接沿用这个历史数字。

### A2. 隔离目录与开关

以下 A2/A3 用于首次新建临时 UAT 环境。已有 `test/runtime/` 现场时跳过，不生成第二套库；
脚本化初始化和只读验证见沙箱指南。尤其不要在用户发送真实测试消息时重建数据库。

```powershell
$ErrorActionPreference = 'Stop'
$env:PHASE5_UAT_DIR = Join-Path ([IO.Path]::GetTempPath()) ('trendradar-phase5-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $env:PHASE5_UAT_DIR | Out-Null
$env:INTELLIGENCE_DB_PATH = Join-Path $env:PHASE5_UAT_DIR 'intelligence.db'
$env:INTELLIGENCE_ENABLED = 'true'
$env:INTELLIGENCE_ASSISTANT_ENABLED = 'true'
$env:LARK_ENABLED = 'false'
$env:LARK_DELIVERY_ENABLED = 'false'
$env:GEMINI_ENABLED = 'false'
python -m trendradar.integrations.lark --config config/config.yaml --check
Test-Path -LiteralPath $env:INTELLIGENCE_DB_PATH
```

此时应输出 `Lark disabled; existing pipelines are unchanged.`，数据库存在性为 `False`。这只证明关闭路径无 I/O，不证明配置齐全。之后打开开关再做一次 `--check`。

`--config` 明确指定本仓库 YAML，避免继承的 `CONFIG_PATH` 指向别处；非空环境变量仍优先于 YAML。应用不自动加载 `.env`，不要认为文件存在就已注入。新增数据库只允许位于上述 UAT 目录。

### A3. 准备可验证的本地情报

以下代码只新建隔离库，拒绝覆盖已有数据库；写入两个标注为 synthetic 的 UAT Story，分数分别为 88 和 42。不运行真实抓取、不调用 Gemini。它验证的是 Phase 5 消费链路，不替代上游采集/聚类验收。

```powershell
@'
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trendradar.core.models import (
    Cluster, ContentItem, ImportanceBreakdown, Story,
    deterministic_cluster_id, deterministic_story_id,
)
from trendradar.intelligence.storage import IntelligenceStorage

root = Path(os.environ["PHASE5_UAT_DIR"]).resolve()
path = Path(os.environ["INTELLIGENCE_DB_PATH"]).resolve()
if not root.name.startswith("trendradar-phase5-") or path.parent != root:
    raise SystemExit("Refusing a database outside the dedicated UAT directory")
if path.exists():
    raise SystemExit("Refusing to overwrite an existing UAT database")
now = datetime.now(timezone.utc)
with IntelligenceStorage(path) as storage:
    for index, score in ((1, 88), (2, 42)):
        identity = f"phase5-uat-{index}"
        event_time = now - timedelta(minutes=index)
        item = ContentItem.create(
            title=f"UAT {index}: synthetic intelligence fixture",
            content=f"UAT fixture {index}. Test fact: budget is {index * 10} units.",
            url=f"https://example.invalid/phase5-uat/{index}",
            source="rss:phase5-uat", domain="ai",
            collected_at=now, published_time=event_time,
            tags=["UAT"], metadata={"source_content_id": identity, "synthetic": True},
        )
        cluster = Cluster(
            id=deterministic_cluster_id([item.id]), member_ids=[item.id],
            domain="ai", event_time=event_time, last_activity_at=now,
        )
        story = Story(
            id=deterministic_story_id(identity), identity_key=identity,
            title=item.title, summary=item.content, domain="ai",
            event_time=event_time, last_activity_at=now, member_ids=[item.id],
            importance=ImportanceBreakdown(score=score, reasons=["Synthetic UAT score"]),
            metadata={"cluster_id": cluster.id, "synthetic": True},
        )
        storage.write_batch([item])
        storage.upsert_story_batch([cluster], [story])
    print("schema", storage.connection.execute("PRAGMA user_version").fetchone()[0])
    print("content_items", storage.count(), "stories", storage.count("stories"))
'@ | python -
```

当前预期 `schema 6`、`content_items 2 stories 2`。两个 `example.invalid` 链接刻意不可访问，验收只核对引用与库中证据一致，不把它们当真实新闻。当天完成本轮测试；跨日验收日报时重新准备一个独立测试目录，避免数据时间窗口干扰。旧 schema 5 取证保留为历史，不覆盖原库来更新数字。

确认没有指向 `output/intelligence.db` 后才进入真实联调。

## 3. B 层：真实会话验收

### B1. 应用、凭据与长连接

先在Lark开放平台完成测试应用的机器人能力、长连接事件订阅 `im.message.receive_v1`、消息接收/回复/发送与消息资源读取相关权限审批，发布使设置生效。确认测试账号在应用可用范围内。具体 scope 标识和控制台栏目以当前租户界面为准，本次未在线核实，不提供猜测的权限名称。

身份字段支持 `open_id`、`user_id`、`union_id`，不是昵称。先只启用单聊并用一个字段、一位白名单用户验证，避免同时调试多种映射。机器人 ID、用户 ID 和群 chat ID 不能互换。旧 webhook 配置不等于应用机器人配置。

以下输入不会把明文密钥写进命令历史；仍须关闭屏幕录制和自动采集调试变量，环境内凭据本身就是敏感信息。已经使用受控启动器注入时可跳过交互输入。

```powershell
foreach ($name in @('LARK_APP_ID', 'LARK_APP_SECRET', 'GEMINI_API_KEY')) {
    $secret = Read-Host $name -AsSecureString
    try {
        if ($secret.Length -eq 0) { throw ('Empty credential: ' + $name) }
        Set-Item -LiteralPath ("Env:" + $name) -Value ([Net.NetworkCredential]::new('', $secret).Password)
    } finally {
        $secret.Dispose()
    }
}
$allowedOpenId = Read-Host 'Test user open_id'
$env:LARK_IDENTITY_FIELDS = @{open_id = @($allowedOpenId)} | ConvertTo-Json -Compress
$env:GEMINI_MODEL = Read-Host 'Account-verified Gemini model ID supporting images and tools'
if ([string]::IsNullOrWhiteSpace($env:GEMINI_MODEL)) { throw 'Explicit Gemini model ID required' }
$env:LARK_ENABLED = 'true'
$env:GEMINI_ENABLED = 'true'
$env:LARK_ALLOWED_CHAT_TYPES = 'p2p'
$env:LARK_DELIVERY_ENABLED = 'false'
python -m trendradar.integrations.lark --config config/config.yaml --check
```

必须看到 `Lark configuration is ready; no network or storage was accessed.`。只看退出码 0 不够，关闭路径也返回 0。此检查不验证密钥、SDK 在线行为、模型可用性、租户权限或 SQLite 是否可写。

默认模型配置是 `gemini-2.0-flash`，不能据此假设当前账号可调用。显式填写实际确认支持文本、图片和工具的模型 ID。默认单请求超时 30 秒、最多尝试 3 次，另有退避、排队、工具轮次与消息发送；不要把 30 秒当整轮问答的总时限。

```powershell
python -m trendradar.integrations.lark --config config/config.yaml
```

后续需要调试器时，用 IDE 的 Python 模块调试方式启动同一模块、同一参数、同一环境和工作目录，确保支持工作线程；不要同时再开第二个 bot。看到 `Lark connection state` 的 `connected` 只代表连接状态，仍需发消息验证。

### B2. 单聊文本、证据与追问

1. 白名单用户向机器人单聊发送 **`UAT`**，只发这个词，不附编号或长句。
2. 验证检索到 A3 的两条测试 Story，核对测试事实预算 10/20、来源链接和引用。模型不一定逐字段复述分数；检索结果和后续日报必须保持 88 高于 42，不允许模型篡改事实或排序。
3. 上一轮已给出预算后，追问“根据上一轮两条 UAT 的预算，计算总和并说明依据”，预期总和 30。记录同会话连续回复，禁止凭“回答像 AI”判断成功。
4. 先完成 B3 的调用取证，再把该场景标为真实 Gemini 通过。追问检索为空时检查对话历史是否已带入已知事实。

第一条只用 `UAT` 是为了隔离检索变量：当前本地查询按空白分词并组合匹配条件，自然语言长句可能匹配不到种子。记录这种检索限制，不把“无匹配”直接归因为数据库或 Gemini 故障。

### B3. Gemini 成功与降级对照

默认生产日志没有逐事件模型用量和成功结果。Windows 沙箱可用
[`phase5_diagnostics.py`](../test/phase5_diagnostics.py) 替代普通入口，按
[沙箱指南](../test/README.md) 获取 `UAT` 元数据；不得同时启动两个实例。
同一进程内的 HMAC 标签关联入站、Assistant、Gemini 和投递；结果包含结束原因、用量和逻辑
生成调用次数，不保存原始 ID 或内容，也不代表 SDK HTTP 重试次数。此入口尚不记录授权拒绝
细分原因、ledger claim 分支或 scheduler tick，不能替代 B6/C 层取证。

不使用沙箱入口时，可在已有 IDE 设置只输出脱敏值的**不停顿日志点**，一次只发一条消息并等待完成。
根据以下函数及语句定位，不依赖易变的行号。

| 位置 | 记录什么 | 判据 |
|------|----------|------|
| `ai/client.py::GeminiClient._generate` 中 `client.models.generate_content` | 实际 client 类型模块、配置模型名、尝试序号 | 实际客户端来自 `google.genai`；到达调用点只证明尝试 |
| `ai/assistant.py::AssistantService._generate` 中 `chat()` 返回后、`_result_parts(result)` 前 | 请求关联哈希、`repr(result)`、`[(i.mime_type, len(i.data)) for i in request.images]` | 有最终文本结果，模型/用量/结束原因可追溯；工具调用中间结果不能冒充最终答案 |
| `feishu/handler.py::FeishuHandler.process` 中最终 `self.client.reply(...)` 前 | 同一请求关联哈希、`reply.degraded` | 成功场景要求非降级；与实际Lark回复时间及内容交叉核对 |
| 实际测试会话 | 脱敏后的答复、事实正确性、接收时间 | 文本正确；图片场景还需视觉事实正确 |

请求关联可以在本地对 `request.request_id` 和 `event.request_id` 计算同一种 SHA256 摘要，归档仅留短哈希和用例别名。不要输出真实身份、完整事件、提示词、图片字节或原始 SDK 响应。`repr(result)` 指本项目脱敏的 `GeminiResult`，不是任意 SDK 对象的 repr。不要在调试表达式里重新调用 `chat()`、`generate_content()` 或发送函数。

做降级对照时，先 Ctrl+C 正常停止并等待进程退出，设置 `GEMINI_ENABLED=false` 再启动；发送新的 `UAT` 消息。预期出现 `Degraded:` 和本地证据降级说明，且不调用 Gemini。再停止、恢复 `GEMINI_ENABLED=true`、启动并发新消息，取得非降级证据。运行中改父 Shell 环境不会改变已启动进程的配置。

“真实模型返回成功，但最终回复因引用清理/截断被降级”要单独记录，不能算完全成功，也不等于没有调用模型。仅有数据库记录、`available=True`、用量面板总量增长或没有降级字样，都不足以独立证明本条消息实际成功使用 Gemini。无法取得可关联证据时记 `blocked: provider_evidence_missing`。

### B4. 图片与图文混合

1. 准备不含隐私的清晰 PNG/JPEG，图中放本轮独有编号和金额/颜色等可核对事实，文字消息不要泄露答案。
2. 单聊发送图片消息。预期能够正常处理附件，模型输入图片数量非零，答复与图片相关；只有“收到图片”的泛化回复不够。
3. 在**同一条富文本 post** 中加入图片和“请读出图中的编号和金额”。核对识别事实、B3 模型元数据、非降级标记及Lark实际回复。
4. 群聊图文留到 B5 启用群聊、检查和重启后补测，在同一条 post 中真实 @ 机器人；普通文本中手打机器人名字不算提及。当前 B1 的 p2p-only 配置会忽略群消息。

限制为最多 4 张、单张 4 MiB、总计 8 MiB。当前校验识别 PNG/JPEG/GIF/WebP 文件头，提供商实际格式支持另验，第一轮用 PNG/JPEG。边界超限测试见 C 层的现有离线用例，不上传大文件去试探服务限额。

使用沙箱诊断时，同一事件标签应同时出现：`inbound` 的文字长度和媒体数均大于零，
`assistant_input`、`gemini_input` 的图片数大于零，最终 `gemini_result` 成功，
`assistant_result.degraded=false`，以及 `delivery.outcome=sent`。再核对实际收件与新视觉事实。
先前在会话中识别过的图不能用来排除历史答案；后续复测使用未发送过的新图，并保留旧图证据。

纯图片只获得 `[Image attachment]` 占位文本，没有额外精确 OCR 指令，因此逐字 OCR 的判据放在明确提问的图文 post 上。图片字节只用于当前请求，不进入后续会话历史；“先发图，再问上一张图”不替代单条图文测试。普通附件或图片 URL 也不等于受支持的图片消息。

`Image processing is unavailable. Please retry with a smaller image or text.` 是媒体失败；先排查消息资源权限、支持的消息类型、文件头和大小，不直接归咎于 Gemini。

### B5. 群聊、白名单与会话隔离

停止进程后配置并重启：

```powershell
$env:LARK_ALLOWED_CHAT_TYPES = 'p2p,group'
$env:LARK_BOT_ID = Read-Host 'Bot open_id'
python -m trendradar.integrations.lark --config config/config.yaml --check
python -m trendradar.integrations.lark --config config/config.yaml
```

确认机器人已加入测试群。用Lark提及控件选择该机器人，测试 `@机器人 UAT`、单条图文，再测试不 @ 的 `UAT`。

同一白名单用户在私聊说一个无敏感内容的测试口令，在群聊询问该私聊口令；群会话不得泄漏。需要验证跨用户隔离时，临时加入第二位授权测试者，各自使用不同口令，完成后恢复原白名单并重启。同用户同会话可延续上下文，换用户/换聊天不应共享。

### B6. 非授权消息的拒绝取证

用可访问测试应用、但不在 bot 白名单中的账号发单聊和群聊 @；另用白名单账号发群聊未 @ 消息。非白名单账号不在应用可用范围时，消息可能根本不到达本进程，不能据此声称 bot 鉴权通过。

最少取得三组证据：事件确实到达 `FeishuHandler.prepare`；身份/提及分支明确返回忽略；没有进入 `respond`、媒体下载或模型调用。再比较受控安静时段前后的事件/会话计数，作为辅助证据。不得启用 SDK 原始事件全文日志来取证。

若只观察到“没回复”，记为证据不足，不判通过。默认 worker 不输出逐事件状态，必要时用 IDE 不停顿日志点，记录分支标签和计数而非身份值。具体离线拒绝用例及数据库只读快照见后文。

```powershell
python -m pytest tests/integrations/feishu/test_handler.py tests/ai/test_media.py -v -ra
```

重点拒绝用例为 `test_rejected_events_have_no_provider_media_or_session_side_effects` 和 `test_authorization_happens_before_content_access`。非白名单账号必须不命中任何一个已配置身份字段；匹配为任一字段命中即可，不是多字段同时匹配。建议采用授权 A 成功、非授权 B 被拒绝、A 再次成功的对照顺序。当前没有聊天 ID 白名单，不要把身份白名单解释成只能在指定群使用。

## 4. C 层：幂等、恢复、冷却与日报

### C1. 同一事件重复投递

现有入口没有事件重投 CLI，也未核实租户控制台是否能重投指定事件。再次发相同文字是新事件，不是本测试。

先执行确定性复现：

```powershell
python -m pytest tests/integrations/feishu/test_idempotency.py -v -ra
```

重点核对 `test_duplicate_delivered_event_is_suppressed_after_restart`：同一模拟 payload 处理完成后，关闭并重建 Assistant/ledger 再提交，模型调用 1 次、回复接口调用 1 次，第二次返回 `already_delivered`。已成功送达的重复事件不得再次回复；发送失败后的保存回复重试由单独测试覆盖。完整测试还覆盖租约、owner fencing、损坏回复和核心轮次已保存后的恢复。

真实重投只在掌握同一个 `event_id` 的可信重投方式后执行；观察 ledger 的 `duplicate_delivered` 分支、相同请求摘要、无新增模型调用和无新增发送。没有入口就把“真实重投”单列为未验证，保留模拟证据，不伪造通过。

### C2. 重启与未完成事件

正常场景：B2 成功后 Ctrl+C 等待正常退出，使用同库同配置重启，验证已有会话连续性与新的授权消息可正常处理。

故障场景在测试库和模拟组件中做，不对真实 bot 强杀制造事故：

- 有效租约内重复事件进入 busy 状态并回复处理中提示。
- 租约到期后，未达到最多三次 claim 的事件可以接管，旧 owner 不能提交覆盖新 owner。
- `test_recovery_after_core_turn_persisted_before_ledger_completion` 模拟核心轮次已保存、事件账本尚未完成：推进假时钟并重投原事件，预期复用核心回复而非重调模型。
- `test_corrupt_completed_event_fails_closed` 验证损坏回复不作为有效结果发送。

**当前实现与限制：**授权后的准备载荷先持久化，再进入 32 项内存队列；combined 模式启动扫描未完成事件并在运行中轮询，独立 Worker 从账本取工作。无效或耗尽记录不会无限重放。相关离线回归见 `test_repair_recovery.py` 和 [修复审计](phase1-6-fix-audit.md)。SDK 的实际确认/重投、入站持久化前崩溃和外部发送后本地提交前崩溃仍有不确定窗口；正常重启与模拟恢复不证明任意崩溃后无损或外部 exactly-once。

### C3. 长连接与冷却

```powershell
python -m pytest tests/integrations/feishu/test_reconnect.py -v -ra
```

精确控制器验收使用 `test_retry_threshold_cooldown_and_single_owner` 的假连接、假时钟和零 jitter：阈值 3、冷却 10 秒时，等待序列应为 retrying/1、retrying/2、cooldown/10、retrying/1。SDK 清理与 endpoint discovery 用例也要检查，存在 skip 时不当作验证完成。

真实步骤：确保无正在处理的问答/日报，仅在可隔离测试实例网络的环境中做短时断连，不关闭整机网络或影响生产。保持进程运行，观察失败、冷却、恢复网络、重新连接，最后发送新的 `UAT` 验证实际恢复。无法单独隔离测试流量时暂停该项，不临时改全局防火墙或代理。

默认五次连续失败进入 300 秒冷却；前面的等待为 1/2/4/8 秒加 jitter，另计网络超时与关闭耗时。冷却中恢复网络不会立即唤醒。状态每 0.5 秒采样且仅打印变化，可能漏过瞬间状态；精确尝试数需 IDE 日志点或受控测试佐证。

当前“稳定 60 秒”实现按连接成功至关闭完成的时间跨度计算，包含关闭耗时，不能据此宣称严格测量了在线稳定时长。若短连接因关闭慢而误复位，记录缺陷并修复，不以模拟测试通过掩盖现场差异。

默认日志没有时间戳，可为普通终端启动加外部采集时间；使用它替换启动命令，不另起实例：

```powershell
python -u -m trendradar.integrations.lark --config config/config.yaml 2>&1 |
    ForEach-Object { '{0:o} {1}' -f (Get-Date), $_ }
```

这是采集时间，不是提供商事件时间。不要假设有现成 `run_id`/`cid` 或 SDK 错误码。没有恢复、无冷却的连续密集重试、残留连接任务都应阻断本项。

### C4. Story 日报真实投递

先停止 bot，确认当天测试 Story 仍在，确认目标为专门测试聊天。以下生成上海时区从约两分钟后开始、持续约十分钟的测试窗口；靠近午夜时拒绝执行，改在同一日内重新安排。配置生效后不要再生成新窗口来做幂等测试。

```powershell
$shanghai = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTimeOffset]::Now, 'China Standard Time')
$windowStart = $shanghai.AddMinutes(2)
$windowEnd = $shanghai.AddMinutes(12)
if ($windowEnd.Date -ne $shanghai.Date) { throw 'Choose a test window within one Shanghai day' }
$env:LARK_DELIVERY_TARGET = Read-Host 'Dedicated test chat_id'
$env:LARK_DELIVERY_TIME = $windowStart.ToString('HH:mm')
$env:LARK_DELIVERY_END = $windowEnd.ToString('HH:mm')
$env:LARK_DELIVERY_ENABLED = 'true'
python -m trendradar.integrations.lark --config config/config.yaml --check
python -m trendradar.integrations.lark --config config/config.yaml
```

等待窗口到达并观察真实收件，核对两条 UAT Story、88 在 42 前、Importance 和证据链接。记录接收时间、内容摘要及第 5 节 ledger 快照。日报摘要是否使用 Gemini另按 B3 方式取证，确定性日报本身不要求 Gemini 成功。

确认 `completed` 且 `next_chunk == chunks` 后，在**同一目标、上海日期、窗口、数据库**下停止并重启。在 `DeliveryScheduler.tick()` 的 `claimed is None` 返回分支设置不停顿日志点，确认两次检查都返回 `already_claimed`，同时实际会话不再收到该窗口日报。运行器没有 tick 日志，已完成窗口再次检查也不更新账本；只等待或比较 snapshot 不够。无法观测 tick 时，只能记录“观察期内未重复收到”，不能判为重启幂等验证通过。不要重新执行窗口生成代码、更换目标或删除账本，这些动作会改变测试身份或破坏证据。

调度启动时立即 tick，此后约每 60 秒检查，但与 Assistant 共用一个工作线程，长轮次会延迟。不要只等几秒就判失败。默认窗口可能全天，未设置窄窗口直接打开日报可能启动即发送。

窗口两端按分钟包含；如 09:00 为结束时间，09:00:59 仍在窗口内。跨午夜时，凌晨段的去重日期属于前一天，但内容选择取执行时上海日历日，不能假设等于窗口起始日。此语义须通过下列模拟边界测试理解，再决定是否适合实际使用。

### C5. 部分失败、空日报与边界

```powershell
python -m pytest tests/integrations/feishu/test_scheduler.py tests/integrations/feishu/test_delivery.py -v -ra
```

`test_partial_failure_retry_resumes_saved_chunks_not_regenerated_output` 模拟两片内容和发送结果 True/False/True：首次失败后 `failed/next_chunk=1`，重建 scheduler 再 tick 只重试第二片、复用分片 UUID、不重生成内容，最终 `completed/next_chunk=2`。

`test_empty_and_failed_output_do_not_consume_window`、`test_shanghai_window_edges_and_overnight_date_identity` 分别覆盖空输出与上海时区边界。这些测试不触发真实发送，不证明Lark UUID 去重期限或外部严格 exactly-once。

日报失败和空输出可在窗口内继续尝试，**没有事件 claim 的三次上限**。持续失败时主动停止测试/关闭日报，不任其反复调用；保留失败状态再排查。窗口外不续传；改目标、改窗口或到新一天会产生新 key。

### C6. 停止、回滚与兼容

1. 前台实例按 Ctrl+C 停止并等待真正退出。隐藏后台实例须先按沙箱指南核对 PID、命令和启动时间，在停止发送且无处理中工作时安排停止；另一个终端的 Ctrl+C 不会停止它。停止可能要等当前有限超时的调用结束。
2. 在同一启动环境执行以下验证。修改开关不会热更新旧进程，也不会撤回消息或降低数据库版本。

```powershell
$env:INTELLIGENCE_ENABLED = 'true'
$env:LARK_ENABLED = 'false'
python -m trendradar.integrations.lark --config config/config.yaml --check
$env:LARK_ENABLED = 'true'
$env:INTELLIGENCE_ENABLED = 'false'
python -m trendradar.integrations.lark --config config/config.yaml --check
```

两次均应报告关闭并退出。第二次刻意恢复 Lark 开关，单独验证 Intelligence 关闭逻辑；使用 `--check` 避免回归缺陷导致意外联网。随后在 A1 的无真实凭据、无 UAT 路径覆盖的预检终端执行：

```powershell
python -m pytest tests/baseline tests/integrations/feishu/test_runner.py tests/intelligence/test_integration.py -v -ra
```

离线兼容测试验证旧入口/schema 和 AI 回滚。不要为“测试兼容”直接跑会抓取/推送的旧生产命令。正式环境旧流水线实跑需另行确认测试目标与数据备份。

确认 bot 已退出后再关闭专用 PowerShell；仅关闭终端不会终止已分离的后台进程或清除其继承的凭据。未改变系统持久环境或原配置时无需全局清理。私有证据目录先保留，按维护者确认的保留周期处理，不自动删数据库，更不碰 `output/`。

## 5. 只读快照与证据

在 bot 空闲时于 IDE 调试控制台之外执行下列脚本，前后各采一次；若用另一个 PowerShell，先只设置相同的两个 UAT 路径变量，不需要注入密钥。不要同时发送其他测试消息。
已有本地沙箱时，`PHASE5_UAT_DIR` 指向仓库下的 `test/runtime/`，`INTELLIGENCE_DB_PATH` 指向其中的 `intelligence.db`，不另行初始化。

脚本校验目录并用 `sqlite3 mode=ro` 查询，不使用会迁移 schema 的 `IntelligenceStorage`，不使用会忽略 WAL 变化的 `immutable=1`。仅输出计数、状态和时间，不输出正文、原始 ID、身份或图片。

```powershell
@'
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

root = Path(os.environ["PHASE5_UAT_DIR"]).resolve()
path = Path(os.environ["INTELLIGENCE_DB_PATH"]).resolve()
allowed_root = root == Path("test/runtime").resolve() or root.name.startswith("trendradar-phase5-")
if not allowed_root or path.parent != root or not path.is_file():
    raise SystemExit("Refusing a missing or non-UAT database")
local_date = datetime.now(ZoneInfo("Asia/Shanghai")).date()
start = datetime.combine(local_date, time.min, ZoneInfo("Asia/Shanghai"))
params = {
    "start": start.astimezone(timezone.utc).isoformat(),
    "end": (start + timedelta(days=1)).astimezone(timezone.utc).isoformat(),
}
queries = {
    "stories_today": (
        "SELECT COUNT(*) AS stories, SUM(importance_score=88) AS score88, "
        "SUM(importance_score=42) AS score42 FROM stories "
        "WHERE last_activity_at>=:start AND event_time<:end"
    ),
    "events": (
        "SELECT status, attempts, COUNT(*) AS events, "
        "SUM(reply_json IS NOT NULL) AS saved_replies, "
        "SUM(json_valid(reply_json)) AS valid_json, "
        "SUM(status='processing' AND julianday(lease_until)<=julianday('now')) AS expired "
        "FROM feishu_events GROUP BY status, attempts"
    ),
    "sessions": (
        "SELECT COUNT(*) AS sessions, COUNT(DISTINCT principal_id) AS principals "
        "FROM assistant_sessions"
    ),
    "messages": (
        "SELECT role, COUNT(*) AS messages, COUNT(DISTINCT request_id) AS requests "
        "FROM assistant_messages GROUP BY role"
    ),
    "deliveries": (
        "SELECT status, next_chunk, "
        "CASE WHEN json_valid(chunks_json) THEN json_array_length(chunks_json) END AS chunks, "
        "COUNT(*) AS deliveries, MIN(updated_at) AS oldest_update, MAX(updated_at) AS newest_update "
        "FROM feishu_deliveries GROUP BY status, next_chunk, chunks"
    ),
}
with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)) as conn:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("BEGIN")
    result = {"schema": conn.execute("PRAGMA user_version").fetchone()[0]}
    for name, query in queries.items():
        result[name] = [dict(row) for row in conn.execute(query, params)]
    print(json.dumps(result, ensure_ascii=True, indent=2))
'@ | python -
```

全库聚合只有在单测试、无并行活动时才可辅助归因。计数不增不能证明没有模型调用；JSON 合法不代表回复 DTO 有效。`feishu_events.completed` 表示本地已确认发送成功；它仍不等于外部平台或收件人已实际看到，且该表没有发送消息 ID。实际收件必须另取证。

若需要针对单一事件查看状态，使用已有可信事件 ID 的参数化查询，在私有本地环境操作，不把 ID 值打印或写进仓库。不要直接编辑账本以“修复”状态。

## 6. 故障定位顺序

| 现象 | 先查什么 | 不应得出的结论 |
|------|----------|----------------|
| `--check` 关闭或报缺配置 | 开关、显式 YAML、环境注入、身份字段和群 bot ID | 退出码 0 不等于完整配置通过 |
| 无 connected / 反复重试 | 单实例、固定 SDK、凭据/租户状态、测试网络、冷却等待 | 仅凭无消息判断 Gemini 失败 |
| connected 但无回复 | 事件是否到达、授权/提及分支、消息类型、队列/worker、最后发送结果 | 默认静默忽略不等于成功鉴权取证 |
| 有回复但本地降级 | 实际模型、key 注入、调用/结果日志点、超时或截断/引用处理 | 有回复不等于 Gemini 成功 |
| 图片失败 | 事件类型/资源权限、大小/文件头、下载结果、图片入模元数据 | 图片-only 泛化回答等于精确 OCR |
| 重复投递多次调用 Gemini 或发送 | 同事件同 scope、已保存轮次、lease/attempts、当前是否为新消息 | 同文字是同事件 |
| 事件 completed 却没收到 | 回复发送函数结果、Lark实际会话、断线/服务错误 | 已存回复等于已经发送 |
| 日报不来 | 开关/目标、上海窗口、当天 Story、已完成 claim、分片进度、实际发送 | 立即反复改窗口或删账本重试 |
| 日报重发 | 目标/日期/窗口是否改变、是否同一数据库、是否已确认全部分片 | 本地幂等等于提供商外部严格一次 |

没有错误码就记录已知阶段和结果，不凭猜测填入“权限不足”“限流”等具体根因。身份越权、错群投递、生产数据被改、密钥泄漏迹象出现时停止真实发送并优先处理，不继续 Phase 6。

## 7. 归档与准入

逐项填写 [05-LIVE-UAT.md](../.planning/phases/05-feishu-assistant/05-LIVE-UAT.md)：用例、层级、时间、预期/实际、脱敏证据编号、缺陷与复测结果。私有截图和记录存 UAT 目录，仓库只放脱敏结论。

准入要求：真实文本/图文、身份拒绝、群聊边界、恢复连接、至少一次日报及同窗口重启不重发有证据；受控重复投递抑制/租约/部分失败/回滚测试通过；没有未解决的越权、错误投递或核心功能缺陷。无法在租户触发的真实重投、崩溃后入站消息恢复等须明确记录未验证范围，不能被模拟结果覆盖。

当前明确的限制包括：默认生产日志缺少逐事件审计（本地沙箱有显式诊断入口，但不覆盖全部故障场景）、没有现成事件重投 CLI、模型/发送可观测性有限、跨午夜去重日与取数日不同、外部接受请求与本地提交之间存在不确定窗口。持久接收与启动/运行中恢复已有离线修复，不能继续当作未实现，也不能当作真实崩溃验收已通过。若残余限制不满足实际使用要求，先修复并复测。

用户已另行授权并推进 Phase 6/7，Phase 5 的未完成真实用例仍保留，不因后续开发而标为通过。Phase 7 正式部署、缓存删除和全仓 Ruff 整理均不是本流程的前置条件。

## 8. 核对依据

- [运行与配置契约](intelligence.md#lark-assistant)、[Phase 5 离线验证](../.planning/phases/05-feishu-assistant/VERIFICATION.md)。
- [运行器](../trendradar/integrations/feishu/__main__.py)、[配置解析](../trendradar/core/settings.py)、[身份映射](../trendradar/integrations/feishu/session.py)。
- [消息处理](../trendradar/integrations/feishu/handler.py)、[事件账本](../trendradar/integrations/feishu/ledger.py)、[重连控制器](../trendradar/integrations/feishu/transport.py)。
- [日报调度](../trendradar/integrations/feishu/scheduler.py)、[日报内容](../trendradar/integrations/feishu/delivery.py)、[SQLite schema](../trendradar/intelligence/storage.py)。
- [核心 Gemini 客户端](../trendradar/ai/client.py)、[Assistant](../trendradar/ai/assistant.py)、[本地检索](../trendradar/ai/retrieval.py)、[媒体限制](../trendradar/ai/media.py)。

置信度：源码、现有测试契约和已试跑离线片段为高；实际租户权限、模型在线能力及真实投递结果在执行前均为未知。
