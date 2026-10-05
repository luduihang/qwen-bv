"""bili.py arc/search 测试（工作包 C）：T-011 单页部分。

全 mock：wbi._http_get（假 nav，走真实 wbi.sign）+ bili._http_get（假 arc/search）；
不碰真实网络。分页/去重/重试部分见 T-013（本文件后续 commit 追加）。
"""
import re

import pytest
import requests  # noqa: F401  (T-013 重试用例使用)

import bili
import wbi
from bili import BiliError, fetch_page

NAV_PAYLOAD = {
    "code": 0,
    "message": "0",
    "data": {
        "wbi_img": {
            "img_url": "https://i0.hdslb.com/bfs/wbi/7cd087993814b8c0b183d4831acb6a27.png",
            "sub_url": "https://i0.hdslb.com/bfs/wbi/4932d08746c0beea468a043a0cba8f56.png",
        },
        "isLogin": 0,
    },
}

CFG = {
    "bilibili": {"cookie": "", "page_size": 30, "request_interval_s": 1.0, "max_retries": 3},
    "timeout": {"request_s": 20},
}


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


def vlist_entry(i, with_bvid=True, **overrides):
    e = {
        "aid": 1000 + i,
        "bvid": f"BV1test{i:03d}",
        "title": f"视频 {i}",
        "duration": "12:34",
        "desc": f"简介 {i}",
        "pic": f"https://i0.hdslb.com/bfs/{i}.jpg",
        "play": 100,
        "comment": 2,
        "created": 1700000000 + i,
        "pubdate": 1700000000 + i,
        "owner": {"mid": 12345678, "name": "测试UP"},
        "is_union_video": False,
    }
    if not with_bvid:
        del e["bvid"]
    e.update(overrides)
    return e


def arc_payload(count, vlist, code=0, message="0", list_key="list"):
    """真实 wbi 接口形状：列表在 data.list（list_key="vlist" 可模拟旧接口）。"""
    data = {list_key: vlist, "page": {"count": count, "size": 30, "pages": 1}}
    return {"code": code, "message": message, "data": data}


@pytest.fixture(autouse=True)
def _fresh_wbi(monkeypatch):
    """每用例清 wbi key 缓存并装假 nav（真实 wbi.sign 逻辑照常执行）。"""
    wbi.invalidate()
    monkeypatch.setattr(
        wbi, "_http_get", lambda url, headers, timeout: FakeResponse(200, NAV_PAYLOAD)
    )
    yield


def install_arc(monkeypatch, factory):
    """装假 arc/search；factory(call_no, params) → FakeResponse 或 Exception。返回调用记录。"""
    calls = []

    def fake_get(url, params, headers, timeout):
        calls.append({"url": url, "params": dict(params), "headers": dict(headers),
                      "timeout": timeout})
        result = factory(len(calls), params)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(bili, "_http_get", fake_get)
    return calls


def mock_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(bili.time, "sleep", lambda s: sleeps.append(s))
    return sleeps


# ---------- 正常页 / VideoRecord 规范化 ----------

def test_fetch_page_normal_normalization(monkeypatch):
    vlist = [vlist_entry(1), vlist_entry(2)]
    install_arc(monkeypatch, lambda n, p: FakeResponse(200, arc_payload(2, vlist)))
    count, records = fetch_page(12345678, 1, CFG)
    assert count == 2
    assert records[0] == {
        "bvid": "BV1test001",
        "aid": 1001,
        "title": "视频 1",
        "url": "https://www.bilibili.com/video/BV1test001",
        "mid": 12345678,
        "author": "测试UP",
        "created": 1700000001,
        "published_at": "2023-11-14T22:13:21Z",
        "length": "12:34",
        "description": "简介 1",
        "pic": "https://i0.hdslb.com/bfs/1.jpg",
        "is_union_video": False,
    }


def test_fetch_page_missing_optional_fields_null(monkeypatch):
    vlist = [{"bvid": "BV1x411c7mD", "title": "光杆条目"}]
    install_arc(monkeypatch, lambda n, p: FakeResponse(200, arc_payload(1, vlist)))
    _, records = fetch_page(1, 1, CFG)
    assert records == [{
        "bvid": "BV1x411c7mD",
        "aid": None,
        "title": "光杆条目",
        "url": "https://www.bilibili.com/video/BV1x411c7mD",
        "mid": None,
        "author": None,
        "created": None,
        "published_at": None,
        "length": None,
        "description": None,
        "pic": None,
        "is_union_video": None,
    }]


