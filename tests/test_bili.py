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


# ---------- 新 wbi 接口真实形状（2026-10-06 带 Cookie 实测） ----------

def flat_vlist_entry(i, **overrides):
    """新 wbi 接口条目（实测形状）：扁平字段，无 owner 子对象，length 为 "12:34" 串。"""
    e = {
        "aid": 2000 + i,
        "bvid": f"BV2real{i:03d}",
        "title": f"视频 {i}",
        "length": "12:07",
        "description": f"简介 {i}",
        "pic": f"https://i2.hdslb.com/bfs/archive/{i}.jpg",
        "created": 1700000000 + i,
        "mid": 546195,
        "author": "老番茄",
        "is_union_video": 0,
    }
    e.update(overrides)
    return e


def arc_payload_real(count, vlist):
    """新 wbi 接口真实响应（实测）：data.list 是 dict（slist/tlist/vlist），列表在其 vlist。"""
    return {
        "code": 0,
        "message": "0",
        "data": {
            "list": {"slist": [], "tlist": {}, "vlist": vlist},
            "page": {"pn": 1, "ps": 30, "count": count},
            "is_risk": False,
        },
    }


def test_fetch_page_real_list_dict_shape(monkeypatch):
    """实测形状：data.list 为 dict 时，列表在其 vlist（Phase 4 真实冒烟发现）。"""
    vlist = [flat_vlist_entry(1), flat_vlist_entry(2)]
    install_arc(monkeypatch, lambda n, p: FakeResponse(200, arc_payload_real(2, vlist)))
    count, records = fetch_page(546195, 1, CFG)
    assert count == 2
    assert [r["bvid"] for r in records] == ["BV2real001", "BV2real002"]


def test_fetch_page_real_flat_fields_normalized(monkeypatch):
    """实测扁平字段 → VideoRecord：author/mid 直取，length 来自 'length' 键（非 'duration'），description 来自 'description' 键。"""
    vlist = [flat_vlist_entry(7)]
    install_arc(monkeypatch, lambda n, p: FakeResponse(200, arc_payload_real(1, vlist)))
    _, records = fetch_page(546195, 1, CFG)
    assert records[0] == {
        "bvid": "BV2real007",
        "aid": 2007,
        "title": "视频 7",
        "url": "https://www.bilibili.com/video/BV2real007",
        "mid": 546195,
        "author": "老番茄",
        "created": 1700000007,
        "published_at": "2023-11-14T22:13:27Z",
        "length": "12:07",
        "description": "简介 7",
        "pic": "https://i2.hdslb.com/bfs/archive/7.jpg",
        "is_union_video": 0,
    }


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


# ---------- T-013：完整分页 / 去重 / 重试 ----------

def mk_entries(start, n, bvid_prefix="BV1pg"):
    """构造 n 条 vlist 条目（i = start..start+n-1，created 递增）。"""
    return [
        vlist_entry(0, bvid=f"{bvid_prefix}{i:03d}", aid=10000 + i,
                    title=f"v{i}", created=1700000000 + i)
        for i in range(start, start + n)
    ]


def test_fetch_all_multi_page_full(monkeypatch):
    """多页全量：count=95, ps=30 → 4 页（30+30+30+5），最后一页不足 page_size。"""
    sleeps = mock_sleep(monkeypatch)
    pages = {pn: mk_entries((pn - 1) * 30, 30 if pn < 4 else 5) for pn in range(1, 5)}
    calls = install_arc(monkeypatch, lambda n, p: FakeResponse(200, arc_payload(95, pages[p["pn"]])))
    name, total_reported, total_fetched, records, pages_fetched = bili.fetch_all(12345678, CFG)
    assert (total_reported, total_fetched, pages_fetched) == (95, 95, 4)
    assert name == "测试UP"
    assert len(records) == 95
    assert [c["params"]["pn"] for c in calls] == [1, 2, 3, 4]
    assert sleeps == [1.0, 1.0, 1.0]  # 页间 3 次；末页后不 sleep
    # created 降序：最后一页（created 最大）在前
    assert records[0]["bvid"] == "BV1pg094"
    assert records[-1]["bvid"] == "BV1pg000"


