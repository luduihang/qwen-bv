# Vision — B 站 UP 主 → 视频/BV 清单 API（bili-upstream）

> Loaded at session start. The agent uses this to ground every decision in *what the app is supposed to be*.
> Update when the answer to "what is this app" actually changes — not for every new feature.

## What this app is
轻量本地 HTTP API 服务：给一个 B 站 UP 主（mid 或空间 URL），自动全量分页拉取其全部公开投稿视频，
规范化、以 bvid 去重、按发布时间倒序，原子保存为 `bvids.txt` / `videos.jsonl` / `manifest.json`，
并通过 HTTP API 返回 BV 清单。

本项目是 **bili-upstream**（名称固定于此）：qwen-tts 的上游。只负责"UP 主 → 视频清单/BV 清单"，
产出物由其他程序（如 shell 脚本）逐个提交给 qwen-tts 的 `POST /transcribe`。

## Who it's for
仅我自己（个人视频转写链路），无外部用户。下游是本机的 qwen-tts（127.0.0.1:5000）。

## What problem it solves
qwen-tts 只解决"一条 BV 号如何变成文本"，不负责发现某个 UP 主有哪些视频。
目前要把一个 UP 主的全部视频转成文字，得手动翻空间、手动记 BV 号。
希望一次 API 调用（mid/空间 URL 进）直接拿到该 UP 主全量、去重、排序的 BV 清单文件。

## How a user gets value
`POST /collect`，body `{"mid": 12345678}` 或 `{"up": "https://space.bilibili.com/12345678"}` 或 `{"up": "12345678"}`，
内部统一解析为 `mid: int`，同步执行完整同步后返回 JSON：
`{ "mid", "name", "total_reported", "total_fetched", "total_unique", "pages_fetched", "bvids_file", "videos_file", "manifest_file", "bvids" }`

主流程（单次请求内顺序执行）：
1. 输入解析 → `mid: int`（数字 / 空间 URL；昵称不做 v1 唯一输入）
2. 动态获取并缓存 WBI key（不写死 w_rid）→ 签名请求
3. `x/space/wbi/arc/search` 第一页 → 取 `data.page.count` → 计算总页数
4. 顺序分页拉完所有页（页间可配置间隔；临时故障有限重试）
5. 规范化 VideoRecord → 以 bvid 为唯一键去重 → 按 created 从新到旧排序
6. 先写 `*.tmp`，整个 UP 主同步成功后 rename 原子替换 `data/<mid>/` 下三个正式文件
7. 返回 JSON；任何中途失败都不覆盖上次完整 snapshot

读取（只读已持久化数据，不偷偷触发网络同步）：
- `GET /up/<mid>/bvids` → `{ "mid", "count", "bvids" }`（从未同步 → 404）
- `GET /up/<mid>/videos?offset=&limit=` → `{ "mid", "total", "offset", "limit", "videos" }`

## What it's not
- 不做 ASR、不调 Qwen 模型、不下载视频或音频 —— 那是下游 qwen-tts 的职责
- 不做字幕解析、不做前端页面、不做用户系统/认证
- 不引入数据库、Redis/Celery 等任务队列 —— 本地个人服务，同步执行
- 不做昵称搜索输入 —— 昵称可重复、可变更，且引入额外 API 与风控；留作未来功能
- v1 不做增量同步 —— 每次 /collect 全量重拉；代码结构允许未来加增量
- 不部署 Vercel —— 依赖本地磁盘 snapshot（data/），部署形态是本地进程
- 不是批处理/调度系统 —— 把 BV 清单喂给 qwen-tts 只是集成示例，不在本项目职责内

## Success looks like
- 给一个真实 UP 主 mid 或空间 URL，`POST /collect` 自动完成：解析 mid → WBI 签名 → 首页取总数 → 全量分页 → 提取有效 BV → 去重 → 排序 → 原子落盘 → 200 JSON
- `data/<mid>/bvids.txt` 一行一个 BV（UTF-8、无 JSON），条数与 `manifest.json` 的 total_unique 一致
- 从 bvids.txt 任取一个 BV 提交本机 qwen-tts `POST /transcribe` 正常转写 —— 数据链路成立：
  UP 主 → 视频发现 → BV → qwen-tts → 音频 → ASR → txt
- 中途失败（如第 17/18 页挂了）时旧 snapshot 原样保留，绝不出现"看似正常实为半截"的 bvids.txt

## Current phase
v0 —— 规划完成（VISION/PLAN/TASKS 就绪），Phase 1 未开始。

## Architecture

