# Tasks — bili-upstream

> Granular task list. Each task ID is `T-NNN`.
> 并行模式约定：每个任务声明 `Owns:`（允许改动的文件，并行窗口内零共享）与 `Contract:`（接口契约，冻结后改动需先改这里）。

## 契约总览（先读这个）

- 配置契约 = `config.example.yaml`（T-002 产物，唯一事实来源）：
  ```yaml
  server:
    host: "127.0.0.1"
    port: 5001
  storage:
    data_dir: "./data"
  bilibili:
    cookie: ""               # 可选；空 = 匿名
    page_size: 30            # v1 默认 30；探明更大值稳定后可配置调整
    request_interval_s: 1.0  # 相邻两页之间的间隔
    max_retries: 3           # 临时故障最大重试次数（退避 1s/2s/4s）
  timeout:
    request_s: 20            # 单个 B 站 API 请求超时
  ```
- UP 输入契约：`bili.parse_up(value) -> int`（mid）
  - 接受：正整数 int、纯数字字符串、空间 URL `https://space.bilibili.com/<mid>`（http/https、尾部 `/`、尾随 path/query、首尾空白均可）
  - 拒绝：昵称、空值、非数字、其他域名、mid≤0 → `BiliError(message, "invalid_up")`
- WBI 契约：`wbi.sign(params: dict) -> dict`
  - 返回加入 `wts`（int 时间戳）+ `w_rid`（MD5 32 位 hex）的新 dict
  - key 来源：nav 接口（`x/web-interface/nav`）`wbi_img.img_url`/`sub_url` → 两个文件名（去扩展名）拼接 → 固定 64 位置换表重排取前 32 位 = mixin key；`w_rid = md5(参数按 key 排序 urlencode(含 wts) + mixin_key)`
  - 内存缓存 TTL 10 分钟；首次 / 过期 / nav 失败重试时重新取 key
  - nav 请求失败、非 JSON、缺 wbi_img → `BiliError(message, "wbi_failed")`
- BiliError 错码集：`invalid_up | not_found | fetch_failed | timeout | rate_limited | risk_control | invalid_response | wbi_failed | incomplete | internal`
- 错误 JSON：`{"error": {"code", "message"}}`；映射：`invalid_up`→400，`not_found`→404，`fetch_failed`/`invalid_response`/`wbi_failed`/`incomplete`→502，`rate_limited`/`risk_control`→429，`timeout`→504，`internal`→500（路由 generic Exception 统一捕获 → internal）
- VideoRecord 契约：
  ```json
  {"bvid":"BV...","aid":123,"title":"...","url":"https://www.bilibili.com/video/BV...","mid":123,"author":"...","created":1700000000,"published_at":"2023-11-15T08:00:00Z","length":"12:34","description":"...","pic":"https://...","is_union_video":false}
  ```
  - `bvid` 必填：vlist 条目缺 bvid → 丢弃（不计入有效集合，log warn）
  - 其余字段缺失允许 null；`url` 由 bvid 拼装；`published_at` 为 ISO8601 UTC（Z），由 created 换算；`length` 透传 vlist 原值（B 站返回 "12:34" 形式字符串）
  - 去重键 = bvid；排序 = created 降序（稳定排序，同值保持先出现顺序）
