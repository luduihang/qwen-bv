"""B 站客户端：UP 主输入解析 + arc/search 全量拉取（Phase 1 仅 parse_up）。

契约（见 TASKS.md 契约总览）：
    parse_up(value) -> int  # mid
    接受：正整数 int、纯数字字符串、空间 URL https://space.bilibili.com/<mid>
          （http/https、尾部 /、尾随 path/query、首尾空白均可）
    拒绝：昵称、空值、非数字、其他域名、mid<=0 → BiliError(message, "invalid_up")
"""
import logging
import math
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

#: 合法空间域名（唯一）
SPACE_HOST = "space.bilibili.com"

_DIGITS = re.compile(r"^[0-9]+$")


class BiliError(Exception):
    """B 站交互失败；code ∈ {invalid_up, not_found, fetch_failed, timeout, rate_limited,
    risk_control, invalid_response, wbi_failed, incomplete, internal}（见 TASKS.md）。"""

    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


def _digits_to_mid(digits, source):
    """纯数字串 → mid；mid <= 0 → invalid_up。"""
    mid = int(digits)
    if mid <= 0:
        raise BiliError(f"mid 必须为正整数: {source!r}", "invalid_up")
    return mid


def _from_space_url(s, source):
    """空间 URL → mid；协议/域名/mid 段非法 → invalid_up。"""
    p = urlparse(s)
    if p.scheme not in ("http", "https"):
        raise BiliError(f"空间 URL 协议必须为 http/https: {source!r}", "invalid_up")
    if (p.hostname or "") != SPACE_HOST:
        raise BiliError(f"只接受 {SPACE_HOST} 域名: {source!r}", "invalid_up")
    first = (p.path or "").strip("/").split("/", 1)[0]
    if not first:
        raise BiliError(f"空间 URL 缺少 mid: {source!r}", "invalid_up")
    if not _DIGITS.match(first):
        raise BiliError(f"空间 URL mid 必须为纯数字: {source!r}", "invalid_up")
    return _digits_to_mid(first, source)


def parse_up(value):
    """UP 输入 → mid (int)。非法输入抛 BiliError(code="invalid_up")。"""
    if isinstance(value, bool):
        raise BiliError(f"非法 UP 输入: {value!r}（bool 不是合法 mid）", "invalid_up")
    if isinstance(value, int):
        if value <= 0:
            raise BiliError(f"mid 必须为正整数: {value!r}", "invalid_up")
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            raise BiliError("UP 输入为空", "invalid_up")
        if "://" in s:
            return _from_space_url(s, value)
        if _DIGITS.match(s):
            return _digits_to_mid(s, value)
        raise BiliError(
            f"非法 UP 输入: {value!r}（只接受正整数、纯数字字符串或空间 URL）", "invalid_up"
        )
    raise BiliError(f"非法 UP 输入: {value!r}（只接受正整数、纯数字字符串或空间 URL）", "invalid_up")


# ---------- arc/search 单页请求（工作包 C，T-010；契约见 TASKS.md） ----------

#: 投稿列表接口
ARC_SEARCH_URL = "https://api.bilibili.com/x/space/wbi/arc/search"

#: 风控码表（初始版，T-019 定稿，Phase 7 实测补充）
RISK_CODES = {-352, -412, -509}

#: UP 主不存在码表（初始版，Phase 7 实测补充）
NOT_FOUND_CODES = {-404, -400}

#: 临时故障（重试对象）：连接错误 / 连接超时 / 读超时 → 最终错码 timeout
_TRANSIENT_EXC = (requests.ConnectionError, requests.ConnectTimeout, requests.ReadTimeout)

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _headers(cfg):
    headers = {"User-Agent": _UA, "Referer": "https://space.bilibili.com"}
    cookie = (cfg.get("bilibili") or {}).get("cookie") or ""
    if cookie:
        headers["Cookie"] = cookie
    return headers


def _timeout(cfg):
    return (cfg.get("timeout") or {}).get("request_s", 20)


def _http_get(url, params, headers, timeout):
    """独立成函数，单测 mock 此函数即可覆盖全部 HTTP 路径。"""
    return requests.get(url, params=params, headers=headers, timeout=timeout)


