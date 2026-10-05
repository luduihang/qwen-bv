"""B 站客户端：UP 主输入解析 + arc/search 全量拉取（Phase 1 仅 parse_up）。

契约（见 TASKS.md 契约总览）：
    parse_up(value) -> int  # mid
    接受：正整数 int、纯数字字符串、空间 URL https://space.bilibili.com/<mid>
          （http/https、尾部 /、尾随 path/query、首尾空白均可）
    拒绝：昵称、空值、非数字、其他域名、mid<=0 → BiliError(message, "invalid_up")
"""
import re
from urllib.parse import urlparse

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
