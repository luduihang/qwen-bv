# Plan — v1：UP 主 → 全量视频/BV 清单 API

> Active work plan. One feature/phase at a time. Replace contents when starting a new feature, or fork to `docs/plans/<name>.md` to archive.

## Goal
一条 curl（mid 或空间 URL 进）拿到该 UP 主全量、去重、按时间倒序的 BV 清单
（`bvids.txt` + `videos.jsonl` + `manifest.json`），GET 端点读取已持久化数据。
v1 验收 = 真实 UP 主全量同步成功 + 从 bvids.txt 任取一个 BV 提交 qwen-tts `/transcribe` 成功。

## Approach
单 Flask 服务 + 四个薄模块（config.py / bili.py / wbi.py / storage.py）+ config.yaml，
同步流水线，无 DB、无队列、无抽象层。接口风格、错误 JSON、配置加载、日志全部沿用兄弟项目
qwen-tts（Flask 2.2.5 + requests + PyYAML，版本钉死）。
B 站侧：`x/space/wbi/arc/search` + 动态 WBI 签名（key 现取现缓存，w_rid 不硬编码）；
顺序分页 + 页间 1s 间隔 + 临时故障 1s/2s/4s 退避有限重试（目标稳定，不追求最快）；
v1 每次全量同步（结构为未来增量留口）；原子 snapshot（先 *.tmp 后 rename，中途失败不覆盖旧数据）。

## Phases

1. **骨架与配置** — 项目结构、requirements/.gitignore/conftest、config.py + config.example.yaml、Flask 启动、`GET /health`、UP 输入解析（数字/空间 URL → `mid: int`；昵称拒绝）。产出：可运行的空服务 + 输入解析单测全绿。
2. **WBI 签名 + 单页请求** — 工作包 A：wbi.py（nav 动态 key + 缓存 + w_rid 签名）及其测试〔独立分支〕；工作包 B：storage.py（tmp+rename 原子写与读取）及其测试〔独立分支，与 A 零文件交集〕；工作包 C（bili 链：单页请求 → 完整分页 → 去重 → 完整性校验，T-010~T-014）在 A 合并后分叉，与 B 并行。产出：能取到真实 UP 主第一页（mock 测试 + 真实网络试拉一次）。
3. **完整分页 + 规范化 + 去重** — 分页循环（count→total_pages，三重终止条件，页间间隔，防死循环）、临时故障重试、bvid 去重、created 倒序、sync_up 整合 + 完整性校验（漂移规则见 DECISIONS）。产出：mock 多页全量拉取正确。
4. **storage + 原子 snapshot** — sync_up → storage 原子落盘管线（全部成功后才 rename）；中途失败旧 snapshot 原样保留、无 *.tmp 残留。产出：真实 UP 主产物落盘；模拟中途失败演练通过。
5. **/collect、cached API** — `POST /collect` 串起全链路（响应契约见 TASKS）；`GET /up/<mid>/bvids`（从未同步 404）；`GET /up/<mid>/videos?offset&limit`。产出：v1 核心目标达成。
6. **异常、限速、日志** — BiliError 错码集与 HTTP 映射定稿（见契约）、风控响应识别 → risk_control（不重试、不假装成功）、同步日志（start/page/retry/错误码/success/duration/路径，不打印完整 Cookie）。产出：每种错误场景返回清晰 JSON，不统一 500。
7. **测试、README、真实端到端** — 21 个测试场景全绿（全 mock 不碰真实网络）、README（快速开始 + 配置表 + curl 示例 + qwen-tts 集成示例 + 故障排查）、真实 UP 主 `POST /collect` + bvids.txt 抽查 + 任取 BV 提交 qwen-tts。产出：可交付的 v1。

## Work packages（并行）

v1 执行视图：Phase 1 串行地基；之后三个工作包 A/B/C 用 git worktree 并行（零文件交集，见 TASKS.md 的 Owns）；合并后 T-015 与 Phase 5/6/7 在 main 串行收口。

```
main:      Phase 1（T-001→T-005）──┬──────────────────────────────┬─ T-015 ─ Phase 5 ─ Phase 6 ─ Phase 7
                                    │（A 合并后分叉 C）              │（B∧C 合并后）
worktree A: ── A: T-006 wbi + T-007 测试 ── merge A
worktree B: ── B: T-008 storage + T-009 测试 ───────────────── merge B
worktree C: ───────── C: T-010→T-014 bili 链（单页/分页/去重/完整性校验）── merge C
```

依赖：
- A/B/C 都依赖 Phase 1（conftest、config、create_app 骨架、parse_up 均在 main）
- C 依赖 A（fetch_page 要 import 真实 wbi.sign，不对着 mock 开发）→ C 在 A 合并后分叉，与 B 的剩余部分并行
- T-015（app.py 管线）依赖 B∧C；Phase 5/6 全部动 app.py → main 串行；Phase 7 串行

