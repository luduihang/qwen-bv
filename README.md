# bili-upstream

B 站 UP 主 → 全量视频/BV 清单 HTTP API。

输入 UP 主 **mid 或空间 URL**（`https://space.bilibili.com/<mid>`），一次性全量分页拉取其
**公开投稿**（B 站 `wbi/arc/search` 接口，带 WBI 签名），规范化后原子落盘，并提供
`/collect`（触发同步）与 GET 缓存端点（BV 清单 / 视频元数据分页）。

下游工具（如 qwen-tts 的转写链路）直接消费 `bvids.txt` 即可，本项目不含音频转文字。

## 功能

- `POST /collect`：解析 mid/URL → WBI 签名分页拉取 → 去重（保先出现）→ 完整性校验 → 原子落盘
- `GET /up/<mid>/bvids`：全量去重 BV 清单
- `GET /up/<mid>/videos?offset=&limit=`：VideoRecord 全量元数据（分页）
- `GET /health`：存活检查
- snapshot 原子写（先 `*.tmp` 后 rename，失败清理、不碰旧数据）
- 临时故障退避重试（1s/2s/4s）、页间限速、风控/限流识别、`[collect]` 同步日志

## 快速开始

```bash
# 1. 安装依赖（Flask 2.2.5 / requests / PyYAML，钉版本）
pip install -r requirements.txt

# 2. 准备配置（config.yaml 已 gitignore，可含 Cookie）
cp config.example.yaml config.yaml
#    在 config.yaml 的 bilibili.cookie 填入浏览器 Cookie（F12 → Network → 任意请求 →
#    复制 Cookie 请求头，至少需要 SESSDATA；详见下方说明）

# 3. 启动（默认 http://127.0.0.1:5001）
python app.py

# 4. 触发全量同步（mid 或空间 URL 二选一）
curl -s -X POST http://127.0.0.1:5001/collect \
  -H 'Content-Type: application/json' \
  -d '{"mid": 546195}' | python -m json.tool
```

同步成功后三个文件出现在 `data/<mid>/`：

| 文件 | 内容 |
|---|---|
| `bvids.txt` | 每行一个 BV，去重后顺序（created 降序，最新在前） |
| `videos.jsonl` | 每行一个 VideoRecord JSON（全量字段，UTF-8） |
| `manifest.json` | mid/name/total_reported/total_fetched/total_unique/synced_at/pages_fetched |

## 配置说明（config.yaml 全部字段）

| 字段 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `server.host` | 是 | — | 监听地址，如 `127.0.0.1` |
| `server.port` | 是 | — | 监听端口，如 `5001` |
| `storage.data_dir` | 是 | — | snapshot 根目录，如 `./data`（启动时自动创建） |
| `bilibili.cookie` | 否 | `""`（匿名） | 浏览器 Cookie 原样粘贴。**匿名请求 `arc/search` 在多数网络环境会命中 -352 风控，真实拉取必须带 Cookie** |
| `bilibili.page_size` | 否 | `30` | 每页条数（B 站该接口目前上限即 30） |
| `bilibili.request_interval_s` | 否 | `1.0` | 相邻两页之间的间隔秒数（限速，末页后不 sleep） |
| `bilibili.max_retries` | 否 | `3` | 临时故障（超时/5xx）最大重试次数，退避 1s→2s→4s |
| `timeout.request_s` | 否 | `20` | 单个 B 站 API 请求超时（秒） |

缺必填字段 → 启动即拒绝并提示（`load_config` 校验）。

## API

### POST /collect

请求体：`{"mid": <int>}` 或 `{"up": <int|数字串|空间URL>}`，二者**必须且只能给一个**。

```bash
curl -s -X POST http://127.0.0.1:5001/collect \
  -H 'Content-Type: application/json' \
  -d '{"up": "https://space.bilibili.com/546195"}'
```

200 响应：

```json
{
  "mid": 546195,
  "name": "老番茄",
  "total_reported": 678,
  "total_fetched": 678,
  "total_unique": 678,
  "pages_fetched": 23,
  "bvids_file": "./data/546195/bvids.txt",
  "videos_file": "./data/546195/videos.jsonl",
  "manifest_file": "./data/546195/manifest.json",
  "bvids": ["BV1xx411c7mD", "..."]
}
```

字段说明：`total_reported` = B 站声称的投稿数；`total_fetched` = 实际拉取条数（含重复）；
`total_unique` = 去重后条数。完整性校验规则：`drift = total_fetched - total_reported`，
`drift < 0` 直接成功；`0 ≤ drift ≤ max(3, 1%)` 成功（日志 warn，同步期新投稿常见）；
超过 → `incomplete` 报错、**不落盘**。

### GET /up/<mid>/bvids

