"""storage.py 测试（工作包 B）：三文件写正确 / 原子性 / 读取 / 目录缺失 → None。

覆盖 TASKS.md 存储契约（全部 tmp_path，无真实网络，不碰真实 data/）：
- 写正确：bvids.txt 一行一个 BV（\\n 结尾）/ videos.jsonl 一行一个 JSON 且与 bvids 同序
  / manifest.json 字段齐全
- 原子性：任一 *.tmp 写失败 → 正式文件不被触碰（旧 snapshot 原样）、无本次运行
  产生的 *.tmp 残留、异常上抛
- 读取：load_bvids / load_videos(offset, limit)（total 为切片前全量）/ load_manifest
- 目录/文件缺失 → None（即从未同步）
"""
import json
from pathlib import Path

import pytest

from storage import atomic_save, load_bvids, load_manifest, load_videos

MID = 12345678

CONTRACT_MANIFEST_KEYS = {
    "mid", "name", "total_reported", "total_fetched", "total_unique", "synced_at", "pages_fetched",
}


def record(bvid, created, author="测试UP主"):
    """构造完整 VideoRecord（字段契约见 TASKS.md 契约总览）。"""
    return {
        "bvid": bvid,
        "aid": 1000,
        "title": f"视频 {bvid}",
        "url": f"https://www.bilibili.com/video/{bvid}",
        "mid": MID,
        "author": author,
        "created": created,
        "published_at": "2023-11-15T08:00:00Z",
        "length": "12:34",
        "description": "这是描述",
        "pic": f"https://i0.hdslb.com/bfs/archive/{bvid}.jpg",
        "is_union_video": False,
    }


def sample_manifest(n=3, **over):
    m = {
        "mid": MID,
        "name": "测试UP主",
        "total_reported": n,
        "total_fetched": n,
        "total_unique": n,
        "synced_at": "2026-10-05T12:00:00Z",
        "pages_fetched": 2,
    }
    m.update(over)
    return m


def sample_data(n=3):
    """n 条，created 降序（与 sync_up 排序契约一致）。"""
    bvids = [f"BV{i:04d}" for i in range(n, 0, -1)]
    videos = [record(bvid, 1700000000 + i) for bvid, i in zip(bvids, range(n, 0, -1))]
    return bvids, videos


def save(data_dir, mid=MID, n=3):
    bvids, videos = sample_data(n)
    atomic_save(data_dir, mid, bvids, videos, sample_manifest(n))
    return bvids, videos


# ---------- 写正确 ----------

def test_save_creates_up_dir_and_three_files(tmp_path):
    data = tmp_path / "data"
    save(data)
    out = data / str(MID)
    assert sorted(p.name for p in out.iterdir()) == ["bvids.txt", "manifest.json", "videos.jsonl"]


def test_save_creates_nested_data_dir(tmp_path):
    save(tmp_path / "data" / "nested")
    assert (tmp_path / "data" / "nested" / str(MID) / "bvids.txt").is_file()


def test_bvids_file_one_per_line_newline_terminated(tmp_path):
    data = tmp_path / "data"
    bvids, _ = save(data)
    content = (data / str(MID) / "bvids.txt").read_text(encoding="utf-8")
    assert content == "".join(bvid + "\n" for bvid in bvids)


def test_videos_jsonl_same_order_and_roundtrip(tmp_path):
    data = tmp_path / "data"
    bvids, videos = save(data)
    raw = (data / str(MID) / "videos.jsonl").read_text(encoding="utf-8")
    lines = raw.splitlines()
    assert len(lines) == len(videos)
    parsed = [json.loads(line) for line in lines]
    assert [r["bvid"] for r in parsed] == bvids  # 与 bvids.txt 同序
    assert parsed == videos  # 字段往返（含中文，UTF-8 无损）


def test_manifest_fields_written(tmp_path):
    data = tmp_path / "data"
    save(data)
    m = load_manifest(data, MID)
    assert m == sample_manifest(3)
    assert set(m) == CONTRACT_MANIFEST_KEYS


