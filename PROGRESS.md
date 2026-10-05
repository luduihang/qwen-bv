# Progress — bili-upstream

> Rolling session summaries. Newest first. Loaded at session start so the next session knows where work left off.
> Each entry is 2-3 sentences. Older entries get pruned/consolidated when this file exceeds ~100 entries or ~8k chars.



## Entries

<!-- newest first -->

## 2026-10-06 00:25 — Phase 2 工作包 B 收口 ✅（T-008/T-009 → Done，main 合并 + push）

**内容**：T-008 storage.py 原子存储 — 三文件（bvids.txt/videos.jsonl/manifest.json）先写 *.tmp 全部成功再逐个 os.replace 提交；任一失败 → 清理全部 tmp、重抛异常、正式文件不被触碰（旧 snapshot 原样保留）；load_bvids / load_videos(offset, limit)（total 为切片前全量）/ load_manifest 目录/文件缺失 → None；bvids/videos 长度不一致 → 落盘前 ValueError（`7848675`）。T-009 16 例：三文件写正确（一行一个 BV / jsonl 同序往返含中文 / manifest 7 字段）、原子性（3 处 tmp→目录破坏：正式文件原样 + 无本次残留 + 异常上抛；新 mid 失败不留任何文件）、offset+limit 读取（越界 → []）、缺失 → None、空 snapshot（`43237ab`）。另建 AGENTS.md：GitHub 须走本地 7897 代理（2026-10-06 实测）+ 测试全 mock 无需网络 + 并行 Owns 协作约定（`e1e5a27`）。
**验收门**：`pytest tests/test_storage.py -q` 16 绿；全量 `pytest tests/ -q` 92 绿（52 + A 24 + B 16，全 mock）。
**现场/下一步**：本地 main 与 w-b 在 `ad4e6fd` 分叉（main 多了 A 的收口 `09723f0`）→ `--no-ff` 合并入 main（`1a3ae4b`）并 push（经 7897 代理）。下一步：从新 main 分叉工作包 C（bili 链 T-010→T-014，A 已就位可立即开始）；C 合并后 T-015 及 Phase 5/6/7 回 main 串行收口。

## 2026-10-06 00:14 — 工作包 A 完成、合并 + push ✅（T-006/T-007 → Done）

**内容**：T-006 wbi.py — nav 取 key + TTL 10 分钟缓存 + w_rid 签名，configure() 绑定 Cookie/超时，失败 → wbi_failed；实测匿名 nav code=-101 但 wbi_img 仍在 → 只按"wbi_img 是否存在"把关、不查业务 code（`8e46322`）。T-007 24 例 — key 提取/签名形状/确定性 w_rid/特殊字符过滤/缓存命中/TTL 过期/失败不污染缓存/nav 失败 7 场景/请求头，全 mock HTTP（`c127a7a`）。
**验收门**：`pytest tests/test_wbi.py -q` 全绿；全量 76 绿。真实试拉：nav 匿名可取 key；arc/search 匿名/带 buvid3 均 -352 风控（本网络环境）→ Phase 7 验收需真实 Cookie（详见 PLAN Notes）。

## 2026-10-05 23:49 — Phase 1 完成 ✅（T-001~T-005，main 串行，5 commit）

**内容**：T-001 依赖钉版本（Flask 2.2.5 / requests 2.33.1 / PyYAML 6.0.3，对齐 qwen-tts）+ .gitignore（config.yaml、data/、.agent/）+ 根 conftest（`6d0e22a`）；T-002 config.py（REQUIRED_KEYS=server.host/port、storage.data_dir，DEFAULTS 补全 bilibili/timeout，缺文件/解析失败/缺必填 → ConfigError 清晰消息）+ config.example.yaml 本身可直接加载（`761a44d`）；T-003 app.py（create_app 工厂 + main，host/port 取配置，启动自动建 data_dir），实测：缺 config.yaml 启动明确报错退出 1、`python app.py` 后 curl :5001/health = 200（`d9ddffd`）；T-004 bili.py::parse_up（int/纯数字串/space URL → mid；bool/昵称/空/非数字/其他域名/mid≤0 → invalid_up）+ 35 单测（`0c59452`）；T-005 test_config（8 场景）+ test_app（health/data_dir）（`aab5398`）。
**验收门**：`pytest tests/ -q` 52 全绿（全 mock 无网络）；PLAN 验收第 1 条（/health 200）已实测勾选；每任务一 commit（`T-00N: 摘要`）。
**下一步**：按 PLAN 工作包章节开 git worktree A（wbi，T-006/T-007）∥ B（storage，T-008/T-009）；A 合并后分叉 C（bili 链，T-010~T-014）。

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
