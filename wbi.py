"""B 站 WBI 签名器：nav 动态 key + 内存缓存（TTL 10 分钟）+ w_rid 签名。

契约（见 TASKS.md 契约总览 WBI 契约）：
    sign(params: dict) -> dict
    - 返回加入 wts（int 时间戳）+ w_rid（MD5 32 位 hex）的新 dict（不修改入参）
    - key 来源：nav 接口 x/web-interface/nav 的 data.wbi_img.img_url/sub_url
      → 两个文件名（去扩展名）拼接 → 固定 64 位置换表重排，取前 32 位 = mixin key
    - w_rid = md5(参数按 key 排序 urlencode(含 wts) + mixin_key)
    - 内存缓存 TTL 10 分钟；首次 / 过期 / nav 失败后重试时重新取 key
    - nav 请求失败 / 非 JSON / 缺 wbi_img → BiliError(message, "wbi_failed")

说明：
- mixin key 是 B 站服务端轮换的公共 key（与用户无关），匿名与带 Cookie 共用，
  因此全局单份缓存即可；configure() 只影响请求头（Cookie）与超时。
- nav 只按"data.wbi_img 是否存在"把关：匿名 nav 返回 code=-101（账号未登录）
  但 wbi_img 仍在（2026-10-05 实测），key 照常可用；业务 code 不影响取 key。
"""
import hashlib
import re
import time
from urllib.parse import urlencode

import requests

from bili import BiliError

NAV_URL = "https://api.bilibili.com/x/web-interface/nav"

#: 固定 64 位置换表（B 站 WBI 算法公开常量，与 key 轮换无关）
MIXIN_TABLE = (
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22,
    25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
)

#: mixin key 缓存有效期（秒）
CACHE_TTL_S = 600.0

#: B 站 WBI 签名前需从 key/value 中过滤的字符（官方算法）
_SPECIAL_CHARS = re.compile(r"[!'()*]")

_DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

#: 模块级状态（单进程本地服务，无并发锁需求）
_cfg = None
_cache = {"key": None, "expires_at": 0.0}


def configure(cfg):
    """绑定应用配置（bilibili.cookie / timeout.request_s）。app 启动时调用。"""
    global _cfg
    _cfg = cfg or {}


def invalidate():
    """清除 key 缓存，下次 sign 重新取 key。"""
    _cache["key"] = None
    _cache["expires_at"] = 0.0


def _headers():
    headers = {"User-Agent": _DEFAULT_UA, "Referer": "https://space.bilibili.com"}
    cookie = _cfg.get("bilibili", {}).get("cookie") or ""
    if cookie:
        headers["Cookie"] = cookie
    return headers


def _timeout():
    return _cfg.get("timeout", {}).get("request_s", 20)


def _http_get(url, headers, timeout):
    """独立成函数，单测 mock 此函数即可覆盖全部 HTTP 路径。"""
    return requests.get(url, headers=headers, timeout=timeout)


def _filename(url):
    """wbi_img URL → 文件名（去扩展名）。"""
    return url.rstrip("/").rsplit("/", 1)[-1].split(".", 1)[0]


def _extract_mixin_key(nav_payload):
    """nav 响应 → mixin key（32 位）；结构异常 → BiliError(wbi_failed)。"""
    data = nav_payload.get("data") if isinstance(nav_payload, dict) else None
    wbi_img = data.get("wbi_img") if isinstance(data, dict) else None
    if not isinstance(wbi_img, dict):
        raise BiliError("nav 响应缺 data.wbi_img", "wbi_failed")
    img_url = wbi_img.get("img_url")
    sub_url = wbi_img.get("sub_url")
    if not img_url or not sub_url:
        raise BiliError("nav 响应 wbi_img 缺 img_url/sub_url", "wbi_failed")
    raw = _filename(img_url) + _filename(sub_url)
    if len(raw) != 64:
        raise BiliError(f"nav wbi key 长度异常: {len(raw)} != 64", "wbi_failed")
    return "".join(raw[i] for i in MIXIN_TABLE)[:32]


def _fetch_key():
    """请求 nav 取 mixin key；请求失败 / 非 JSON / 缺 wbi_img → BiliError(wbi_failed)，不写缓存。

    匿名 nav 返回 code=-101（账号未登录）但 wbi_img 仍在（实测），故不检查业务 code。
    """
    try:
        resp = _http_get(NAV_URL, _headers(), _timeout())
    except requests.RequestException as e:
        raise BiliError(f"nav 请求失败: {e}", "wbi_failed") from e
    if resp.status_code != 200:
        raise BiliError(f"nav 返回 HTTP {resp.status_code}", "wbi_failed")
    try:
        payload = resp.json()
    except ValueError as e:
        raise BiliError(f"nav 响应非 JSON: {e}", "wbi_failed") from e
    return _extract_mixin_key(payload)


def _get_mixin_key():
    """缓存命中直接返回；否则现取（失败上抛，缓存保持原样供重试）。"""
    now = time.time()
    if _cache["key"] is not None and now < _cache["expires_at"]:
        return _cache["key"]
    key = _fetch_key()
    _cache["key"] = key
    _cache["expires_at"] = time.time() + CACHE_TTL_S
    return key


def _clean(value):
    """签名前过滤官方算法要求剔除的字符。"""
    return _SPECIAL_CHARS.sub("", str(value))


def sign(params):
    """返回加入 wts + w_rid 的新 dict（不修改入参）。

    nav 失败 / 非 JSON / code != 0 / 缺 wbi_img → BiliError(code="wbi_failed")。
    """
    signed = dict(params)
    signed["wts"] = int(time.time())
    key = _get_mixin_key()
    query = urlencode([(_clean(k), _clean(v)) for k, v in sorted(signed.items())])
    signed["w_rid"] = hashlib.md5((query + key).encode("utf-8")).hexdigest()
    return signed
