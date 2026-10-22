# Phase 7 发布候选整理记录 — 2026-10-22

用户已指定将项目提交到 senzawapoi/TrendRadarpoi，并提供目标 VPS 的本地 SSH 入口。
本次在独立 worktree 整理 release/phase7-rc-20261022，以远端默认分支 master 的
3572aeb8275c5cb9f1fbd6dacb75d9d4ac70ea77 为基点。
原本地 main、未提交修改、运行库及审计夹具保持原状。

## 候选范围

- 纳入已验证的项目源码、依赖锁、部署工具、回归测试和阶段文档。
- 未纳入 PhaseGate Demo、Demo 压缩包、.phasegate 输出、运行数据库或凭据。
- 候选配置清空实际 Bark 推送地址；从环境或 GitHub Secrets 注入。
  该地址已存在于远端旧版本，清空当前文件不代表清理了历史。
- CI 的 push 范围包含 master 和 main；部署输入的默认 ref 改为 master。
- 只更新对应的既有分支断言，生产部署/健康/恢复逻辑保持 v6 实现。

## 验证依据与边界

v6 的 301 个源文件在复制前全部匹配冻结清单。历史 Windows 全量为
683 passed / 342 skipped；Linux 全量为 1019 passed / 6 skipped。
这些结果对应 v6 输入，候选的精确差异列于同目录的
phase7-release-candidate-delta-20261022.json，不能将历史结果改称本次 CI。

真实 GitHub CI、干净候选产物安装和目标部署结果需另行记录。
工作流上传和 PR 不等于合并默认分支，也不等于生产部署。
现有 27 PASS / 1 BLOCKED 矩阵中的 RG-04 应在本候选实际安装证据取得后更新。

## 目标主机只读预检

- Ubuntu 24.04，x86_64，1 CPU，约 1.87 GiB RAM，512 MiB swap。
- 预检时 MemAvailable 约 1.23 GiB，根盘空闲约 10.91 GiB；这不是负载验收。
- Python 3.12.3 / SQLite 3.45.1，systemd 255，cgroup v2。
- Lark、Gemini、PyPI、GitHub 的 DNS/TLS 可用；未执行认证 API 或 Lark WSS 会话。
- 既有网站及其他服务正在运行。TrendRadar 标准目录、固定安装入口和 restic 尚不存在。
- 目标 Python/SQLite 与 v6 Linux 验证环境不同；需核查发行版补丁并验证所选运行时安装。
- 没有安装软件、创建生产账号、变更服务、防火墙或部署业务。

后续：候选 CI → 干净产物 → 部署账号/固定入口/环境配置 → 受控上线测试。
C3/C4、远端取回恢复、至少 48 小时和两个日报窗口仍属现场验收。
