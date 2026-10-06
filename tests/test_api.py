"""API 测试：POST /collect 与 GET /up/<mid>/{bvids,videos}（全 mock，不碰真实网络/B 站）。

契约见 TASKS.md 契约总览（/collect 请求/响应、GET 契约、错误 JSON）。
"""
import json
from pathlib import Path

import pytest

import storage
from app import create_app
from bili import BiliError

MID = 546195


def make_cfg(tmp_path):
    return {
        "server": {"host": "127.0.0.1", "port": 5001},
        "storage": {"data_dir": str(tmp_path / "data")},
        "bilibili": {"cookie": "", "page_size": 30, "request_interval_s": 0, "max_retries": 3},
        "timeout": {"request_s": 1},
    }


def make_records(n, start=1700000000):
    """n 条契约形状的 VideoRecord（bvid 稳定可断言）。"""
    recs = []
    for i in range(n):
        bvid = f"BV1{i:09d}"
        recs.append({
            "bvid": bvid,
            "aid": 1000 + i,
            "title": f"视频{i}",
            "url": f"https://www.bilibili.com/video/{bvid}",
            "mid": MID,
            "author": "测试UP主",
            "created": start + i,
            "published_at": "2023-11-15T08:00:00Z",
            "length": "12:34",
            "description": f"desc{i}",
            "pic": "https://i0.hdslb.com/bfs/x.jpg",
            "is_union_video": False,
        })
    return recs


def mock_sync(monkeypatch, records, name="测试UP主"):
    """mock app.sync_up → (name, total_reported, total_fetched, records, pages_fetched)。"""
    def fake_sync_up(mid, cfg):
        assert mid == MID
        return name, len(records), len(records) + 2, records, 2

    monkeypatch.setattr("app.sync_up", fake_sync_up)


# ---------- T-016: POST /collect ----------


def test_collect_success_200_fields_and_files(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    records = make_records(5)
    mock_sync(monkeypatch, records)
    app = create_app(cfg)
    r = app.test_client().post("/collect", json={"mid": MID})
    assert r.status_code == 200
    body = r.get_json()
    assert body["mid"] == MID
    assert body["name"] == "测试UP主"
    assert body["total_reported"] == 5
    assert body["total_fetched"] == 7
    assert body["total_unique"] == 5
    assert body["pages_fetched"] == 2
    assert body["bvids"] == [rec["bvid"] for rec in records]
    # *_file 为相对路径（契约：./data/<mid>/...）
    assert body["bvids_file"] == f"{cfg['storage']['data_dir']}/{MID}/bvids.txt"
    assert body["videos_file"] == f"{cfg['storage']['data_dir']}/{MID}/videos.jsonl"
    assert body["manifest_file"] == f"{cfg['storage']['data_dir']}/{MID}/manifest.json"
    # 三文件真实落盘且内容一致
    up_dir = Path(cfg["storage"]["data_dir"]) / str(MID)
    assert (up_dir / "bvids.txt").read_text(encoding="utf-8").splitlines() == [
        rec["bvid"] for rec in records
    ]
    assert len((up_dir / "videos.jsonl").read_text(encoding="utf-8").splitlines()) == 5
    manifest = json.loads((up_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mid"] == MID
    assert manifest["total_unique"] == 5
    assert manifest["pages_fetched"] == 2
    assert manifest["synced_at"].endswith("Z")


def test_collect_success_up_url_input(tmp_path, monkeypatch):
    """{"up": 空间 URL} 与 {"mid": int} 等价（parse_up 统一解析）。"""
    cfg = make_cfg(tmp_path)
    mock_sync(monkeypatch, make_records(3))
    app = create_app(cfg)
    r = app.test_client().post("/collect", json={"up": f"https://space.bilibili.com/{MID}"})
    assert r.status_code == 200
    assert r.get_json()["mid"] == MID


def test_collect_success_up_numeric_string(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    mock_sync(monkeypatch, make_records(1))
    app = create_app(cfg)
    r = app.test_client().post("/collect", json={"up": str(MID)})
    assert r.status_code == 200
    assert r.get_json()["mid"] == MID


@pytest.mark.parametrize(
    "payload",
    [
        {},  # 都缺
        {"mid": MID, "up": MID},  # 都给
        {"up": "某知名UP主"},  # 昵称
        {"up": "12a45"},  # 非数字
        {"up": "https://bilibili.com/123"},  # 其他域名
        {"mid": 0},  # mid <= 0
        {"mid": None},  # 空值
        {"up": "   "},  # 空白
    ],
)
def test_collect_invalid_up_400(tmp_path, payload):
    app = create_app(make_cfg(tmp_path))
    r = app.test_client().post("/collect", json=payload)
    assert r.status_code == 400
    body = r.get_json()
    assert body["error"]["code"] == "invalid_up"
    assert body["error"]["message"]


@pytest.mark.parametrize("code,status", [
    ("not_found", 404),
    ("fetch_failed", 502),
    ("invalid_response", 502),
    ("wbi_failed", 502),
    ("incomplete", 502),
    ("rate_limited", 429),
    ("risk_control", 429),
    ("timeout", 504),
])
def test_collect_bili_error_code_mapping(tmp_path, monkeypatch, code, status):
    """sync_up 抛 BiliError → 契约映射的 HTTP 状态 + 错误 JSON；不落盘。"""
    def fake_sync_up(mid, cfg):
        raise BiliError(f"mock {code}", code)

    monkeypatch.setattr("app.sync_up", fake_sync_up)
    cfg = make_cfg(tmp_path)
    app = create_app(cfg)
    r = app.test_client().post("/collect", json={"mid": MID})
    assert r.status_code == status
    body = r.get_json()
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    assert not (Path(cfg["storage"]["data_dir"]) / str(MID)).exists()  # 失败不落盘


def test_collect_unexpected_error_500_internal(tmp_path, monkeypatch):
    def fake_sync_up(mid, cfg):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.sync_up", fake_sync_up)
    app = create_app(make_cfg(tmp_path))
    r = app.test_client().post("/collect", json={"mid": MID})
    assert r.status_code == 500
    body = r.get_json()
    assert body["error"]["code"] == "internal"
    assert body["error"]["message"]
