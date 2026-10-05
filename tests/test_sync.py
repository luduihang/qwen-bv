"""sync_up 完整性校验测试（T-014，DECISIONS 2026-10-05-1 漂移规则）。

全 mock（复用 test_bili 的假 nav / 假 arc/search 基建）：
drift = total_reported - total_unique
- drift < 0（抓取期间新增）→ 成功，不告警
- 0 <= drift <= max(3, 1%) → 成功 + log warn
- drift > 容忍度 → BiliError(code="incomplete")
"""
import pytest

from bili import BiliError, sync_up
from test_bili import (  # noqa: F401  (_fresh_wbi 作为 fixture 复用)
    CFG,
    FakeResponse,
    _fresh_wbi,
    arc_payload,
    install_arc,
    mk_entries,
    mock_sleep,
)


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """多页同步会逐页 sleep(request_interval_s)，测试一律 mock 掉。"""
    mock_sleep(monkeypatch)
    yield


def fill_pages(unique_count, ps=30):
    """按每页 ps 条生成 {pn: vlist}，恰好 unique_count 条唯一条目。"""
    per = {}
    pn = 1
    i = 0
    while i < unique_count:
        n = min(ps, unique_count - i)
        per[pn] = mk_entries(i, n)
        i += n
        pn += 1
    return per


def pages_factory(count, per):
    def factory(n, params):
        return FakeResponse(200, arc_payload(count, per.get(params["pn"], [])))
    return factory


def test_sync_incomplete_500_to_430(monkeypatch):
    """drift 70 > max(3, 5) → incomplete（验收场景：不能把 430 当成功）。"""
    install_arc(monkeypatch, pages_factory(500, fill_pages(430)))
    with pytest.raises(BiliError) as e:
        sync_up(1, CFG)
    assert e.value.code == "incomplete"
    assert "430" in str(e.value)


@pytest.mark.parametrize(
    "reported,unique,expected_code",
    [
        (1000, 991, None),          # drift 9 ≤ 10 → 成功
        (1000, 989, "incomplete"),  # drift 11 > 10 → 失败
        (100, 97, None),            # drift 3 ≤ max(3, 1) → 成功
        (523, 517, "incomplete"),   # drift 6 > max(3, 5.23) → 失败
    ],
    ids=["1%-inner", "1%-outer", "floor-3", "floor-3-outer"],
)
def test_sync_drift_tolerance_boundaries(monkeypatch, reported, unique, expected_code):
    install_arc(monkeypatch, pages_factory(reported, fill_pages(unique)))
    if expected_code is None:
        name, total_reported, total_fetched, records, pages_fetched = sync_up(1, CFG)
        assert total_reported == reported
        assert len(records) == unique
        assert pages_fetched >= 1
    else:
        with pytest.raises(BiliError) as e:
            sync_up(1, CFG)
        assert e.value.code == expected_code


def test_sync_drift_within_tolerance_warns(monkeypatch, caplog):
    """0 < drift <= 容忍度 → 成功且 log warn（manifest 双数字供人工核对）。"""
    install_arc(monkeypatch, pages_factory(100, fill_pages(97)))
    _, total_reported, total_fetched, records, _ = sync_up(1, CFG)
    assert (total_reported, total_fetched, len(records)) == (100, 97, 97)
    assert any("drift" in m for m in caplog.messages)


def test_sync_new_posts_during_fetch_success_no_warn(monkeypatch, caplog):
    """count < unique（抓取期间新增投稿，drift < 0）→ 成功，不告警。"""
    install_arc(monkeypatch, pages_factory(99, fill_pages(101)))
    _, total_reported, total_fetched, records, pages_fetched = sync_up(1, CFG)
    assert (total_reported, total_fetched, len(records), pages_fetched) == (99, 101, 101, 4)
    assert not any("drift" in m for m in caplog.messages)


def test_sync_count_zero_success(monkeypatch):
    """count=0 → 成功空清单。"""
    install_arc(monkeypatch, lambda n, p: FakeResponse(200, arc_payload(0, [])))
    name, total_reported, total_fetched, records, pages_fetched = sync_up(1, CFG)
    assert (name, total_reported, total_fetched, records, pages_fetched) == (
        "unknown", 0, 0, [], 1
    )


def test_sync_returns_five_tuple_shape(monkeypatch):
    """返回值形状 = (name, total_reported, total_fetched, records, pages_fetched)。"""
    install_arc(monkeypatch, pages_factory(30, fill_pages(30)))
    result = sync_up(1, CFG)
    assert len(result) == 5
    name, total_reported, total_fetched, records, pages_fetched = result
    assert name == "测试UP"
    assert all(isinstance(v, int) for v in (total_reported, total_fetched, pages_fetched))
    assert isinstance(records, list)
