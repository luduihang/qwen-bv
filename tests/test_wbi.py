"""wbi 签名器测试：key 提取 / 签名形状 / 缓存 TTL / nav 失败（TASKS T-007，全 mock HTTP）。"""
import hashlib
import re
import time

import pytest
import requests

import wbi
from bili import BiliError

IMG_KEY = "7cd087993814b8c0b183d4831acb6a27"  # 32 位
SUB_KEY = "4932d08746c0beea468a043a0cba8f56"  # 32 位
MIXIN_KEY = "ea8d43340817b0e2b07698c3a6c7b868"  # = 重排(IMG_KEY+SUB_KEY)[:32]，独立预计算


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


def make_nav(img_key=IMG_KEY, sub_key=SUB_KEY, code=0, drop_wbi_img=False,
             drop_img_url=False):
    wbi_img = {}
    if not drop_img_url:
        wbi_img["img_url"] = f"https://i0.hdslb.com/bfs/wbi/{img_key}.png"
    wbi_img["sub_url"] = f"https://i0.hdslb.com/bfs/wbi/{sub_key}.png"
    data = {"isLogin": 0}
    if not drop_wbi_img:
        data["wbi_img"] = wbi_img
    return {"code": code, "message": "0" if code == 0 else "错误", "data": data}


def nav_resp(**kw):
    return FakeResponse(200, make_nav(**kw))


def install_nav(monkeypatch, resp_factory):
    """用 fake _http_get 替换真实 HTTP；返回调用计数器。"""
    calls = {"n": 0, "headers": None, "timeout": None}

    def fake_get(url, headers, timeout):
        calls["n"] += 1
        assert url == wbi.NAV_URL
        calls["headers"] = headers
        calls["timeout"] = timeout
        return resp_factory()

    monkeypatch.setattr(wbi, "_http_get", fake_get)
    return calls


@pytest.fixture(autouse=True)
def reset_state():
    wbi.configure(None)
    wbi.invalidate()
    yield
    wbi.configure(None)
    wbi.invalidate()


# ---------- key 提取 ----------

def test_extract_mixin_key_from_filenames():
    payload = make_nav()
    assert wbi._extract_mixin_key(payload) == MIXIN_KEY


def test_extract_mixin_key_strips_path_and_extension():
    payload = make_nav(
        img_key="a" * 32, sub_key="b" * 32,
    )
    key = wbi._extract_mixin_key(payload)
    raw = "a" * 32 + "b" * 32
    assert key == "".join(raw[i] for i in wbi.MIXIN_TABLE)[:32]
    assert len(key) == 32


@pytest.mark.parametrize(
    "factory",
    [
        lambda: make_nav(drop_wbi_img=True),            # 缺 data.wbi_img
        lambda: make_nav(drop_img_url=True),            # 缺 img_url
        lambda: make_nav(img_key="a" * 16, sub_key="b" * 16),  # 拼接后 32 != 64
        lambda: {"code": 0, "data": {}},                # data 缺 wbi_img
    ],
    ids=["no-wbi_img", "no-img_url", "short-key", "data-without-wbi_img"],
)
def test_extract_mixin_key_bad_payload(factory):
    with pytest.raises(BiliError) as e:
        wbi._extract_mixin_key(factory())
    assert e.value.code == "wbi_failed"


# ---------- 签名形状 ----------

def test_anonymous_nav_code_minus_101_still_yields_key(monkeypatch):
    """实测：匿名 nav 返回 code=-101（账号未登录）但 wbi_img 仍在，key 照常可用。"""
    install_nav(monkeypatch, lambda: FakeResponse(200, make_nav(code=-101)))
    out = wbi.sign({"mid": 1})
    assert re.fullmatch(r"[0-9a-f]{32}", out["w_rid"])
    assert wbi._cache["key"] == MIXIN_KEY


def test_sign_shape(monkeypatch):
    install_nav(monkeypatch, nav_resp)
    out = wbi.sign({"order": "pubdate", "mid": 99, "pn": 1, "ps": 30})
    assert isinstance(out["wts"], int)
    assert time.time() - out["wts"] <= 5
    assert re.fullmatch(r"[0-9a-f]{32}", out["w_rid"])
    # 原参数仍在
    assert (out["order"], out["mid"], out["pn"], out["ps"]) == ("pubdate", 99, 1, 30)


def test_sign_does_not_mutate_input(monkeypatch):
    install_nav(monkeypatch, nav_resp)
    params = {"mid": 1, "pn": 2}
    out = wbi.sign(params)
    assert params == {"mid": 1, "pn": 2}
    assert set(out) >= {"mid", "pn", "wts", "w_rid"}