**Components:**
- `app.py` — Flask HTTP 层：`/health`、`POST /collect`、`GET /up/<mid>/bvids`、`GET /up/<mid>/videos`；错误码→HTTP 状态映射
- `config.py` — config.yaml 加载与校验（必填项/默认值；敏感项只存在于本地 config.yaml）
- `bili.py` — B 站 API 客户端：UP 主输入解析、arc/search 全量分页、VideoRecord 规范化、去重排序、重试
- `wbi.py` — WBI key 动态获取 + 缓存 + w_rid 签名
- `storage.py` — `data/<mid>/` 下 bvids.txt / videos.jsonl / manifest.json 的原子写（tmp+rename）与读取
- `config.yaml` / `config.example.yaml` — 全部参数（server、storage、bilibili、timeout）
- `data/<mid>/` — 每个 UP 主一个目录的持久化 snapshot

**Data flow:** `POST /collect → 解析 mid → wbi 签名 → arc/search 分页（顺序 + 间隔 + 有限重试）→ VideoRecord 规范化/去重/排序 → tmp 原子落盘 → JSON 响应`；GET 端点只读 `data/<mid>/` 已持久化文件

**Key tech choices:**
- Python 3 + Flask + requests + pyyaml —— 与 qwen-tts 完全一致的轻量依赖
- 数据接口用 `x/space/wbi/arc/search`（已废弃的 `x/space/arc/search` 不用）
- WBI key 动态获取 + 缓存，w_rid 现算，绝不硬编码
- 匿名优先；Cookie 可配置（config.yaml，gitignore，绝不进代码/仓库）
- 顺序分页 + 页间约 1s 间隔 + 临时故障 1s/2s/4s 退避、有限重试 —— 目标稳定，不追求最快
- v1 每次全量同步；结构为未来增量同步留口（如"看到连续已存 BV 提前停止"）

## Constraints worth knowing
- 运行在本地机器：B 站网络可达；下游 qwen-tts 在 127.0.0.1:5000（集成示例用）
- 匿名能成功就无 Cookie 工作；匿名被风控时必须返回明确错误（risk_control/rate_limited），不能假装成功返回空数组
- `page.count=500` 实际只拿到 430（且不能证明是抓取期间被删）→ 本次同步失败，旧 snapshot 保留，不把 430 当成功
- 错误必须可区分：UP 主不存在 / 参数错误 / 网络错误 / 超时 / HTTP 错误 / API code≠0 / WBI 失败 / Cookie 问题 / 风控 / 响应结构异常 —— 一律 JSON 错误，不统一 500
- 所有核心参数走 config.yaml，不散落在代码里

## Domain glossary
> Use these terms exactly. Avoid synonyms or paraphrasing in code, comments, UI, docs, or chat.

| Term | Definition |
|---|---|
| UP 主 | B 站内容作者；v1 以 mid 或空间 URL 唯一标识 |
| mid | UP 主的数字 ID（int），本项目内部统一主键 |
| 空间 URL | `https://space.bilibili.com/<mid>` 形式的 UP 主主页地址，解析为 mid |
| BV 号 | B 站视频 ID（如 BV1GJ411x7h7），bvids.txt 的一行内容，下游 qwen-tts 的唯一输入 |
| arc/search 接口 | `x/space/wbi/arc/search`，UP 主投稿视频分页接口（废弃接口 `x/space/arc/search` 不用） |
| WBI 签名 | arc/search 要求的 w_rid 机制；key 从 nav 接口动态获取并缓存，w_rid 现算 |
| page.count | arc/search 返回的投稿总数，用于计算总页数与完整性校验 |
| VideoRecord | 内部统一视频结构（bvid/aid/title/url/mid/author/created/published_at/length/description/pic/is_union_video）；bvid 必填，其余允许合理 null/默认值 |
| 全量同步 | 一次 /collect 从第 1 页拉到最后一页；v1 唯一同步模式 |
| 原子 snapshot | 先写 *.tmp，整个 UP 主同步成功后 rename 替换正式文件；中途失败旧数据原样保留 |
| bvids.txt | 一行一个 BV 的 UTF-8 纯文本清单，供 shell/Python 逐行读取 |
| manifest.json | 本次同步元数据（mid/name/total_reported/total_fetched/total_unique/synced_at/pages_fetched） |
| 风控 | B 站对匿名/高频请求的拦截；必须返回明确错误而非空数组 |
| Cookie | 可选 B 站登录态，写 config.yaml（gitignore），绝不硬编码/进仓库 |

**Avoided terms:** 不叫 "archive"（职责是生成视频清单，不是归档存储体系）；不说 "下载视频"（只拉视频列表元数据，不碰音视频文件）；不说 "昵称查询"（v1 输入只有 mid/空间 URL）。