def test_fetch_page_drops_entries_without_bvid(monkeypatch, caplog):
    vlist = [vlist_entry(1), {"aid": 99, "title": "缺 bvid 的条目"}, vlist_entry(2)]
    install_arc(monkeypatch, lambda n, p: FakeResponse(200, arc_payload(3, vlist)))
    count, records = fetch_page(1, 1, CFG)
    assert count == 3  # count 原样返回（含被丢弃条目）
    assert [r["bvid"] for r in records] == ["BV1test001", "BV1test002"]
    assert any("bvid" in m for m in caplog.messages)


# ---------- code != 0 ----------

@pytest.mark.parametrize("code", [-404, -400])
def test_fetch_page_not_found_codes(monkeypatch, code):
    install_arc(monkeypatch, lambda n, p: FakeResponse(200, arc_payload(0, [], code=code,
                                                                        message="什么 UP 主")))
    with pytest.raises(BiliError) as e:
        fetch_page(1, 1, CFG)
    assert e.value.code == "not_found"


@pytest.mark.parametrize("code", [-352, -412, -509])
def test_fetch_page_risk_control_codes(monkeypatch, code):
    install_arc(monkeypatch, lambda n, p: FakeResponse(200, arc_payload(0, [], code=code,
                                                                        message="风控校验失败")))
    with pytest.raises(BiliError) as e:
        fetch_page(1, 1, CFG)
    assert e.value.code == "risk_control"


def test_fetch_page_other_nonzero_code_fetch_failed(monkeypatch):
    install_arc(monkeypatch, lambda n, p: FakeResponse(200, arc_payload(0, [], code=-500,
                                                                        message="服务器开了个小差")))
    with pytest.raises(BiliError) as e:
        fetch_page(1, 1, CFG)
    assert e.value.code == "fetch_failed"


# ---------- 非 JSON / 缺字段 → invalid_response（不重试） ----------

def test_fetch_page_non_json_invalid_response_no_retry(monkeypatch):
    calls = install_arc(monkeypatch, lambda n, p: FakeResponse(200, None))
    with pytest.raises(BiliError) as e:
        fetch_page(1, 1, CFG)
    assert e.value.code == "invalid_response"
    assert len(calls) == 1  # 非 JSON 不重试


@pytest.mark.parametrize(
    "payload",
    [
        {"code": 0, "message": "0"},                              # 缺 data
        {"code": 0, "message": "0", "data": {"list": []}},        # 缺 data.page
        {"code": 0, "message": "0",
         "data": {"page": {"count": 1, "size": 30, "pages": 1}}},  # 缺列表（list/vlist 皆无）
        {"code": 0, "message": "0", "data": {"list": "not-a-list",
         "page": {"count": 1, "size": 30, "pages": 1}}},           # 列表非列表
        {"message": "0", "data": {"list": [],
         "page": {"count": 1, "size": 30, "pages": 1}}},           # 缺 code
    ],
    ids=["no-data", "no-page", "no-vlist", "vlist-not-list", "no-code"],
)
def test_fetch_page_missing_fields_invalid_response(monkeypatch, payload):
    install_arc(monkeypatch, lambda n, p: FakeResponse(200, payload))
    with pytest.raises(BiliError) as e:
        fetch_page(1, 1, CFG)
    assert e.value.code == "invalid_response"


def test_fetch_page_old_vlist_shape_also_accepted(monkeypatch):
    """兼容旧接口形状：列表在 data.vlist 也可解析。"""
    vlist = [vlist_entry(1)]
    install_arc(monkeypatch, lambda n, p: FakeResponse(200, arc_payload(1, vlist, list_key="vlist")))
    count, records = fetch_page(1, 1, CFG)
    assert count == 1 and records[0]["bvid"] == "BV1test001"


# ---------- 请求形状 / 请求头 ----------

def test_fetch_page_request_shape_and_cookie(monkeypatch):
    calls = install_arc(monkeypatch, lambda n, p: FakeResponse(200, arc_payload(0, [])))
    cfg = {**CFG, "bilibili": {**CFG["bilibili"], "cookie": "SESSDATA=x; buvid3=y"}}
    fetch_page(777, 2, cfg)
    c = calls[0]
    assert c["url"] == bili.ARC_SEARCH_URL
    assert c["params"]["mid"] == 777
    assert c["params"]["pn"] == 2
    assert c["params"]["ps"] == 30  # page_size
    assert c["params"]["order"] == "pubdate"
    assert isinstance(c["params"]["wts"], int)
    assert re.fullmatch(r"[0-9a-f]{32}", c["params"]["w_rid"])
    assert c["headers"]["Cookie"] == "SESSDATA=x; buvid3=y"
    assert c["timeout"] == 20


def test_fetch_page_anonymous_no_cookie_header(monkeypatch):
    calls = install_arc(monkeypatch, lambda n, p: FakeResponse(200, arc_payload(0, [])))
    fetch_page(777, 1, CFG)
    assert "Cookie" not in calls[0]["headers"]
