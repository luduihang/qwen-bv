# AGENTS.md — bili-upstream

> 项目级运维与协作备注，供本仓库的 agent 读取。
> 项目状态看 VISION / PLAN / TASKS / PROGRESS / DECISIONS；全局约定看全局 AGENTS.md。

## 环境 / 运维

- **访问 GitHub 需要本地代理（端口 7897）**：本环境直连 github.com 会失败
  （`GnuTLS recv error (-110)` / TLS 中断）。git 远端操作请走本地 7897 混合代理
  （http/socks5 均可）：

  ```bash
  https_proxy=http://127.0.0.1:7897 http_proxy=http://127.0.0.1:7897 git fetch origin
  https_proxy=http://127.0.0.1:7897 http_proxy=http://127.0.0.1:7897 git push origin <branch>
  ```

  2026-10-06 实测：该代理下 `git ls-remote` / `push` 正常。不想每次带环境变量时，
  可临时 `git config http.proxy http://127.0.0.1:7897`（仓库级；代理没起时记得
  `git config --unset http.proxy` 还原，避免误伤其他场景）。
- 测试全部 mock（`pytest tests/ -q`），**不需要**任何网络/代理。

## 协作

- 并行工作包遵守 TASKS.md 的 `Owns:` 声明（零共享文件）；共享文档
  （TASKS/PLAN/PROGRESS 勾选与收口）由串行整合者在合并时统一提交。
- 每任务一个 commit，格式 `T-00N: <摘要>`（非任务性文档改动用 `docs:` 前缀）。
