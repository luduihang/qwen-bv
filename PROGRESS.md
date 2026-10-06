# Progress — bili-upstream

> Rolling session summaries. Newest first. Loaded at session start so the next session knows where work left off.
> Each entry is 2-3 sentences. Older entries get pruned/consolidated when this file exceeds ~100 entries or ~8k chars.


<!-- session-in-progress:start=2026-10-05T15:37:01.606Z -->
## 2026-10-06 13:07 — I've outlined the implementation for T-020, which adds synchronous logging acros... _(in progress)_
I've outlined the implementation for T-020, which adds synchronous logging across app.py, the collect operation in app.py, the pagination logic in bili.py, and the retry mechanism in bili.py. Now I'll start implementing these changes.
<!-- end-session-in-progress -->
## Entries

<!-- newest first -->

## 2026-10-06 13:12 — Phase 6 完成 ✅（T-019~T-021，main 串行，3 commit）

**内容**：T-019 错码与风控定稿 — fetch_page HTTP 412 → risk_control、HTTP 429 → rate_limited（均一次请求立即失败不重试）；风控码表定稿（-352/-412/-509，Phase 7 实测补充）；ERROR_STATUS 10 错码全映射确认；wbi nav 保持 wbi_failed（WBI 契约冻结不变）（`966bb02`）；T-020 同步日志 — [collect] start(mid+cookie=set/empty) / page(pn+items+total) / retry(pn+attempt+reason) / error(code+mid+duration+msg) / ok(pages+unique+duration+files)，mock 完整同步实测行齐全且无 Cookie 泄漏（`ae3b939`）；T-021 异常场景测试 — 错码全矩阵 10 code → 契约 HTTP 状态 + JSON 形状（失败不落盘）、HTTP 412/429/业务风控码不重试（1 次调用）、风控不返回 200 空数组、[collect] start/ok/error 日志行 + 无 Cookie（+19 例）（`e250c6a`）。
**验收门**：`pytest tests/ -q` 195 全绿（基线 176 + 新增 19，全 mock）；T-020 手动 mock 同步验证（start/retry/page/ok + error 两路径）通过。
**下一步**：Phase 7 串行 main — T-022 21 场景全量核对 → T-023 README → T-024 真实端到端验收（Cookie 已可用，-352 风险已解除；qwen-tts /transcribe 链路不在本项目任务内，验收前需用户确认）。

## 2026-10-06 12:05 — Phase 5 完成 ✅（T-016~T-018，main 串行，3 commit + 冒烟）

**内容**：T-016 POST /collect（`{"mid":int}` 或 `{"up":int|数字串|空间URL}`，两者都给/都缺/解析失败 → 400 invalid_up；成功 200 契约 payload 含三相对路径 + bvids；BiliError → ERROR_STATUS 契约映射 400/404/429/502/504，generic → 500 internal；错误统一 `{"error":{"code","message"}}`）（`f37fb6c`）；T-017 GET /up/<mid>/bvids 与 /videos?offset&limit（从未同步 → 404 not_found；limit 默认 100 clamp [1,500]、offset 默认 0 clamp ≥0、非整数按默认值；路径 mid 复用 parse_up → 非数字 400）（`f4acf04`）；T-018 test_api 补齐（错误 JSON 精确形状/非 JSON body 400/mid 数字串/无 tmp 残留/jsonl 中文往返）（`630bb71`）。纯路由层，未动 bili/wbi/storage 逻辑；同步日志留给 T-020。
**验收门**：`pytest tests/ -q` 176 全绿（基线 136 + 新增 40，全 mock）；真实 snapshot 冒烟（老番茄 678 条，不走网络）：bvids count=678、offset=677 取尾部 1 条、limit=99999→500、未同步 mid 404、/collect 都缺 400，全部正确。用户范围强调已入项目记忆：音频转文字（qwen-tts /transcribe）不属于本项目任务。
**下一步**：Phase 6 串行 main — T-019 错码/风控码表定稿 + T-020 同步日志（start/page/retry/error/ok）+ T-021 异常场景测试 → Phase 7（README + 真实验收）。

