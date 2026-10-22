---
phase: 00-project-baseline-stabilization
status: complete
date: 2026-08-21
---

# Phase 0 Research: Baseline and Settings

## Research Question

如何在不改变当前抓取、通知和 SQLite 行为的前提下，建立可执行的架构基线与统一配置边界？

## Current State

- `trendradar/core/loader.py` 已把主 YAML 转成旧式大写字典，并实现多数环境变量覆盖。
- `trendradar/__main__.py`、AI Frontier 和四个 MCP 模块仍各自直接调用 `yaml.safe_load`。
- AI Frontier 数据库路径硬编码为 `output/ai_frontier.db`；主存储仍按
  `output/news/YYYY-MM-DD.db` 与 `output/rss/YYYY-MM-DD.db` 分区。
- 当前自动化测试集中在 `tests/ai_frontier/`，已知基线为 91 passed；主入口、核心存储和
  MCP 缺少特征测试。
- `config/` 是运行数据目录而非已打包 Python 包。把 canonical 实现只放在
  `config/settings.py` 会使 wheel/非仓库根运行不可靠。

## Recommended Architecture

### Settings boundary

在 `trendradar/core/settings.py` 建立无第三方依赖的冻结 dataclass：

1. 解析配置路径，优先级为 explicit > `CONFIG_PATH` > `config/config.yaml`。
2. 读取并校验 YAML 根节点为 mapping，保留 `raw_config` 供旧 loader 返回原有字典。
3. 提供统一的 env string/int/bool/list 解析及嵌套 YAML 查找。
4. 为时区、Gemini、飞书和数据库路径暴露具名属性；secret 属性只读环境变量。
5. `config/settings.py` 仅 re-export 核心 API，满足文档路径同时保持打包方向正确。

现有 `load_config()` 继续返回原字典，内部改用 settings 读取 YAML 和 env。其他直接 YAML
读取点调用共享 loader，不改变调用者的返回类型或异常语义。

### Compatibility baseline

- 入口测试只 import/检查 callable，不执行网络抓取或启动长连接。
- 主 SQLite 测试用 `tmp_path` 创建 news/rss schema，检查关键表与唯一约束仍存在。
- AI Frontier 测试复用真实临时 SQLite，验证 `(source, url)` 幂等 upsert。
- 配置测试固定默认值、环境覆盖、显式路径覆盖、无效 YAML 和 secret 不回退 YAML。

## Risks and Controls

| Risk | Control |
|------|---------|
| 大范围配置迁移改变默认值 | 在修改前提交特征测试；保留旧返回字典和默认常量 |
| secret 被示例或日志泄露 | `.env.example` 使用空值；设置对象 repr 隐藏 secret；测试禁止值出现在 repr |
| `config/settings.py` 无法随 wheel 安装 | canonical 实现位于 `trendradar/core/`，根配置模块只转发 |
| MCP 降级行为改变 | 保留读取失败时空字典/空平台列表及原异常包装 |
| 用户未提交 AI Frontier 修改被覆盖 | 本阶段不改两个 source 文件，测试按当前工作树运行 |

## Validation Architecture

### Test layers

- **Fast characterization:** `python -m pytest tests/baseline tests/test_settings.py -q`
- **Existing regression:** `python -m pytest tests -q`
- **Changed-scope lint:** 对本阶段新增和修改的 Python 文件运行 Ruff。
- **Source assertions:** `rg` 确认现存运行模块不再直接调用 `yaml.safe_load`，但 settings
  模块本身可以调用。

### Requirement mapping

- BASE-01: 文档结构断言和人工读取 `docs/code-review.md`。
- BASE-02: 入口及 SQLite 特征测试、`docs/baseline.md` 命令记录。
- CONF-01: settings 优先级和所有直接 YAML 读取点迁移测试。
- CONF-02: `.env.example` 空占位与 secret repr/来源测试。
- CONF-03: timezone、Gemini、飞书和 DB path 属性测试。

## Sources

- 三份仓库内 v5 Codex 文档（Phase 0 权威要求）。
- `.planning/codebase/ARCHITECTURE.md`、`CONCERNS.md`、`TESTING.md`。
- 当前 `trendradar/core/loader.py`、AI Frontier 入口、MCP YAML 读取点和 SQLite 实现。

## Confidence

高。Phase 0 不依赖外部 API 设计；所有关键结论均来自当前仓库代码和锁定文档。

## RESEARCH COMPLETE
