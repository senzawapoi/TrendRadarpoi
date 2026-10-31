# Configuration / 配置与关键词

[中文首页](../README.md) | [English README](../README-EN.md) | [MCP setup / 客户端配置](mcp-setup.md)

本页中英对照，说明主采集器的关键词匹配与 HTML 报告配置。模型、Lark 和部署设置见首页及[部署手册](deployment.md)。

This bilingual reference covers the main collector's keyword matching and HTML reports.
See the READMEs and [deployment guide](deployment.md) for models, Lark and deployment settings.

## Files / 文件与路径

| Purpose / 用途 | Path and overrides / 路径与覆盖 |
| --- | --- |
| YAML | `config/config.yaml`; `CONFIG_PATH` selects another file / 可选择其他配置文件。 |
| Keywords / 关键词 | UTF-8 `config/frequency_words.txt`; `FREQUENCY_WORDS_PATH` selects another file / 可选择其他词表。 |
| Report settings / 报告设置 | The environment variables below override YAML / 下表中的环境变量优先于 YAML。 |

默认相对路径基于**进程工作目录**。从仓库根目录运行；在其他目录启动时，分别为两个配置文件设置绝对路径。`CONFIG_PATH` 不会移动词表或改变工作目录。空词表有效，报告显示全部新闻（仍应用全局过滤）；文件缺失则加载失败。MCP 的路径规则另见[客户端配置](mcp-setup.md)。

Default relative paths resolve from the **process working directory**. Run from the checkout
root, or set both file paths explicitly to absolute paths. `CONFIG_PATH` neither relocates the
keyword file nor changes the working directory. An empty keyword file is valid and selects all
news, subject to global exclusions; a missing file fails loading. MCP has separate path rules
documented in the [setup guide](mcp-setup.md).

## Keyword Rules / 关键词规则

将下例内容用于词表。每组以真正的空行分隔，区域标记必须位于新块首行。没有 `#` 注释语法，注释行会被当作关键词。

The following is a keyword-file example. Separate groups with empty lines; section markers
must start a new block. There is no `#` comment syntax: such lines become literal keywords.

```text
[GLOBAL_FILTER]
advertisement
sponsored

[WORD_GROUPS]
/\bAI\b/ => AI releases
large language model
+release
!/rumou?r/
@5

semiconductor => Chips
GPU
@10
```

| Syntax | 中文 | English |
| --- | --- | --- |
| `AI` | 标题中的普通子串，不区分大小写；同组普通词为“或”。 | Case-insensitive title substring; ordinary terms in a group are ORed. |
| `+release` | 每个必须词都需匹配；若还有普通词，还须匹配其中至少一个。允许只有必须词的组。 | All required terms must match, plus at least one ordinary term if present. Required-only groups are valid. |
| `!rumor` | 匹配则排除。当前实现将所有组的 `!` 合并，实际跨组生效。 | Excludes matches. The current implementation pools `!` rules across all groups. |
| `/\bAI\b/` | Python 正则搜索，默认忽略大小写；也可用于 `+`、`!`。 | Python regex search, always case-insensitive; also supported after `+` and `!`. |
| `GPU => Chips` | `Chips` 仅为显示名，不是额外匹配词；正则也支持别名。 | `Chips` is a display alias, not another search term; regex aliases also work. |
| `@5` | 该组最多显示 5 条；语法是 `@数字`，不是字面量 `@count`。 | Display at most five titles in this group; use `@number`, not literal `@count`. |
| `[GLOBAL_FILTER]` | 全局排除区，一行一个普通子串；不解析正则或别名；以 `!`、`+`、`@` 开头的行忽略。 | Global plain-substring exclusions, one per line; no regex or alias parsing. Lines starting with `!`, `+` or `@` are ignored. |
| `[WORD_GROUPS]` | 恢复词组区域，也是文件初始默认区域。 | Resume keyword groups; this is also the default initial section. |

示例第一组要求标题包含 `release`，且包含独立词 `AI` 或子串 `large language model`。
`rumor` / `rumour` 在两个组中都会被排除。标题归入首个匹配组，因此将较具体的组放在前面。
显示名优先取普通词中的第一个别名，其次才是必须词中的别名。

The first example group requires `release` and either the whole word `AI` or the substring
`large language model`. The `rumor` / `rumour` exclusion affects both groups. A title belongs
to its first matching group, so put specific groups first. The group label uses the first alias
among ordinary terms, falling back to the first alias among required terms.

