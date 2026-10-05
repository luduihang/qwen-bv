"""app.py run_collect 原子 snapshot 管线测试（T-015）。

契约（TASKS.md）：run_collect(up_input, cfg) -> payload
    parse_up → sync_up → storage.atomic_save → 响应 payload（含三个文件相对路径）
    中途任何 BiliError/异常 → storage 正式文件不被触碰（旧 snapshot 原样）、
    无本次运行产生的 *.tmp 残留、异常上抛。
全 mock：monkeypatch app.sync_up，不碰真实网络 / 真实 data/。
"""
import json
import re
from pathlib import Path

import pytest

import app
from bili import BiliError

MID = 12345678


def make_cfg(tmp_path):
    return {
        "server": {"host": "127.0.0.1", "port": 5001},
        "storage": {"data_dir": str(tmp_path / "data")},
        "bilibili": {"cookie": "", "page_size": 30, "request_interval_s": 0.0, "max_retries": 3},
        "timeout": {"request_s": 20},
    }


def rec(bvid, created, author="测试UP"):
    return {
        "bvid": bvid,
        "aid": 1000,
        "title": f"视频 {bvid}",
        "url": f"https://www.bilibili.com/video/{bvid}",
        "mid": MID,
        "author": author,
        "created": created,
        "published_at": "2023-11-14T22:13:20Z",
        "length": "12:34",
        "description": "这是描述",
        "pic": "",
        "is_union_video": False,
    }


def up_dir(cfg):
    return Path(cfg["storage"]["data_dir"]) / str(MID)


def write_old_snapshot(cfg):
    """预写旧 snapshot，用于验证失败后"原样保留"。"""
    out = up_dir(cfg)
    out.mkdir(parents=True)
    old_bvids = "BVOLD1\nBVOLD2\n"
    (out / "bvids.txt").write_text(old_bvids, encoding="utf-8")
    (out / "videos.jsonl").write_text(
        json.dumps({"bvid": "BVOLD1"}) + "\n" + json.dumps({"bvid": "BVOLD2"}) + "\n",
        encoding="utf-8",
    )
    old_manifest = {
        "mid": MID, "name": "旧快照", "total_reported": 2, "total_fetched": 2,
        "total_unique": 2, "synced_at": "2020-01-01T00:00:00Z", "pages_fetched": 1,
    }
    (out / "manifest.json").write_text(json.dumps(old_manifest), encoding="utf-8")
    return old_bvids, old_manifest


# ---------- 成功路径 ----------

