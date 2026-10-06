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


# ---------- T-017: GET 缓存 API ----------


def write_snapshot(tmp_path, n=10):
    """用 storage 真实写一份 snapshot（不 mock），GET 端点读真实磁盘数据。"""
    cfg = make_cfg(tmp_path)
    records = make_records(n)
    bvids = [r["bvid"] for r in records]
    manifest = {
        "mid": MID,
        "name": "测试UP主",
        "total_reported": n,
        "total_fetched": n,
        "total_unique": n,
        "synced_at": "2026-10-06T00:00:00Z",
        "pages_fetched": 1,
    }
    storage.atomic_save(cfg["storage"]["data_dir"], MID, bvids, records, manifest)
    return cfg


def test_get_bvids_200(tmp_path):
    cfg = write_snapshot(tmp_path, 5)
    app = create_app(cfg)
    r = app.test_client().get(f"/up/{MID}/bvids")
    assert r.status_code == 200
    body = r.get_json()
    assert body["mid"] == MID
    assert body["count"] == 5
    assert body["bvids"] == [rec["bvid"] for rec in make_records(5)]


def test_get_bvids_never_synced_404(tmp_path):
    app = create_app(make_cfg(tmp_path))
    r = app.test_client().get(f"/up/{MID}/bvids")
    assert r.status_code == 404
    assert r.get_json()["error"]["code"] == "not_found"


def test_get_bvids_non_numeric_mid_400(tmp_path):
    """路径 mid 复用 parse_up 契约：非数字 → 400 invalid_up。"""
    app = create_app(make_cfg(tmp_path))
    r = app.test_client().get("/up/abc/bvids")
    assert r.status_code == 400
    assert r.get_json()["error"]["code"] == "invalid_up"


def test_get_videos_default_slice(tmp_path):
    cfg = write_snapshot(tmp_path, 10)
    app = create_app(cfg)
    r = app.test_client().get(f"/up/{MID}/videos")
    assert r.status_code == 200
    body = r.get_json()
    assert body["mid"] == MID
    assert body["total"] == 10
    assert body["offset"] == 0
    assert body["limit"] == 100
    assert [v["bvid"] for v in body["videos"]] == [rec["bvid"] for rec in make_records(10)]


def test_get_videos_offset_limit_slice(tmp_path):
    cfg = write_snapshot(tmp_path, 10)
    app = create_app(cfg)
    r = app.test_client().get(f"/up/{MID}/videos?offset=2&limit=3")
    assert r.status_code == 200
    body = r.get_json()
    assert body["total"] == 10  # total 是切片前全量
    assert body["offset"] == 2
    assert body["limit"] == 3
    assert [v["bvid"] for v in body["videos"]] == [rec["bvid"] for rec in make_records(10)[2:5]]


@pytest.mark.parametrize(
    "query,expected_offset,expected_limit",
    [
        ("offset=-3", 0, 100),  # offset clamp >= 0
        ("limit=99999", 0, 500),  # limit clamp <= 500
        ("limit=0", 0, 1),  # limit clamp >= 1
        ("limit=-5", 0, 1),
        ("offset=abc", 0, 100),  # 非整数 → 默认值
        ("limit=abc", 0, 100),
        ("offset=1.5", 0, 100),
        ("offset=1&limit=2", 1, 2),  # 合法值原样
    ],
)
def test_get_videos_clamp_and_defaults(tmp_path, query, expected_offset, expected_limit):
    cfg = write_snapshot(tmp_path, 10)
    app = create_app(cfg)
    r = app.test_client().get(f"/up/{MID}/videos?{query}")
    assert r.status_code == 200
    body = r.get_json()
    assert body["offset"] == expected_offset
    assert body["limit"] == expected_limit
    assert len(body["videos"]) == len(make_records(10)[expected_offset : expected_offset + expected_limit])


def test_get_videos_beyond_total_empty(tmp_path):
    cfg = write_snapshot(tmp_path, 10)
    app = create_app(cfg)
    r = app.test_client().get(f"/up/{MID}/videos?offset=50&limit=10")
    assert r.status_code == 200
    body = r.get_json()
    assert body["total"] == 10
    assert body["videos"] == []


def test_get_videos_never_synced_404(tmp_path):
    app = create_app(make_cfg(tmp_path))
    r = app.test_client().get(f"/up/{MID}/videos?offset=0&limit=10")
    assert r.status_code == 404
    assert r.get_json()["error"]["code"] == "not_found"


# ---------- T-018: 错误 JSON 形状与补充覆盖 ----------


def test_error_json_shape_exact(tmp_path):
    """契约形状：{"error": {"code", "message"}}，无多余顶层键。"""
    app = create_app(make_cfg(tmp_path))
    r = app.test_client().post("/collect", json={})
    body = r.get_json()
    assert set(body.keys()) == {"error"}
    assert set(body["error"].keys()) == {"code", "message"}
    r2 = app.test_client().get(f"/up/{MID}/bvids")
    body2 = r2.get_json()
    assert set(body2.keys()) == {"error"}
    assert set(body2["error"].keys()) == {"code", "message"}


def test_collect_non_json_body_400(tmp_path):
    """非 JSON body → 视为都缺 → 400 invalid_up（不是 415/500）。"""
    app = create_app(make_cfg(tmp_path))
    r = app.test_client().post("/collect", data="not json", content_type="text/plain")
    assert r.status_code == 400
    assert r.get_json()["error"]["code"] == "invalid_up"