def test_empty_snapshot(tmp_path):
    data = tmp_path / "data"
    atomic_save(data, MID, [], [], sample_manifest(0, pages_fetched=0))
    out = data / str(MID)
    assert (out / "bvids.txt").read_text(encoding="utf-8") == ""
    assert (out / "videos.jsonl").read_text(encoding="utf-8") == ""
    assert load_bvids(data, MID) == []
    assert load_videos(data, MID, 0, 100) == (0, [])
    assert load_manifest(data, MID) == sample_manifest(0, pages_fetched=0)


def test_bvids_videos_length_mismatch_rejected(tmp_path):
    with pytest.raises(ValueError, match="长度不一致"):
        atomic_save(tmp_path, MID, ["BV1", "BV2"], [record("BV1", 1)], sample_manifest(2))
    # 校验先于任何落盘副作用
    assert not (tmp_path / str(MID)).exists()


# ---------- 原子性 ----------

@pytest.mark.parametrize("victim", ["bvids.txt", "videos.jsonl", "manifest.json"])
def test_tmp_write_failure_keeps_old_snapshot(tmp_path, victim):
    data = tmp_path / "data"
    out = data / str(MID)
    out.mkdir(parents=True)
    # 旧 snapshot
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

    # 破坏：把 victim 对应的 tmp 路径变成目录 → 该次 tmp 写必然失败
    (out / f"{victim}.tmp").mkdir()

    with pytest.raises(OSError):
        atomic_save(data, MID, ["BVNEW1"], [record("BVNEW1", 1)], sample_manifest(1))

    # 正式文件原样保留
    assert (out / "bvids.txt").read_text(encoding="utf-8") == old_bvids
    assert (out / "manifest.json").read_text(encoding="utf-8") == json.dumps(old_manifest)
    assert [json.loads(line)["bvid"] for line in
            (out / "videos.jsonl").read_text(encoding="utf-8").splitlines()] == ["BVOLD1", "BVOLD2"]
    # 无本次运行产生的 *.tmp 残留（破坏用的目录是测试夹具，不算残留）
    leftover = [p.name for p in out.iterdir() if p.name.endswith(".tmp")]
    assert leftover == [f"{victim}.tmp"]


def test_tmp_failure_on_fresh_mid_leaves_no_files(tmp_path):
    data = tmp_path / "data"
    out = data / str(MID)
    out.mkdir(parents=True)
    (out / "bvids.txt.tmp").mkdir()
    with pytest.raises(OSError):
        atomic_save(data, MID, ["BVNEW1"], [record("BVNEW1", 1)], sample_manifest(1))
    assert not (out / "bvids.txt").exists()
    assert not (out / "videos.jsonl").exists()
    assert not (out / "manifest.json").exists()
    assert not (out / "videos.jsonl.tmp").exists()
    assert not (out / "manifest.json.tmp").exists()


# ---------- 读取 ----------

def test_load_bvids_returns_list_in_order(tmp_path):
    data = tmp_path / "data"
    bvids, _ = save(data)
    assert load_bvids(data, MID) == bvids


def test_load_videos_offset_limit(tmp_path):
    data = tmp_path / "data"
    _, videos = save(data, n=5)
    total, all_rows = load_videos(data, MID, 0, 100)
    assert total == 5
    assert all_rows == videos

    total, page = load_videos(data, MID, 1, 2)
    assert total == 5
    assert page == videos[1:3]

    total, tail = load_videos(data, MID, 4, 10)
    assert total == 5
    assert tail == videos[4:]

    total, beyond = load_videos(data, MID, 99, 10)
    assert total == 5
    assert beyond == []


def test_load_manifest_roundtrip(tmp_path):
    data = tmp_path / "data"
    save(data)
    assert load_manifest(data, MID) == sample_manifest(3)


# ---------- 缺失 → None ----------

def test_missing_up_dir_returns_none(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    assert load_bvids(data, 999) is None
    assert load_videos(data, 999, 0, 100) is None
    assert load_manifest(data, 999) is None


def test_missing_data_dir_returns_none(tmp_path):
    assert load_bvids(tmp_path / "nope", 1) is None
    assert load_videos(tmp_path / "nope", 1, 0, 100) is None
    assert load_manifest(tmp_path / "nope", 1) is None