def test_fetch_all_last_page_short(monkeypatch):
    """count=35 → 2 页（30+5），第二页不足 page_size 正常终止。"""
    sleeps = mock_sleep(monkeypatch)
    calls = install_arc(monkeypatch, lambda n, p: FakeResponse(
        200, arc_payload(35, mk_entries((p["pn"] - 1) * 30, 30 if p["pn"] == 1 else 5))))
    _, _, _, records, pages_fetched = bili.fetch_all(1, CFG)
    assert pages_fetched == 2 and len(records) == 35
    assert len(calls) == 2 and sleeps == [1.0]


def test_fetch_all_count_zero(monkeypatch):
    """count=0 → 成功空清单（不报错、不落空成功）。"""
    sleeps = mock_sleep(monkeypatch)
    calls = install_arc(monkeypatch, lambda n, p: FakeResponse(200, arc_payload(0, [])))
    name, total_reported, total_fetched, records, pages_fetched = bili.fetch_all(1, CFG)
    assert (total_reported, total_fetched, pages_fetched, records) == (0, 0, 1, [])
    assert name == "unknown"
    assert len(calls) == 1 and sleeps == []


def test_fetch_all_cross_page_dedup(monkeypatch):
    """跨页重复 BV → 去重保先出现（total_fetched 含重复）。"""
    mock_sleep(monkeypatch)
    p1 = mk_entries(0, 30)
    p2 = mk_entries(30, 5) + [dict(e, title="dup") for e in mk_entries(0, 5)]  # 5 新 + 5 重复
    pages = {1: p1, 2: p2}
    install_arc(monkeypatch, lambda n, p: FakeResponse(200, arc_payload(35, pages[p["pn"]])))
    _, total_reported, total_fetched, records, _ = bili.fetch_all(1, CFG)
    assert total_reported == 35
    assert total_fetched == 40  # 30 + 10（含 5 重复）
    bvids = [r["bvid"] for r in records]
    assert len(bvids) == 35 and len(set(bvids)) == 35
    # 重复条目保留先出现（第一页）的 version
    assert all(r["title"] != "dup" for r in records)


def test_fetch_all_sort_created_desc_stable(monkeypatch):
    """created 降序；同 created 稳定保先出现顺序。"""
    mock_sleep(monkeypatch)
    vlist = [
        vlist_entry(0, bvid="BV1a", title="A", created=100),
        vlist_entry(1, bvid="BV1b", title="B", created=200),
        vlist_entry(2, bvid="BV1c", title="C", created=100),  # 与 A 同 created，后出现
        vlist_entry(3, bvid="BV1d", title="D", created=300),
    ]
    install_arc(monkeypatch, lambda n, p: FakeResponse(200, arc_payload(4, vlist)))
    _, _, _, records, _ = bili.fetch_all(1, CFG)
    assert [r["bvid"] for r in records] == ["BV1d", "BV1b", "BV1a", "BV1c"]


def test_fetch_all_timeout_midpage_retry_success(monkeypatch):
    """中途某页 timeout → 退避重试后成功，分页继续。"""
    sleeps = mock_sleep(monkeypatch)
    state = {"p2_attempts": 0}

    def factory(n, p):
        if p["pn"] == 2:
            state["p2_attempts"] += 1
            if state["p2_attempts"] == 1:
                return requests.ReadTimeout("slow")
        return FakeResponse(200, arc_payload(60, mk_entries((p["pn"] - 1) * 30, 30)))

    calls = install_arc(monkeypatch, factory)
    _, total_reported, total_fetched, records, pages_fetched = bili.fetch_all(1, CFG)
    assert (total_reported, total_fetched, pages_fetched) == (60, 60, 2)
    assert len(records) == 60
    # sleep：页间 1.0（p1 后）→ 退避 1s（p2 首次超时后）
    assert sleeps == [1.0, 1]
    assert state["p2_attempts"] == 2