- 分页契约：请求 pn=1 → `data.page.count` → `total_pages = ceil(count / page_size)` → 循环 pn=2..total_pages；终止条件（满足其一即停）：① 已获取数 >= count ② 当前页 vlist 为空 ③ pn 达到 total_pages；另设硬上限 `pn > total_pages + 5` 视为 invalid_response 立即停（防死循环）；相邻页之间 `sleep(request_interval_s)`
- 重试契约：只对临时故障重试 —— requests.ConnectionError / ConnectTimeout / ReadTimeout（最终错码 timeout）/ HTTP 5xx（最终错码 fetch_failed）；退避 1s→2s→4s，最多 `max_retries` 次；`code != 0` / risk_control / invalid_response / 非 JSON 不重试、立即失败
- 完整性校验契约（DECISIONS 2026-10-05-1）：`drift = total_reported - total_unique`；drift < 0（抓取期间新增）→ 成功；`0 <= drift <= max(3, total_reported 的 1%)` → 成功 + log warn；`drift > 容忍度` → `BiliError("incomplete")`，不落盘
- /collect 请求：`{"mid": 12345678}` 或 `{"up": 12345678 | "12345678" | "https://space.bilibili.com/12345678"}`；两者都给或都缺 / 解析失败 → `invalid_up`
- /collect 成功 200：`{mid, name, total_reported, total_fetched, total_unique, pages_fetched, bvids_file, videos_file, manifest_file, bvids}`；`*_file` 为相对路径（如 `./data/<mid>/bvids.txt`）；`total_fetched` = 拉到的 vlist 条目总数（含重复）
- `GET /up/<mid>/bvids`：200 `{mid, count, bvids}`；从未同步（无 manifest.json）→ 404 `not_found`
- `GET /up/<mid>/videos?offset=0&limit=100`：200 `{mid, total, offset, limit, videos}`；limit 默认 100、clamp 到 [1,500]；offset 默认 0、clamp ≥0；非整数参数按默认值处理；从未同步 → 404
- 存储契约：`data/<mid>/` 三文件
  - `bvids.txt` — 一行一个 BV，UTF-8，`\n` 结尾
  - `videos.jsonl` — 一行一个 JSON VideoRecord，与 bvids.txt 同序
  - `manifest.json` — `{mid, name, total_reported, total_fetched, total_unique, synced_at, pages_fetched}`（synced_at ISO8601 UTC）
  - `storage.atomic_save(data_dir, mid, bvids, videos, manifest)`：先在同目录写三个 `*.tmp`，全部成功后逐个 `os.replace` 为正式名；任一失败 → 清理全部 tmp、抛异常，正式文件不被触碰
  - 读取：`load_bvids(data_dir, mid) -> list | None`；`load_videos(data_dir, mid, offset, limit) -> (total, [VideoRecord]) | None`；`load_manifest(data_dir, mid) -> dict | None`；目录/文件缺失 → None
- 日志契约：`[collect] start mid=<mid>` → 每页 `[collect] page=<pn> items=<n> total=<count>` → 重试 `[collect] retry page=<pn> attempt=<k> reason=<...>` → 失败 `[collect] error code=<code> mid=<mid> ...`；成功 `[collect] ok mid=<mid> pages=<n> unique=<m> duration=<x.x>s files=./data/<mid>/`；不打印完整 Cookie（最多 "cookie=set/empty"）

### 测试场景覆盖表（21 场景）

| # | 场景 | 测试文件 | 任务 |
|---|---|---|---|
| 1 | 数字 mid 输入解析 | tests/test_up_parser.py | T-004 |
| 2 | space URL 输入解析 | tests/test_up_parser.py | T-004 |
| 3 | 非法 UP 输入 | tests/test_up_parser.py | T-004 |
| 4 | 一页视频 | tests/test_bili.py | T-011 |
| 5 | 多页视频 | tests/test_bili.py | T-013 |
| 6 | 最后一页不足 page_size | tests/test_bili.py | T-013 |
| 7 | page.count = 0 | tests/test_bili.py | T-013 |
| 8 | 不同页面出现重复 BV | tests/test_bili.py | T-013 |
| 9 | 中途某页 timeout | tests/test_bili.py | T-013 |
| 10 | retry 后成功 | tests/test_bili.py | T-013 |
| 11 | retry 最终失败 | tests/test_bili.py | T-013 |
| 12 | Bilibili code != 0 | tests/test_bili.py | T-011 |
| 13 | 风控响应 | tests/test_bili.py | T-011, T-021 |
| 14 | 非 JSON 响应 | tests/test_bili.py | T-011 |
| 15 | 响应缺 data/list/vlist | tests/test_bili.py | T-011 |
| 16 | 原子文件写入 | tests/test_storage.py | T-009 |
| 17 | 中途失败不破坏旧 snapshot | tests/test_pipeline.py | T-015 |
| 18 | /collect API 成功 | tests/test_api.py | T-018 |
| 19 | /collect API 参数错误 | tests/test_api.py | T-018 |
| 20 | GET cached bvids | tests/test_api.py | T-018 |
| 21 | GET videos 分页 | tests/test_api.py | T-018 |