def test_sign_deterministic_wrid(monkeypatch):
    install_nav(monkeypatch, nav_resp)
    monkeypatch.setattr(wbi.time, "time", lambda: 1700000000.0)
    out = wbi.sign({"mid": 12345, "pn": 1})
    assert out["wts"] == 1700000000
    # md5(参数按 key 排序 urlencode(含 wts) + mixin_key)
    expected = hashlib.md5(
        ("mid=12345&pn=1&wts=1700000000" + MIXIN_KEY).encode()
    ).hexdigest()
    assert out["w_rid"] == expected == "41a167bf70fedd35e7c3e8248b2b6e9f"


def test_sign_filters_special_chars(monkeypatch):
    install_nav(monkeypatch, nav_resp)
    monkeypatch.setattr(wbi.time, "time", lambda: 1700000001.0)
    with_special = wbi.sign({"q": "a!'()*b"})
    without = wbi.sign({"q": "ab"})
    assert with_special["w_rid"] == without["w_rid"] == \
        "4f6af80c4a665a0a8fcdecb86b0a47d2"


def test_different_params_different_wrid(monkeypatch):
    install_nav(monkeypatch, nav_resp)
    monkeypatch.setattr(wbi.time, "time", lambda: 1700000000.0)  # 冻结 wts，隔离变量
    r1 = wbi.sign({"mid": 1, "pn": 1})
    r2 = wbi.sign({"mid": 1, "pn": 2})
    r3 = wbi.sign({"mid": 2, "pn": 1})
    assert len({r1["w_rid"], r2["w_rid"], r3["w_rid"]}) == 3


# ---------- 缓存 ----------

def test_cache_hit_second_call_no_nav(monkeypatch):
    calls = install_nav(monkeypatch, nav_resp)
    wbi.sign({"mid": 1})
    wbi.sign({"mid": 2})
    assert calls["n"] == 1


def test_cache_ttl_expiry_refetches(monkeypatch):
    calls = install_nav(monkeypatch, nav_resp)
    wbi.sign({"mid": 1})
    assert wbi._cache["key"] == MIXIN_KEY
    assert wbi._cache["expires_at"] > time.time()
    wbi._cache["expires_at"] = 0.0  # 强制过期
    wbi.sign({"mid": 1})
    assert calls["n"] == 2


def test_failed_nav_does_not_poison_cache(monkeypatch):
    state = {"n": 0}

    def resp_factory():
        state["n"] += 1
        if state["n"] == 1:
            raise requests.ConnectionError("boom")
        return FakeResponse(200, make_nav())

    calls = install_nav(monkeypatch, resp_factory)
    with pytest.raises(BiliError) as e:
        wbi.sign({"mid": 1})
    assert e.value.code == "wbi_failed"
    assert wbi._cache["key"] is None  # 失败不写缓存
    out = wbi.sign({"mid": 1})  # 重试重新取 key
    assert out["w_rid"] and calls["n"] == 2


# ---------- nav 失败 → wbi_failed ----------

@pytest.mark.parametrize(
    "resp_factory",
    [
        lambda: (_ for _ in ()).throw(requests.ConnectionError("conn")),
        lambda: (_ for _ in ()).throw(requests.Timeout("slow")),
        lambda: FakeResponse(500, make_nav()),
        lambda: FakeResponse(200, None),  # 非 JSON
        lambda: FakeResponse(200, ["nav", "not", "an", "object"]),  # 非对象
        lambda: FakeResponse(200, make_nav(drop_wbi_img=True)),
        lambda: FakeResponse(200, make_nav(img_key="a" * 16, sub_key="b" * 16)),
    ],
    ids=[
        "connection-error", "timeout", "http-500", "non-json", "non-object",
        "missing-wbi_img", "short-key",
    ],
)
def test_nav_failure_raises_wbi_failed(monkeypatch, resp_factory):
    install_nav(monkeypatch, resp_factory)
    with pytest.raises(BiliError) as e:
        wbi.sign({"mid": 1})
    assert e.value.code == "wbi_failed"


# ---------- 请求头 / 配置 ----------

def test_nav_headers_carry_cookie_when_configured(monkeypatch):
    calls = install_nav(monkeypatch, nav_resp)
    wbi.configure({"bilibili": {"cookie": "SESSDATA=x; buvid3=y"},
                   "timeout": {"request_s": 7}})
    wbi.sign({"mid": 1})
    assert calls["headers"]["Cookie"] == "SESSDATA=x; buvid3=y"
    assert calls["headers"]["User-Agent"]
    assert calls["timeout"] == 7


def test_nav_headers_anonymous_no_cookie(monkeypatch):
    calls = install_nav(monkeypatch, nav_resp)
    wbi.sign({"mid": 1})
    assert "Cookie" not in calls["headers"]
    assert calls["timeout"] == 20  # 缺省 timeout