规则：
- A/B/C 用 `git worktree` 各占一个分支，物理隔离；merge 顺序 A → B、C（B/C 先后不限，均须早于 T-015）→ main
- 并行窗口内零共享文件（由 `Owns:` 保证：A={wbi.py, tests/test_wbi.py}，B={storage.py, tests/test_storage.py}，C={bili.py, tests/test_bili.py, tests/test_sync.py}）
- 接口契约冻结在 TASKS.md"契约总览"，改动须先改契约
- 整合验收门：`pytest tests/ -q` 全绿 + 真实 e2e（见 Acceptance criteria）
- 每任务一个 commit，格式 `T-00N: <摘要>`

## Files that will change

| File | Change | Phase |
|---|---|---|
| `requirements.txt` | 新建 — flask、requests、pyyaml（版本与 qwen-tts 对齐） | 1 |
| `.gitignore` | 新建 — config.yaml、data/、__pycache__ 等 | 1 |
| `conftest.py` | 新建 — 让 tests 直接 import 根目录模块 | 1 |
| `config.py` | 新建 — 配置加载与校验 | 1 |
| `config.example.yaml` | 新建 — 配置样例（入库） | 1 |
| `app.py` | 新建 — Flask 入口，/health、/collect、GET 端点 | 1, 4, 5, 6 |
| `wbi.py` | 新建 — WBI key 获取/缓存/签名（工作包 A） | 2 |
| `bili.py` | 新建 — UP 输入解析、arc/search 分页、规范化、去重排序、sync_up | 1, 2, 3, 4, 6 |
| `storage.py` | 新建 — 原子 snapshot 写与读取（工作包 B，Phase 2 窗口提前建） | 2, 4 |
| `tests/` | 新建 — 全 mock 单测（test_up_parser / test_wbi / test_bili / test_storage / test_pipeline / test_api） | 1-7 |
| `README.md` | 新建 — 启动方式、curl 示例、配置说明、qwen-tts 集成 | 7 |

## Acceptance criteria

- [ ] `python app.py` 启动，`curl localhost:5001/health` 返回 200
- [ ] 真实 UP 主 `POST /collect`（mid 与空间 URL 两种输入均验证）→ 200；`bvids.txt` 行数 == manifest.total_unique == B 站 page.count（或在容忍度内，见 DECISIONS）
- [ ] bvids.txt 一行一个 BV、无重复、按 created 从新到旧；videos.jsonl 行数一致
- [ ] 模拟中途某页失败：旧 snapshot 原样保留、无 *.tmp 残留、API 返回对应错误 JSON
- [ ] 风控 / 超时 / UP 主不存在 / 参数错误 各返回对应错码 JSON（4xx/5xx），不是 500 HTML，不返回空数组假装成功
- [ ] bvids.txt 任取一个 BV → qwen-tts `POST /transcribe` → 200（数据链路成立）
- [ ] `pytest tests/ -q` 全绿（全 mock，不依赖真实 B 站网络）
- [ ] `config.yaml` 与 `data/` 不进仓库，代码中无任何硬编码 Cookie

## Not in scope

- 昵称搜索输入（昵称可重复可变更，引入额外 API 与风控；未来功能）
- 增量同步（v1 每次全量；代码结构留口）
- ASR / Qwen 调用 / 音视频下载 / 字幕解析（下游 qwen-tts 职责）
- 前端页面、用户系统、数据库、Redis/Celery 任务队列
- 并发多 UP 主 /collect、checkpoint、任务状态机
- 批量喂 qwen-tts（只作 README 集成示例，不进核心职责）
- Vercel 或任何远程部署（stateful 本地服务，本地进程形态）

## Open questions

- 目标 UP 主匿名（无 Cookie）能否全量拉取？若风控，把 Cookie 写进 config.yaml —— Phase 7 验收时确认
- ps 是否探过更大值（如 50）？默认 30 可配置，不依赖未验证的极端 page size
- 验收用哪个真实 UP 主：你给一个，或我从热门榜选一个大投稿量的（选前报备）

## References

- `VISION.md` — 项目定位与领域词汇
- 兄弟项目 `qwen-tts` — 接口风格、错误 JSON、配置加载、日志、文档结构约定

## Current step

**v0 收官**（2026-10-05）— 五份文档落盘，仓库 https://github.com/luduihang/qwen-bv（public）已建并 push。下一步：Phase 1（T-001~T-005，main 串行）→ 完成后按工作包章节开 worktree A（wbi）∥ B（storage），A 合并后分叉 C（bili 链）。

## Notes

- 2026-10-05 规划：沿用 qwen-tts 约定（Flask+requests+pyyaml 钉版本、BiliError+ERROR_STATUS、config.yaml gitignore、单测全 mock）
- 2026-10-05 规划：WBI（工作包 A）与 storage（工作包 B）零文件交集 → 提前到 Phase 2 窗口 git worktree 并行，Phase 4 只做 snapshot 管线整合
- 2026-10-05 并行定稿（用户确认）：执行视图 = 三工作包 A/B/C（A∥B；C 在 A 合并后分叉 ∥ B），T-015 及 Phase 5/6/7 回 main 串行；B/C 互不依赖，关键路径 = P1→A→C→T-015→P5→P6→P7