def test_run_collect_success_writes_three_files(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    records = [rec(f"BV{i:04d}", 1700000000 + i) for i in (3, 2, 1)]
    seen = {}

    def fake_sync_up(mid, cfg_):
        seen["mid"] = mid
        return "测试UP", 3, 3, records, 1

    monkeypatch.setattr(app, "sync_up", fake_sync_up)
    payload = app.run_collect("12345678", cfg)  # 纯数字串 → parse_up → mid

    assert seen["mid"] == MID
    assert payload["mid"] == MID
    assert payload["name"] == "测试UP"
    assert (payload["total_reported"], payload["total_fetched"], payload["total_unique"]) == (3, 3, 3)
    assert payload["pages_fetched"] == 1
    assert payload["bvids"] == ["BV0003", "BV0002", "BV0001"]
    base = cfg["storage"]["data_dir"]
    assert payload["bvids_file"] == f"{base}/{MID}/bvids.txt"
    assert payload["videos_file"] == f"{base}/{MID}/videos.jsonl"
    assert payload["manifest_file"] == f"{base}/{MID}/manifest.json"

    # 三文件落盘；bvids 行数 == total_unique，与 payload/videos 同序
    out = up_dir(cfg)
    lines = (out / "bvids.txt").read_text(encoding="utf-8").splitlines()
    assert lines == payload["bvids"]
    assert len(lines) == payload["total_unique"]
    vlines = [json.loads(l) for l in (out / "videos.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["bvid"] for r in vlines] == payload["bvids"]
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert m["mid"] == MID and m["name"] == "测试UP"
    assert m["total_reported"] == 3 and m["total_fetched"] == 3 and m["total_unique"] == 3
    assert m["pages_fetched"] == 1
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", m["synced_at"])
    # 无 *.tmp 残留
    assert not [p for p in out.iterdir() if p.name.endswith(".tmp")]


def test_run_collect_accepts_space_url_input(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    monkeypatch.setattr(app, "sync_up", lambda mid, cfg_: ("unknown", 0, 0, [], 0))
    payload = app.run_collect(f"https://space.bilibili.com/{MID}/", cfg)
    assert payload["mid"] == MID


def test_run_collect_empty_up_success(tmp_path, monkeypatch):
    """count=0 → 成功空清单（分页契约）。"""
    cfg = make_cfg(tmp_path)
    monkeypatch.setattr(app, "sync_up", lambda mid, cfg_: ("unknown", 0, 0, [], 0))
    payload = app.run_collect(MID, cfg)
    assert payload["total_unique"] == 0
    assert payload["bvids"] == []
    assert (up_dir(cfg) / "bvids.txt").read_text(encoding="utf-8") == ""
    assert (up_dir(cfg) / "videos.jsonl").read_text(encoding="utf-8") == ""


# ---------- 失败演练（旧 snapshot 原样 + 无 tmp 残留 + 异常上抛） ----------

def test_run_collect_invalid_up_raises_without_writing(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)

    def boom(mid, cfg_):
        raise AssertionError("sync_up 不应被调用")

    monkeypatch.setattr(app, "sync_up", boom)
    with pytest.raises(BiliError) as e:
        app.run_collect("昵称", cfg)
    assert e.value.code == "invalid_up"
    assert not Path(cfg["storage"]["data_dir"]).exists()


def test_run_collect_sync_failure_keeps_old_snapshot(tmp_path, monkeypatch):
    """第 N 页失败（sync_up 抛错）：完全没走到落盘，旧文件原样。"""
    cfg = make_cfg(tmp_path)
    old_bvids, old_manifest = write_old_snapshot(cfg)

    def flaky(mid, cfg_):
        raise BiliError("模拟第 N 页 timeout", "timeout")

    monkeypatch.setattr(app, "sync_up", flaky)
    with pytest.raises(BiliError) as e:
        app.run_collect(MID, cfg)
    assert e.value.code == "timeout"
    out = up_dir(cfg)
    assert (out / "bvids.txt").read_text(encoding="utf-8") == old_bvids
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8")) == old_manifest
    assert not [p for p in out.iterdir() if p.name.endswith(".tmp")]


def test_run_collect_storage_failure_keeps_old_snapshot(tmp_path, monkeypatch):
    """sync_up 成功但 atomic_save 写 tmp 失败：storage 清理 tmp，旧文件原样。"""
    cfg = make_cfg(tmp_path)
    old_bvids, old_manifest = write_old_snapshot(cfg)
    monkeypatch.setattr(
        app, "sync_up",
        lambda mid, cfg_: ("测试UP", 2, 2, [rec("BVNEW1", 1), rec("BVNEW2", 2)], 1),
    )
    # 破坏：manifest.json.tmp 变成目录 → 第三个 tmp 写必然失败
    (up_dir(cfg) / "manifest.json.tmp").mkdir()
    with pytest.raises(OSError):
        app.run_collect(MID, cfg)
    out = up_dir(cfg)
    assert (out / "bvids.txt").read_text(encoding="utf-8") == old_bvids
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8")) == old_manifest
    # 仅剩破坏夹具本身，无本次运行产生的 tmp 残留
    leftover = [p.name for p in out.iterdir() if p.name.endswith(".tmp")]
    assert leftover == ["manifest.json.tmp"]