正则后缀如 `/pattern/i` 可以被识别，但标志被忽略，统一使用忽略大小写；`/s` 不会启用跨行匹配。
无效正则退回普通文本匹配。无效或非正数的 `@` 不生效。没有任何普通词或必须词时，报告会清空 `!` 过滤；全部新闻模式下请用 `[GLOBAL_FILTER]` 排除内容。

Regex suffixes such as `/pattern/i` are accepted but ignored: matching always uses ignore-case,
and `/s` does not enable dot-all. Invalid regex falls back to literal matching. Invalid or
nonpositive `@` values have no effect. Without any ordinary or required terms, reports discard
`!` exclusions; use `[GLOBAL_FILTER]` for exclusions in all-news mode.

## Reports / 报告配置

以下为关键词展示示例，可合并到现有 YAML 的 `report` 节；不是整份配置文件。

This keyword-display example belongs in the existing YAML `report` section; it is not a complete configuration.

```yaml
report:
  mode: incremental
  display_mode: keyword
  rank_threshold: 5
  sort_by_position_first: false
  max_news_per_keyword: 0
  reverse_content_order: false
```

| YAML key / 配置项 | Environment / 环境变量 | Behavior / 行为 |
| --- | --- | --- |
| `report.mode` | `REPORT_MODE` | `incremental`, `current`, `daily`; see below / 见下表。 |
| `report.display_mode` | `DISPLAY_MODE` | `keyword` or `platform` HTML display style; does not change keyword matching / 关键词或平台展示样式，不改变匹配条件。 |
| `report.rank_threshold` | YAML only / 仅 YAML | Top-rank threshold used in highlighting and hotness weighting / 高排名强调与热度权重阈值。 |
| `report.sort_by_position_first` | `SORT_BY_POSITION_FIRST` | `true`: group order in the file first; `false`: matched count descending, then file order / 按文件组顺序优先，或按匹配数量降序、文件顺序次之。 |
| `report.max_news_per_keyword` | `MAX_NEWS_PER_KEYWORD` | Global per-group display cap; `0` is unlimited; positive `@N` overrides it / 每组默认显示上限，`0` 不限，正数 `@N` 优先。 |
| `report.reverse_content_order` | `REVERSE_CONTENT_ORDER` | `true` puts new-item sections before statistics sections / 将新增内容区块放在统计区块前。 |

| Mode / 模式 | 中文 | English |
| --- | --- | --- |
| `incremental` | 当天首次采集处理全部输入，之后只处理新增标题。 | Process all supplied titles on the first crawl of the day, then only newly detected titles. |
| `current` | 有历史时间记录时，仅保留最新批次中的输入标题，并使用历史统计。 | Select supplied titles from the latest batch when history timestamps are available, retaining historical statistics. |
| `daily` | 分析器处理全部传入结果；当前主入口传入本轮采集结果，不自动重建全天标题集合。 | Analyze all supplied results. The current main CLI supplies the current crawl; it does not reconstruct a full-day title set. |

组内热榜标题按权重、最佳排名、出现次数排序；显示上限不会降低原始匹配计数。
当前主入口在当天非首次的 `incremental` 报告中，会将热榜重组为平台分组、RSS 仅保留新增并按订阅源分组。

Within hot-list groups, titles sort by weight, best rank and occurrence count. Display caps do
not reduce the original match count. For later `incremental` runs that day, the main entrypoint
explicitly regroups hot-list results by platform and includes only new RSS entries, grouped by feed.