def test_collect_mid_numeric_string_ok(tmp_path, monkeypatch):
    """mid 键传纯数字字符串：parse_up 统一解析，合法即 200。"""
    cfg = make_cfg(tmp_path)
    mock_sync(monkeypatch, make_records(2))
    app = create_app(cfg)
    r = app.test_client().post("/collect", json={"mid": str(MID)})
    assert r.status_code == 200
    assert r.get_json()["mid"] == MID


def test_collect_success_no_tmp_leftover(tmp_path, monkeypatch):
    """成功路径也不留 *.tmp（原子写已提交）。"""
    cfg = make_cfg(tmp_path)
    mock_sync(monkeypatch, make_records(3))
    app = create_app(cfg)
    r = app.test_client().post("/collect", json={"mid": MID})
    assert r.status_code == 200
    up_dir = Path(cfg["storage"]["data_dir"]) / str(MID)
    assert list(up_dir.glob("*.tmp")) == []


def test_videos_jsonl_roundtrip_fields(tmp_path):
    """GET videos 返回的 VideoRecord 字段与落盘一致（含中文不丢）。"""
    cfg = write_snapshot(tmp_path, 4)
    app = create_app(cfg)
    r = app.test_client().get(f"/up/{MID}/videos?offset=0&limit=4")
    videos = r.get_json()["videos"]
    assert [v["title"] for v in videos] == [f"视频{i}" for i in range(4)]
    assert all(v["url"] == f"https://www.bilibili.com/video/{v['bvid']}" for v in videos)
    assert all(set(v.keys()) >= {"bvid", "aid", "title", "url", "mid", "author", "created", "published_at", "length"} for v in videos)


# ---------- T-021: 错码全矩阵 + 风控不假装成功 + 同步日志 ----------

#: BiliError 错码集（TASKS 契约总览）→ 契约映射的 HTTP 状态
ERROR_MATRIX = {
    "invalid_up": 400,
    "not_found": 404,
    "fetch_failed": 502,
    "invalid_response": 502,
    "wbi_failed": 502,
    "incomplete": 502,
    "rate_limited": 429,
    "risk_control": 429,
    "timeout": 504,
    "internal": 500,
}


@pytest.mark.parametrize("code", list(ERROR_MATRIX))
def test_error_code_http_matrix(tmp_path, monkeypatch, code):
    """错码集每个 code → 契约 HTTP 状态 + 错误 JSON 形状；失败不落盘。"""
    cfg = make_cfg(tmp_path)
    app_ = create_app(cfg)
    if code == "invalid_up":
        r = app_.test_client().post("/collect", json={})  # 都缺 → invalid_up
    elif code == "internal":
        monkeypatch.setattr(
            "app.sync_up", lambda m, c: (_ for _ in ()).throw(RuntimeError("boom")))
        r = app_.test_client().post("/collect", json={"mid": MID})
    else:
        monkeypatch.setattr(
            "app.sync_up",
            lambda m, c: (_ for _ in ()).throw(BiliError(f"mock {code}", code)),
        )
        r = app_.test_client().post("/collect", json={"mid": MID})
    assert r.status_code == ERROR_MATRIX[code]
    body = r.get_json()
    assert set(body.keys()) == {"error"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    assert not (Path(cfg["storage"]["data_dir"]) / str(MID)).exists()  # 失败不落盘


def test_risk_control_not_200_empty_array(tmp_path, monkeypatch):
    """风控必须 429 错误 JSON，不返回 200 空数组假装成功，不落盘。"""
    monkeypatch.setattr(
        "app.sync_up",
        lambda m, c: (_ for _ in ()).throw(BiliError("风控校验失败", "risk_control")),
    )
    cfg = make_cfg(tmp_path)
    app_ = create_app(cfg)
    r = app_.test_client().post("/collect", json={"mid": MID})
    assert r.status_code == 429
    body = r.get_json()
    assert "bvids" not in body  # 不是 200 + 空 bvids 数组
    assert body["error"]["code"] == "risk_control"
    assert not (Path(cfg["storage"]["data_dir"]) / str(MID)).exists()


def test_collect_log_lines_success_no_cookie(tmp_path, monkeypatch, capsys):
    """[collect] start/ok 行齐全（mid/pages/unique/duration/files），日志无 Cookie。"""
    cfg = make_cfg(tmp_path)
    cfg["bilibili"]["cookie"] = "SESSDATA=secret_token_value"
    mock_sync(monkeypatch, make_records(3))
    app_ = create_app(cfg)
    r = app_.test_client().post("/collect", json={"mid": MID})
    assert r.status_code == 200
    out = capsys.readouterr().out
    assert f"[collect] start mid={MID} cookie=set" in out
    assert f"[collect] ok mid={MID} pages=2 unique=3 duration=" in out
    assert f"files={cfg['storage']['data_dir']}/{MID}/" in out
    assert "secret_token_value" not in out  # 不打印完整 Cookie


def test_collect_log_line_error(tmp_path, monkeypatch, capsys):
    """失败 → [collect] error code=<code> mid=<mid> duration=...s。"""
    monkeypatch.setattr(
        "app.sync_up",
        lambda m, c: (_ for _ in ()).throw(BiliError("mock 风控", "risk_control")),
    )
    app_ = create_app(make_cfg(tmp_path))
    r = app_.test_client().post("/collect", json={"mid": MID})
    assert r.status_code == 429
    out = capsys.readouterr().out
    assert f"[collect] error code=risk_control mid={MID} duration=" in out


def test_collect_log_line_invalid_up_request(tmp_path, capsys):
    """请求级 invalid_up（都缺）也有 error 行（无 mid 字段）。"""
    app_ = create_app(make_cfg(tmp_path))
    r = app_.test_client().post("/collect", json={})
    assert r.status_code == 400
    out = capsys.readouterr().out
    assert "[collect] error code=invalid_up" in out
