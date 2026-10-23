# MCP Client Setup / MCP 客户端配置

[中文首页](../README.md) | [English README](../README-EN.md) | [Configuration / 配置与关键词](configuration.md)

本页中英对照，适用于使用 `mcpServers` JSON 的本地 stdio 客户端。客户端启动 Python 子进程并通过标准输入输出通信；无需预先运行服务器，也不需要 HTTP 地址或端口。

This bilingual guide covers local stdio clients using `mcpServers` JSON. The client launches a
Python subprocess and communicates through stdin/stdout. Do not pre-start a separate server;
stdio needs no HTTP URL or port.

## Interpreter / 解释器

准备 Python 3.10+ 环境（生产使用 3.12），并用同一个解释器安装仓库依赖。以下路径均为示例；替换为实际仓库及已有虚拟环境路径。

Use Python 3.10+ (3.12 in production) and install this checkout's dependencies with the same
interpreter that the client will launch. All paths below are examples; replace them with the
actual checkout and virtual environment paths.

```powershell
Set-Location 'C:/work/TrendRadar'
& 'C:/work/TrendRadar/.venv/Scripts/python.exe' -m pip install -r requirements.lock
```

Linux/macOS 使用对应的绝对解释器路径，例如 `/home/user/TrendRadar/.venv/bin/python`，同时替换下面所有仓库路径。查询本地历史不需要 Google 或 Lark 凭据。

On Linux/macOS, use an absolute interpreter path such as `/home/user/TrendRadar/.venv/bin/python`
and replace all checkout paths below. Local historical queries need no Google or Lark credentials.

## Client JSON / 客户端 JSON

将以下条目合并到客户端的 MCP 设置，保留已有服务器。保存后重新连接该 MCP 服务。

Merge this entry into the client's MCP settings, preserving other servers, then reconnect it.

```json
{
  "mcpServers": {
    "trendradar": {
      "command": "C:/work/TrendRadar/.venv/Scripts/python.exe",
      "args": [
        "-c",
        "import os, runpy; os.chdir('C:/work/TrendRadar'); runpy.run_module('mcp_server.server', run_name='__main__')",
        "--transport",
        "stdio",
        "--project-root",
        "C:/work/TrendRadar"
      ],
      "env": {
        "PYTHONUTF8": "1",
        "CONFIG_PATH": "C:/work/TrendRadar/config/config.yaml",
        "FREQUENCY_WORDS_PATH": "C:/work/TrendRadar/config/frequency_words.txt"
      }
    }
  }
}
```

`-c` 只用 Python 标准库切换目录并运行现有模块，等价于在仓库根目录执行
`python -m mcp_server.server --transport stdio --project-root <absolute-root>`。
这样不依赖客户端是否支持 `cwd` 字段，也能处理带空格的路径。如果路径含单引号，需相应调整 `os.chdir(...)` 内的 Python 字符串引号。

The `-c` bootstrap only changes directory and runs the existing module using Python's standard
library. It is equivalent to running `python -m mcp_server.server --transport stdio --project-root
<absolute-root>` from the checkout root. This works without a client-specific `cwd` field and
supports spaces in paths. If a path contains an apostrophe, adjust the Python string quoting
inside `os.chdir(...)` accordingly.

**路径约定：** `--project-root` 选择 MCP 的配置与数据根目录，本身不会切换工作目录，也不会将模块加入 Python 导入路径。
当前传统 MCP 查询直接读取 `<root>/config/config.yaml`、`<root>/config/frequency_words.txt` 以及
`<root>/output/news/`、`<root>/output/rss/`。上例故意让这些路径与环境变量一致；不要指望仅修改
`CONFIG_PATH` 或 `FREQUENCY_WORDS_PATH` 就移动所有 MCP 读取。CLI 没有 `--config` 参数。

**Path contract:** `--project-root` selects MCP's configuration/data root; it does not change
the working directory or make the Python module importable. Current legacy MCP queries read
`<root>/config/config.yaml`, `<root>/config/frequency_words.txt`, `<root>/output/news/` and
`<root>/output/rss/` directly. The example deliberately aligns these with the environment
variables; changing only `CONFIG_PATH` or `FREQUENCY_WORDS_PATH` does not relocate every MCP
read. There is no `--config` CLI option.

## First Queries / 首次查询

| Action / 操作 | Expected result / 预期 |
| --- | --- |
| `resolve_date_range(expression="today")` | Local date parsing; no collected data required / 本地日期解析，不依赖已采集数据。 |
| `get_system_status()` | Local data/cache status; not VPS readiness or provider authentication / 本地数据与缓存状态，不代表 VPS 就绪或提供商鉴权通过。 |
| `get_latest_news(limit=10)` | Reads collected news; an empty database is not a connection failure / 读取已采集新闻，空库不等于连接失败。 |
| `get_trending_topics(extract_mode="auto_extract", top_n=10)` | Extracts frequent words from existing titles without a keyword list / 从已有标题提取高频词，不需要预设词表。 |

配置文件修改后重连服务，以避免缓存旧设置。数据查询需有采集器产生的本地记录；MCP 连接本身不会自动采集。
`trigger_crawl` 和 `sync_from_remote` 会访问网络，并可能写入数据，不要用作连接检查。

Reconnect after changing configuration to avoid cached settings. Data queries require local
records produced by collectors; connecting MCP does not collect them automatically.
`trigger_crawl` and `sync_from_remote` access the network and can write data, so they are not
connection checks.

## Current Limits / 当前限制

| Symptom / 现象 | Explanation / 说明 |
| --- | --- |
| `ModuleNotFoundError` | Check the interpreter, installed dependencies and the `os.chdir` checkout path / 核对解释器、依赖安装及 `os.chdir` 仓库路径。 |
| Configuration or data not found / 找不到配置或数据 | Check `--project-root` and its `config/` and `output/` directories; do not assume the client's working directory / 检查根路径及其配置、数据目录，不要依赖客户端默认工作目录。 |
| JSON/protocol error during startup / 启动时 JSON 或协议错误 | The current CLI prints a banner to stdout before starting MCP; strict clients may reject it. Path settings do not fix this existing issue. Do not redirect all stdout, which also carries MCP messages / 当前 CLI 在启动 MCP 前向 stdout 打印横幅，严格客户端可能拒绝；路径设置不能修复此现有问题，也不能整体重定向承载协议的 stdout。 |
| Keyword-topic query fails / 关键词话题查询失败 | `keywords` currently uses a legacy string matcher with structured parsed terms and does not reproduce the report rules; nonempty keyword configurations can fail. Use `auto_extract` for topic queries / 当前 `keywords` 使用旧字符串匹配逻辑，不能正确处理解析后的结构化词项或复现报告规则，非空词表可能失败；话题查询可用 `auto_extract`。 |

本指南依据源码核对；未代表真实客户端握手已验收。关键词语法的完整支持范围是[配置指南](configuration.md)中的采集器报告流程。

This guide is checked against source, not a claim of a verified live client handshake. The
complete keyword syntax documented in the [configuration guide](configuration.md) applies to
the collector's report pipeline.

## Source Reference / 实现依据

[CLI and registered tools / CLI 与工具注册](../mcp_server/server.py),
[configuration/data paths / 配置与数据路径](../mcp_server/services/parser_service.py),
[query behavior / 查询行为](../mcp_server/services/data_service.py),
[crawl tool / 采集工具](../mcp_server/tools/system.py),
[storage synchronization / 存储同步](../mcp_server/tools/storage_sync.py).
