# Progress — bili-upstream

> Rolling session summaries. Newest first. Loaded at session start so the next session knows where work left off.
> Each entry is 2-3 sentences. Older entries get pruned/consolidated when this file exceeds ~100 entries or ~8k chars.

## Entries

<!-- newest first -->

## 2026-10-05 23:31 — 三步收尾完成 ✅

1. **PROGRESS.md** — 正式模板（覆盖截断残留）+ 两条会话记录：scaffold 完成（23:27）、建仓收官（23:30）。已验证。
2. **DECISIONS.md** — ADR-lite 模板 + 首条决策已冻结：**2026-10-05-1 全量同步完整性校验**（drift < 0 成功；`≤ max(3, 1%)` 成功 + warn；超过 → `incomplete` 502 不落盘，旧 snapshot 保留）。已验证。
3. **git + GitHub** — `git init -b main`，5 份文档入库（500 行），无任何代码；仓库 **https://github.com/luduihang/qwen-bv**（public，沿用 qwen-tts 的目录名惯例）；2 commits 已 push（`b0d9412` → `be52372`），工作树干净，main 跟踪 origin/main。

## 2026-10-05 23:30 — GitHub 建仓收官：luduihang/qwen-bv（public）已 push
**现场**：main 已 push（scaffold commit `b0d9412` + 本条 docs commit），工作树干净，5 份文档入库、尚无任何代码。
**下一步**：Phase 1（T-001~T-005）main 串行 → 完成后按 PLAN 工作包章节开 worktree A（wbi）∥ B（storage），A 合并后分叉 C（bili 链）。

## 2026-10-05 23:27 — Scaffold 完成：五份项目文档落盘，Phase 1 未开始
**规划（本 session）**：分诊 = 真实产品（7 Phase、持久化数据、长期维护的 HTTP 服务）。参考项目 qwen-tts 通读完成（接口风格 / 错误 JSON / 配置加载 / 日志 / 文档结构全部沿用：Flask 2.2.5 + requests + PyYAML 钉版本、BiliError + ERROR_STATUS、config.yaml gitignore、单测全 mock）。五份文档按 scaffold 流程逐文件审批 + 落盘回读验证：VISION（项目名固定 bili-upstream）、PLAN（7 Phase + A/B/C 三工作包 worktree 并行）、TASKS（契约总览冻结 + 21 测试场景落位 + T-001~T-024）、PROGRESS（本文件）、DECISIONS（漂移容忍度决策已冻结）。
**关键取舍**：不部署 Vercel（stateful 本地服务，data/ 磁盘 snapshot + 下游 127.0.0.1:5000）；不上 Playwright（纯后端 API，pytest 全 mock 即质量门）；C 工作包（bili 链）必须等 A（wbi）合并后分叉——fetch_page 要 import 真实 wbi.sign，不对着 mock 开发；关键路径 P1→A→C→T-015→P5→P6→P7，B 不在关键路径。
**现场**：VISION/PLAN/TASKS/PROGRESS/DECISIONS 全部在盘，尚无任何代码，git 仓库创建中。下一步：GitHub 建仓 push → Phase 1（T-001~T-005，main 串行）。