def _published_at(created):
    """created（unix 秒）→ ISO8601 UTC（Z）；非法 → None。"""
    if isinstance(created, (int, float)) and not isinstance(created, bool):
        return datetime.fromtimestamp(created, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return None


def _normalize(v):
    """vlist 条目 → VideoRecord（契约见 TASKS.md）；缺 bvid / 非 dict → None（调用方丢弃 + warn）。"""
    if not isinstance(v, dict):
        return None
    bvid = v.get("bvid")
    if not bvid:
        return None
    owner = v.get("owner") if isinstance(v.get("owner"), dict) else {}
    return {
        "bvid": bvid,
        "aid": v.get("aid"),
        "title": v.get("title"),
        "url": f"https://www.bilibili.com/video/{bvid}",
        "mid": owner.get("mid"),
        "author": owner.get("name"),
        "created": v.get("created"),
        "published_at": _published_at(v.get("created")),
        "length": v.get("duration"),  # 透传 vlist 原值（"12:34" 形式）
        "description": v.get("desc"),
        "pic": v.get("pic"),
        "is_union_video": v.get("is_union_video"),
    }


def fetch_page(mid, pn, cfg):
    """签名 GET arc/search 单页 → (count, [VideoRecord])。

    只对临时故障重试（ConnectionError/ConnectTimeout/ReadTimeout → 最终 timeout；
    HTTP 5xx → 最终 fetch_failed），退避 1s→2s→4s，最多 max_retries 次；
    code!=0 / 风控 / 非 JSON / 缺字段不重试、立即失败。
    错码：not_found / risk_control / fetch_failed / timeout / invalid_response。
    """
    import wbi  # 函数级 import：wbi 从 bili 导入 BiliError，模块级互引会循环依赖
    wbi.configure(cfg)  # 防御式绑定：保证 sign 的请求头/超时与本 cfg 一致（幂等）

    bilibili_cfg = cfg.get("bilibili") or {}
    max_retries = bilibili_cfg.get("max_retries", 3)
    page_size = bilibili_cfg.get("page_size", 30)
    headers = _headers(cfg)
    timeout = _timeout(cfg)
    base_params = {"mid": mid, "pn": pn, "ps": page_size, "order": "pubdate"}

    for attempt in range(max_retries + 1):
        params = wbi.sign(base_params)  # 每次尝试重签，wts 保持新鲜
        try:
            resp = _http_get(ARC_SEARCH_URL, params, headers, timeout)
        except _TRANSIENT_EXC as e:
            if attempt < max_retries:
                time.sleep(2 ** attempt)  # 1s → 2s → 4s
                continue
            raise BiliError(f"请求超时/连接失败（重试 {max_retries} 次后仍失败）: {e}", "timeout") from e
        except requests.RequestException as e:
            raise BiliError(f"请求失败: {e}", "fetch_failed") from e

        if 500 <= resp.status_code < 600:
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            raise BiliError(f"HTTP {resp.status_code}（重试 {max_retries} 次后仍失败）", "fetch_failed")
        if resp.status_code != 200:
            raise BiliError(f"HTTP {resp.status_code}", "fetch_failed")

        try:
            payload = resp.json()
        except ValueError as e:
            raise BiliError(f"响应非 JSON: {e}", "invalid_response") from e
        if not isinstance(payload, dict):
            raise BiliError("响应不是 JSON 对象", "invalid_response")
        code = payload.get("code")
        if code is None:
            raise BiliError("响应缺 code", "invalid_response")
        if code != 0:
            message = payload.get("message")
            if code in NOT_FOUND_CODES:
                raise BiliError(f"UP 主可能不存在 (code={code}: {message})", "not_found")
            if code in RISK_CODES:
                raise BiliError(f"命中风控 (code={code}: {message})", "risk_control")
            raise BiliError(f"arc/search 返回 code={code}: {message}", "fetch_failed")

        data = payload.get("data")
        page = data.get("page") if isinstance(data, dict) else None
        if not isinstance(page, dict):
            raise BiliError("响应缺 data.page", "invalid_response")
        # 新 wbi 接口列表在 data.list，旧接口在 data.vlist；两者皆缺 → invalid_response
        vlist = data.get("list") if isinstance(data, dict) else None
        if not isinstance(vlist, list):
            vlist = data.get("vlist") if isinstance(data, dict) else None
        if not isinstance(vlist, list):
            raise BiliError("响应缺 vlist（data.list/data.vlist）", "invalid_response")
        count = page.get("count")
        if isinstance(count, bool) or not isinstance(count, int):
            raise BiliError("data.page.count 不是整数", "invalid_response")

        records = []
        for v in vlist:
            record = _normalize(v)
            if record is None:
                aid = v.get("aid") if isinstance(v, dict) else None
                title = (v.get("title") or "")[:40] if isinstance(v, dict) else None
                logger.warning("vlist 条目缺 bvid，丢弃: aid=%s title=%s", aid, title)
                continue
            records.append(record)
        return count, records
    raise AssertionError("unreachable")  # 循环必在末次尝试 return/raise


# ---------- 完整分页 + 去重 + 同步整合（T-012 / T-014） ----------

def _created_key(record):
    """created 降序排序键；缺失/非法 → 0（排末尾）。"""
    created = record.get("created")
    if isinstance(created, bool) or not isinstance(created, (int, float)):
        return 0
    return created


def _page_guard(pn, total_pages):
    """硬上限防死循环：pn > total_pages + 5 → invalid_response 立即停。"""
    if total_pages is not None and pn > total_pages + 5:
        raise BiliError(
            f"分页硬上限：pn={pn} > total_pages+5={total_pages + 5}", "invalid_response"
        )


def fetch_all(mid, cfg):
    """完整分页 → (name, total_reported, total_fetched, records, pages_fetched)。

    分页契约（TASKS.md）：pn=1 → data.page.count → total_pages = ceil(count/ps)；
    终止条件（满足其一即停）：① 累计 >= count ② 当前页 vlist 为空 ③ pn 达 total_pages；
    另设硬上限 pn > total_pages+5 → invalid_response（防死循环）；
    相邻页之间 sleep(request_interval_s)。
    name 取首页 vlist 的 author（空则 "unknown"）；去重键 bvid（保先出现）；
    排序 created 降序（稳定）；total_fetched = 拉到的 vlist 条目总数（含重复）。
    """
    bilibili_cfg = cfg.get("bilibili") or {}
    interval = bilibili_cfg.get("request_interval_s", 1.0)
    page_size = bilibili_cfg.get("page_size", 30)

    pn = 1
    total_reported = None
    total_pages = None
    name = None
    pages_fetched = 0
    all_records = []

    while True:
        _page_guard(pn, total_pages)
        count, records = fetch_page(mid, pn, cfg)
        pages_fetched += 1
        if total_pages is None:  # 首页：定 total_pages 与 name
            total_reported = count
            total_pages = math.ceil(count / page_size) if count > 0 else 0
            name = next((r["author"] for r in records if r.get("author")), None) or "unknown"
        all_records.extend(records)

        if len(records) == 0:        # ② 当前页 vlist 为空
            break
        if len(all_records) >= count:  # ① 已获取数 >= count
            break
        if pn >= total_pages:        # ③ pn 达到 total_pages
            break
        time.sleep(interval)
        pn += 1

    seen = set()
    unique = []
    for r in all_records:
        if r["bvid"] in seen:
            continue
        seen.add(r["bvid"])
        unique.append(r)
    unique.sort(key=_created_key, reverse=True)
    return name, total_reported, len(all_records), unique, pages_fetched


def sync_up(mid, cfg):
    """全量同步 → (name, total_reported, total_fetched, records, pages_fetched)。

    完整性校验（DECISIONS 2026-10-05-1）：drift = total_reported - total_unique
    - drift < 0（抓取期间新增投稿）→ 成功（不告警）
    - 0 <= drift <= max(3, total_reported 的 1%) → 成功 + log warn
    - drift > 容忍度 → BiliError(code="incomplete")（调用方据此不落盘）
    """
    name, total_reported, total_fetched, records, pages_fetched = fetch_all(mid, cfg)
    total_unique = len(records)
    drift = total_reported - total_unique
    if drift < 0:
        logger.info(
            "完整性校验：抓取期间有新增 reported=%s unique=%s (drift=%s)",
            total_reported, total_unique, drift,
        )
        return name, total_reported, total_fetched, records, pages_fetched
    tolerance = max(3, total_reported * 0.01)
    if drift > tolerance:
        raise BiliError(
            f"完整性校验失败: reported={total_reported} unique={total_unique} "
            f"drift={drift} > 容忍度 {tolerance:g}",
            "incomplete",
        )
    logger.warning(
        "完整性校验 drift 在容忍度内: reported=%s unique=%s drift=%s 容忍度=%s",
        total_reported, total_unique, drift, f"{tolerance:g}",
    )
    return name, total_reported, total_fetched, records, pages_fetched