## Active

### Phase 4 — storage + 原子 snapshot（T-015 回 main 串行）

- [ ] T-015 — 原子 snapshot 管线
  - **Owns:** `app.py`（run_collect 部分）, `tests/test_pipeline.py`
  - `run_collect(mid, cfg) -> payload`：parse_up → sync_up → storage.atomic_save → 响应 payload（含三个文件路径）；中途任何 BiliError → 不触碰 storage 正式文件、清理 tmp、异常上抛
  - 覆盖：成功（三文件落盘、bvids 行数 == total_unique）、第 N 页失败演练（mock：旧文件原样、无 *.tmp 残留、异常上抛）
  - **Done when:** `pytest tests/test_pipeline.py -q` 全绿

### Phase 5 — /collect、cached API（串行，main）

- [ ] T-016 — POST /collect
  - **Owns:** `app.py`（路由）
  - **Contract:** 见契约总览 /collect 请求/响应
  - **Done when:** `pytest tests/test_api.py -q` 全绿（/collect 部分）
- [ ] T-017 — GET cached API
  - **Owns:** `app.py`（路由）
  - **Contract:** 见契约总览 GET 契约
  - **Done when:** `pytest tests/test_api.py -q` 全绿（GET 部分）
- [ ] T-018 — API 测试
  - **Owns:** `tests/test_api.py`
  - 覆盖：/collect 成功（全 mock：200 + 字段齐全 + 三文件落盘）、/collect 参数错误（都缺 / 都给 / 昵称 / 非数字 → 400）、GET bvids（200 + 从未同步 404）、GET videos（offset/limit 分页 + 404 + clamp）、错误 JSON 形状 `{"error":{"code","message"}}`
  - **Done when:** `pytest tests/ -q` 全绿

### Phase 6 — 异常、限速、日志（串行，main）

- [ ] T-019 — 错误分类与风控识别
  - **Owns:** `bili.py`, `wbi.py`, `app.py`（ERROR_STATUS）
  - BiliError 错码集与 HTTP 映射定稿（按契约总览）；风控码表定稿（初始 -352/-412/-509 + HTTP 412，Phase 7 实测补充）；risk_control 不重试；路由 generic Exception → 500 internal JSON
  - **Done when:** `pytest tests/ -q` 全绿
- [ ] T-020 — 同步日志
  - **Owns:** `app.py`, `bili.py`
  - **Contract:** 见契约总览日志契约
  - **Done when:** mock 完整同步一次，日志行齐全（start/page/retry/error/ok + duration + 路径），日志无 Cookie
- [ ] T-021 — 异常场景测试
  - **Owns:** `tests/test_api.py`, `tests/test_bili.py`（补充）
  - 覆盖：各错码 → 正确 HTTP 状态 + JSON 形状（invalid_up 400 / not_found 404 / fetch_failed 502 / risk_control 429 / rate_limited 429 / timeout 504 / incomplete 502 / internal 500）；风控不返回 200 空数组
  - **Done when:** `pytest tests/ -q` 全绿

### Phase 7 — 测试、README、真实端到端（串行，main）

- [ ] T-022 — 全量测试套件
  - **Owns:** `tests/`
  - 对照契约总览 21 个测试场景逐一核对（全覆盖），全量绿
  - **Done when:** `pytest tests/ -q` 全绿，且 21 场景均有对应用例
- [ ] T-023 — README
  - **Owns:** `README.md`
  - 简介（含"qwen-tts 上游"定位）、快速开始（装依赖/配 config/启动）、curl 示例（成功+错误）、配置项表、故障排查、qwen-tts 集成示例（逐行读 bvids.txt 提交 /transcribe，仅作示例不进核心职责）
  - **Done when:** 按 README 从零走一遍能启动服务（自查记录进 PROGRESS）
- [ ] T-024 — 真实 UP 主端到端验收
  - **Owns:** 无代码改动（仅验证 + PLAN/PROGRESS 勾选；如需修复则记入 Notes）
  - 真实 UP 主跑 `POST /collect`（mid 与空间 URL 两种形态），逐条核对 PLAN.md Acceptance criteria（8 项）；最后从 bvids.txt 任取一个 BV 提交 qwen-tts `/transcribe` → 200
  - **Done when:** PLAN.md 验收标准全部勾选，结果写入 PROGRESS.md，commit + push