## 2026-10-06 01:55 — T-015 原子 snapshot 管线完成 ✅（Phase 4 收口，136 全绿，真实 UP 主 e2e 通过）

**内容**：T-015 app.py `run_collect(up_input, cfg)` — parse_up → sync_up → storage.atomic_save → payload（三相对路径 + bvids，manifest synced_at ISO8601 UTC）；中途失败 → 旧 snapshot 原样、无 tmp 残留、异常上抛（`a7fa239`）。main() 启动补 `wbi.configure(cfg)`（工作包 C 发现②）。另真实响应兼容 fix（`9525238`）：带 Cookie 实测发现新 wbi 接口 `data.list` 是 dict（列表在其 `vlist`）、条目为扁平字段（author/mid/length/description，无 owner 子对象）→ fetch_page/_normalize 兼容新旧两形状 + 2 真实形状测试。
**验收门**：`pytest tests/test_pipeline.py -q` 6 绿；全量 `pytest tests/ -q` 136 绿（全 mock）。真实 e2e（用户 Cookie 已写入 config.yaml，值不入仓库）：老番茄 mid=546195 全量同步 678 视频 / 23 页 / 33.7s，drift=0；bvids.txt 678 行 == manifest.total_unique、无重复、created 降序、0 tmp 残留 —— Phase 4 验收（真实 UP 主产物落盘 + 失败演练）达成。
**下一步**：Phase 5 串行 main — T-016 POST /collect + T-017 GET 缓存 API（T-018 test_api.py）；随后 Phase 6（错码/限速/日志）→ Phase 7（README + 真实验收：/collect 两种输入形态 + qwen-tts /transcribe 链路）。


## 2026-10-06 01:30 — 工作包 C 完成并合并 ✅（T-010~T-014，bili 链，worktree worker-c-bili）

**内容**：T-010 bili.py fetch_page（WBI 签名 GET arc/search + VideoRecord 规范化 + 临时故障 1s/2s/4s 退避重试 + 错码映射，`5044d44`）；T-011 单页测试 18 例（`cefa8b7`）；T-012 fetch_all 完整分页（count→total_pages、三重终止条件、页间 sleep、_page_guard 硬上限、bvid 去重保先出现、created 降序稳定）+ sync_up 骨架（`134029d`）；T-013 分页/去重/重试测试 9 例（`1752eba`）；T-014 sync_up 完整性校验（drift<0 成功 / 0≤drift≤max(3,1%) 成功+warn / 超过 → incomplete）+ test_sync 9 例（含 500→430 验收场景）（`a74895f`）。
**验收门**：`pytest tests/ -q` 128 全绿（92 基线 + 36 新增，全 mock）；21 场景表 bili 部分（4~15）全覆盖；merge `7c1faa9` 已 push；顺手删除远端 origin/w-b 残留。
**实现发现**：① 新 wbi 接口列表在 `data.list`（旧接口 `data.vlist`）→ 实现为两者兼容读取，错码语义不变（契约的 "vlist" 按领域词理解）；② fetch_page 内加防御式 `wbi.configure(cfg)`（wbi._cfg 未绑定为 None 会 AttributeError，T-015 起 app 启动也应 configure）；③ 硬上限为纯防御（终止条件 ①②③ 先触发），以 _page_guard 单元测试覆盖。
**现场备忘**：会话计划/思考全文在 `.agent/session-C-plan.md`（gitignore，防截断）。
**下一步**：main 串行 T-015 原子 snapshot 管线（app.py run_collect + tests/test_pipeline.py）→ Phase 5 → Phase 6 → Phase 7（真实 e2e 需真实 Cookie：本网络匿名 arc/search -352 风控）。

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