```bash
curl -s http://127.0.0.1:5001/up/546195/bvids
# → {"mid": 546195, "count": 678, "bvids": ["BV1xx411c7mD", "..."]}
```

### GET /up/<mid>/videos?offset=0&limit=100

```bash
curl -s "http://127.0.0.1:5001/up/546195/videos?offset=0&limit=2"
# → {"mid": 546195, "total": 678, "offset": 0, "limit": 2, "videos": [{...}, {...}]}
```

`limit` 默认 100、clamp 到 [1, 500]；`offset` 默认 0、clamp ≥ 0；非整数参数按默认值处理。
VideoRecord 字段：`bvid / aid / title / url / mid / author / created / published_at
（ISO8601 UTC，如 2024-01-01T00:00:00Z）/ length / description / pic / is_union_video`。

### GET /health

```bash
curl -s http://127.0.0.1:5001/health   # → {"status": "ok"}
```

### 错误响应

统一形状：`{"error": {"code": "...", "message": "..."}}`

| code | HTTP | 含义 |
|---|---|---|
| `invalid_up` | 400 | mid/up 缺失、都给、或非数字/非空间 URL |
| `not_found` | 404 | mid 不存在 / 空间受限（B 站 -404/-403）；GET 缓存端点指向上从未同步的 mid |
| `fetch_failed` | 502 | 请求失败 / HTTP 5xx 重试耗尽 / 未知业务错误码 |
| `invalid_response` | 502 | 响应非 JSON / 缺 data、page、列表字段 |
| `wbi_failed` | 502 | WBI 签名 key 获取失败 |
| `incomplete` | 502 | 完整性校验未通过（drift 超容忍度，不落盘） |
| `rate_limited` | 429 | HTTP 429 限流（不重试） |
| `risk_control` | 429 | 风控（业务码 -352/-412/-509 或 HTTP 412，不重试） |
| `timeout` | 504 | 超时/连接失败重试耗尽 |
| `internal` | 500 | 未预期异常 |

## 同步日志

`POST /collect` 期间向 stdout 打印（进程日志，非 API 响应）：

```
[collect] start mid=546195 cookie=set
[collect] page=1 items=30 total=678
[collect] retry page=2 attempt=1 reason=ReadTimeout   ← 仅临时故障重试时
...
[collect] ok mid=546195 pages=23 unique=678 duration=33.7s files=./data/546195/
```

失败时打印 `[collect] error code=<code> mid=<mid> duration=<x.x>s msg=<...>`。
日志只记录 `cookie=set/empty`，**不打印 Cookie 内容**。

## 故障排查

| 症状 | 处理 |
|---|---|
| `risk_control`（429，message 含 -352/风控） | 未带 Cookie 或 Cookie 过期 → 更新 `config.yaml` 的 `bilibili.cookie` 后重启；刚被风控则等几小时再试 |
| `incomplete`（502） | 同步期间 UP 主有新投稿导致 reported 数上涨超容忍度 → 重新 `POST /collect`；未落盘，旧 snapshot 不受影响 |
| `timeout` / `fetch_failed`（5xx） | 网络波动，重试一般恢复；持续出现可加大 `timeout.request_s` |
| `data/<mid>/*.tmp` 残留 | 正常不会（失败自动清理）；进程被 kill 等极端情况可能残留，**直接删除即可**，正式文件不受影响 |
| GET 缓存端点 404 `not_found` | 该 mid 从未成功同步（无 manifest.json）→ 先 `POST /collect` |
| 412/429 频繁出现 | 请求过快 → 调大 `request_interval_s`、调小 `page_size`、降低调用频率 |

## 与下游集成（可选）

`bvids.txt` 一行一个 BV，可直接喂给任何按 BV 处理的下游（例如 qwen-tts 的
`POST /transcribe` 转写链路）。本仓库不依赖、不包含任何转写逻辑。

## 测试

```bash
python -m pytest tests/ -q    # 195 例全绿（全 mock，不碰真实网络）
```

21 个契约测试场景的覆盖映射见 [`tests/SCENARIOS.md`](tests/SCENARIOS.md)。

## 项目结构

| 文件 | 职责 |
|---|---|
| `app.py` | Flask 入口 + 路由 + `run_collect` 管线 + 错误映射 + 同步日志 |
| `bili.py` | `parse_up`（mid/URL 解析）、`fetch_page`（单页+重试+错码）、`fetch_all`（分页/去重）、`sync_up`（整合+完整性校验） |
| `wbi.py` | WBI 签名（nav 动态 key，TTL 10min 缓存） |
| `storage.py` | 原子 snapshot（`*.tmp` + rename）、读取/clamp |
| `config.py` | 配置加载校验（必填拒绝启动、可选补默认） |
| `tests/` | 全 mock 单测/集成测试 + SCENARIOS.md 覆盖映射 |