## In progress

（无）

## Done

- T-014 — sync_up 完整性校验（drift<0 成功 / 0≤drift≤max(3, 1%) 成功+warn / 超过 → incomplete 不落盘，DECISIONS 2026-10-05-1）+ test_sync 9 例（含 500→430 验收场景与 1% 边界）（commit `a74895f`，merge `7c1faa9`）
- T-013 — 分页/去重/重试测试 9 例（多页全量/末页不足/count=0/跨页去重保先出现/created 降序稳定/中途 timeout 重试成功/重试耗尽 timeout+fetch_failed/硬上限守卫）（commit `1752eba`）
- T-012 — fetch_all 完整分页（count→total_pages、三重终止条件、页间 sleep、_page_guard 硬上限防死循环、bvid 去重保先出现、created 降序稳定）+ sync_up 骨架（commit `134029d`）
- T-011 — bili.py 单页测试 18 例（VideoRecord 规范化/缺 bvid 丢弃/code!=0/风控码/非 JSON 不重试/缺字段/请求形状，全 mock）（commit `cefa8b7`）
- T-010 — bili.py fetch_page 单页请求（WBI 签名 GET arc/search + VideoRecord 规范化 + 临时故障 1s/2s/4s 退避重试 + 错码映射；实测新 wbi 接口列表在 data.list、旧接口 data.vlist → 两者兼容读取；fetch_page 内防御式 wbi.configure(cfg)）（commit `5044d44`）
- T-008 — storage.py 原子存储（三文件先 *.tmp 全写后逐个 os.replace；失败清理全部 tmp、重抛、正式文件不被触碰；load_bvids/load_videos/load_manifest 缺失 → None；bvids/videos 长度不一致 → 落盘前 ValueError）（commit `7848675`，merge `1a3ae4b`）
- T-009 — storage.py 测试 16 例（三文件写正确 / 原子性：tmp 写失败正式文件原样 + 无残留 / offset+limit 读取 / 缺失 → None，全 tmp_path）（commit `43237ab`）
- T-006 — wbi.py WBI 签名器（nav key 提取 + TTL 10 分钟缓存 + w_rid 签名，失败 → wbi_failed；实测匿名 nav code=-101 但 wbi_img 仍在 → 只按 wbi_img 把关不查业务 code；commit `8e46322`，merge `ad4e6fd`）
- T-007 — wbi 签名器测试 24 例（key 提取/签名形状/确定性 w_rid/特殊字符过滤/缓存命中/TTL 过期/失败不污染缓存/nav 失败 7 场景/请求头，全 mock HTTP）（commit `c127a7a`）
- T-001 — 初始化依赖（钉版本对齐 qwen-tts）、gitignore（config.yaml/data//.agent/）、根 conftest（commit `6d0e22a`）
- T-002 — config.py（REQUIRED_KEYS + DEFAULTS，缺文件/缺必填 → ConfigError）+ config.example.yaml 可直接加载（commit `761a44d`）
- T-003 — Flask 入口（create_app 工厂 + main）+ /health，启动自动建 data_dir（实测 curl 200；commit `d9ddffd`）
- T-004 — parse_up（int/纯数字串/space URL → mid；非法 → invalid_up）+ 35 单测（commit `0c59452`）
- T-005 — Phase 1 单测（test_config 8 场景 + test_app/health/data_dir），全量 52 用例绿（commit `aab5398`）

## Blocked

（无）

## Format conventions

- Task IDs increment monotonically across the project's lifetime — never reuse an ID, even for deleted tasks.
- A task is "active" if it's queued and ready; "in progress" if a session is currently working on it; "done" if its acceptance criteria are met; "blocked" if it can't proceed without resolving a dependency.
- Move tasks between sections as state changes. Don't delete completed tasks — they're a record.
- For larger tasks (>1 session of work), spawn subtasks under it rather than letting it grow.
- 并行约定：`Owns:` 声明的文件之外不得改动；契约变更必须先改本文件"契约总览"并同步相关任务。