def test_fetch_all_retry_exhausted_timeout(monkeypatch):
    """某页 ReadTimeout 重试 max_retries 次耗尽 → timeout 上抛。"""
    sleeps = mock_sleep(monkeypatch)

    def factory(n, p):
        if p["pn"] == 2:
            return requests.ReadTimeout("slow")
        return FakeResponse(200, arc_payload(60, mk_entries((p["pn"] - 1) * 30, 30)))

    calls = install_arc(monkeypatch, factory)
    with pytest.raises(BiliError) as e:
        bili.fetch_all(1, CFG)
    assert e.value.code == "timeout"
    assert [c["params"]["pn"] for c in calls] == [1, 2, 2, 2, 2]  # p2 共 1+3 次
    assert sleeps == [1.0, 1, 2, 4]  # 页间 + 退避 1s/2s/4s


def test_fetch_all_retry_exhausted_5xx(monkeypatch):
    """某页 HTTP 5xx 重试耗尽 → fetch_failed 上抛。"""
    sleeps = mock_sleep(monkeypatch)

    def factory(n, p):
        if p["pn"] == 2:
            return FakeResponse(503, {})
        return FakeResponse(200, arc_payload(60, mk_entries((p["pn"] - 1) * 30, 30)))

    install_arc(monkeypatch, factory)
    with pytest.raises(BiliError) as e:
        bili.fetch_all(1, CFG)
    assert e.value.code == "fetch_failed"
    assert sleeps == [1.0, 1, 2, 4]


def test_page_guard_hard_limit():
    """硬上限防死循环：pn > total_pages + 5 → invalid_response（守卫单元测试；
    正常路径下终止条件 ①②③ 先于硬上限触发，硬上限为纯防御）。"""
    bili._page_guard(6, 1)    # == total_pages+5，不触发
    bili._page_guard(99, None)  # 首页尚无 total_pages，不触发
    with pytest.raises(BiliError) as e:
        bili._page_guard(7, 1)  # 7 > 1+5
    assert e.value.code == "invalid_response"


# ---------- T-021: 错码/风控定稿（T-019 路径）+ [collect] 日志行（T-020） ----------


@pytest.mark.parametrize(
    "status,code",
    [
        (412, "risk_control"),  # HTTP 412 风控
        (429, "rate_limited"),  # HTTP 429 限流
    ],
)
def test_fetch_page_http_risk_status_no_retry(monkeypatch, status, code):
    """HTTP 412/429 → 对应错码，且一次请求立即失败（不重试）。"""
    calls = install_arc(monkeypatch, lambda n, p: FakeResponse(status, {}))
    with pytest.raises(BiliError) as e:
        fetch_page(1, 1, CFG)
    assert e.value.code == code
    assert len(calls) == 1


def test_fetch_page_risk_business_code_no_retry(monkeypatch):
    """业务风控码（-352）→ risk_control，code != 0 不重试。"""
    calls = install_arc(monkeypatch, lambda n, p: FakeResponse(
        200, arc_payload(0, [], code=-352, message="风控校验失败")))
    with pytest.raises(BiliError) as e:
        fetch_page(1, 1, CFG)
    assert e.value.code == "risk_control"
    assert len(calls) == 1


def test_fetch_all_page_log_lines(monkeypatch, capsys):
    """[collect] page=<pn> items=<n> total=<count> 每页一行。"""
    mock_sleep(monkeypatch)
    install_arc(monkeypatch, lambda n, p: FakeResponse(
        200, arc_payload(35, mk_entries((p["pn"] - 1) * 30, 30 if p["pn"] == 1 else 5))))
    bili.fetch_all(1, CFG)
    out = capsys.readouterr().out
    assert "[collect] page=1 items=30 total=35" in out
    assert "[collect] page=2 items=5 total=35" in out


def test_fetch_page_retry_log_line(monkeypatch, capsys):
    """[collect] retry page=<pn> attempt=<k> reason=<...>（临时故障重试时）。"""
    state = {"n": 0}

    def factory(n, p):
        state["n"] += 1
        if state["n"] == 1:
            return requests.ConnectTimeout("slow")
        return FakeResponse(200, arc_payload(1, [vlist_entry(1)]))

    mock_sleep(monkeypatch)
    install_arc(monkeypatch, factory)
    count, records = fetch_page(1, 1, CFG)
    assert count == 1 and len(records) == 1
    out = capsys.readouterr().out
    assert "[collect] retry page=1 attempt=1 reason=ConnectTimeout" in out