**`report.mode` 不控制 Lark 投递。** `LARK_DELIVERY_MODE=instant` 是独立的 Story 投递策略，由 Scheduler
检查新 Story；采集器只采集与生成报告。将报告改成 `daily` 不会启用 Lark 日报。详见 [Lark 指南](intelligence.md#lark-assistant)。

**`report.mode` does not control Lark delivery.** `LARK_DELIVERY_MODE=instant` separately selects
new-Story delivery by the Scheduler. Collectors collect data and generate reports; selecting
`daily` reports does not enable Lark daily delivery. See the [Lark guide](intelligence.md#lark-assistant).

### Instant push filter / 即时推送过滤

`lark.delivery.filter.enabled: true`（或 `LARK_DELIVERY_FILTER_ENABLED=true`）启用。规则如下：

- Story 满足以下任一条件就推送：
  - `domain` 在 `domains` 中（默认 `ai`、`security`）；
  - 任一成员来源在 `sources` 中；
  - 标题、摘要或成员原始标题命中 `keywords`。英文关键词按字母和数字边界匹配，所以 `AI芯片` 能命中 `AI`，`SAID` 不会。
- 成员来源全部列在 `exclude_sources` 中的 Story 不推送。
- 不推送的 Story 仍按目标登记，但不分配批次（`delivery_key` 为 NULL）：
  - 不会重发，不计入积压或等待告警；
  - 仍留在数据库、报告和 Assistant 检索里；
  - 健康检查用 `instant_delivery.held_back_stories_24h` 报告最近 24 小时的数量。
- 不需要迁移数据库表结构，回滚到旧版本也能读这些登记记录。
- 列表不配置时使用 `trendradar/integrations/feishu/story_filter.py` 里的宽松默认值；配置了就整体替换默认值。

`lark.delivery_max_batches_per_tick`（默认 1，最大 10）设置每次 Scheduler 运行最多连续发送几批。只有上一批发送完成才会继续，遇到失败、维护或租约丢失立即停止。

Enable with `lark.delivery.filter.enabled: true` (or `LARK_DELIVERY_FILTER_ENABLED=true`):

- A Story is pushed when any of these holds:
  - its domain is in `domains`;
  - a member source is in `sources`;
  - its title, summary or a member's original title matches `keywords`.
- A Story whose member sources are all in `exclude_sources` is not pushed.
- Held-back Stories are registered for the target with no batch:
  - they are never resent and are not counted as backlog;
  - they remain in the database, reports and Assistant search;
  - health reports `held_back_stories_24h`.
- No schema migration is involved, and older releases can still read these records.

`lark.delivery_max_batches_per_tick` sets how many batches one scheduler run may send. A run continues only after a completed send.

### NVD significance filter / NVD 重要性过滤

在 `intelligence.security.sources.nvd` 下配置：

- `date_field: published` 只查询 lookback 窗口内新发布的 CVE。默认值 `modified` 会把最近改过的旧 CVE 也查出来。
- `significance.enabled: true` 在采集时只保留以下 CVE，`max_items` 在过滤之后计数：
  - `known_exploited` 为真（可用 `keep_known_exploited` 关闭）；
  - 命中某条 `rules`：CVSS 不低于该规则的 `min_cvss`，且描述命中该规则的 `keywords`。
- 默认规则：
  - `ai_stack`：CVSS ≥ 8.0；
  - `major_platform`：CVSS ≥ 9.0；
  - 没有评分的记录跳过，除非规则设置了 `include_unscored`。
- 关键词是产品名，比如 `Microsoft Windows`、`GitHub Copilot`，不用描述里顺带出现的 `Windows`、`Copilot` 这类单词。
- `max_per_keyword`（默认 0，表示不限）控制每轮采集里同一个命中关键词最多保留几个 CVE，按 CVSS 从高到低取。厂商一次批量发布很多 CVE 时，这个上限能把数量压下来。
- CISA KEV 由独立的采集器采集，不受这个过滤影响。
- 某一轮没有保留任何 CVE 时，该来源记为 `degraded`、错误数 0，健康检查和部署就绪检查都接受这种状态。

Under `intelligence.security.sources.nvd`:

- `date_field: published` queries only CVEs first published in the lookback window.
- `significance.enabled: true` keeps only known-exploited records or records matching a rule (CVSS ≥ `min_cvss` and a keyword). `max_items` counts after filtering.
- Defaults are `ai_stack` (CVSS ≥ 8.0) and `major_platform` (CVSS ≥ 9.0).
- An empty filtered run is reported as `degraded` with no errors, which readiness accepts.

## Source Reference / 实现依据

[Keyword parser and matcher / 关键词解析与匹配](../trendradar/core/frequency.py),
[report analysis / 报告分析](../trendradar/core/analyzer.py),
[report settings / 报告设置](../trendradar/core/loader.py),
[settings precedence / 配置优先级](../trendradar/core/settings.py),
[main entrypoint / 主入口](../trendradar/__main__.py),
[HTML rendering / HTML 渲染](../trendradar/report/html.py).
