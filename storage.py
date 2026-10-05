"""原子存储：data/<mid>/ 三文件 snapshot（bvids.txt / videos.jsonl / manifest.json）。

契约（见 TASKS.md 契约总览"存储契约"）：
    atomic_save(data_dir, mid, bvids, videos, manifest)
    - bvids.txt：一行一个 BV，UTF-8，\\n 结尾
    - videos.jsonl：一行一个 JSON VideoRecord，与 bvids.txt 同序
    - manifest.json：{mid, name, total_reported, total_fetched, total_unique,
      synced_at, pages_fetched}（synced_at 由调用方以 ISO8601 UTC 提供）
    - 先在同目录写三个 *.tmp，全部成功后逐个 os.replace 为正式名（同目录 rename 原子）
    - 任一失败 → 清理全部 *.tmp、重抛异常，正式文件不被触碰（旧 snapshot 原样保留）
    - bvids 与 videos 长度不一致 → ValueError（同序一一对应的不变式）
    load_bvids(data_dir, mid) -> list | None
    load_videos(data_dir, mid, offset, limit) -> (total, [VideoRecord]) | None
    load_manifest(data_dir, mid) -> dict | None
    - 目录/文件缺失 → None（即从未同步）
    - offset/limit 的 clamp 由 API 层负责（T-017），本层只做纯切片
"""
import json
import os
from pathlib import Path

#: data/<mid>/ 下的三个正式文件名（契约固定，勿改）
BVIDS_NAME = "bvids.txt"
VIDEOS_NAME = "videos.jsonl"
MANIFEST_NAME = "manifest.json"


def _up_dir(data_dir, mid):
    return Path(data_dir).expanduser() / str(mid)


def atomic_save(data_dir, mid, bvids, videos, manifest):
    """原子写入 mid 的三文件 snapshot（契约见模块 docstring）。

    两阶段：① 三个 *.tmp 全部写成功 ② 逐个 os.replace 为正式名。
    阶段①任一步抛错 → 尽力清理已写 tmp 后重抛，正式文件绝不被触碰；
    阶段②逐文件原子提交（rename 是提交点，POSIX 下读者要么见旧、要么见新）。
    """
    if len(bvids) != len(videos):
        raise ValueError(
            f"bvids 与 videos 长度不一致: {len(bvids)} != {len(videos)}（必须同序一一对应）"
        )
    out_dir = _up_dir(data_dir, mid)
    out_dir.mkdir(parents=True, exist_ok=True)
    payloads = (
        (BVIDS_NAME, "".join(f"{bvid}\n" for bvid in bvids)),
        (VIDEOS_NAME, "".join(json.dumps(v, ensure_ascii=False) + "\n" for v in videos)),
        (MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"),
    )
    tmp_paths = {name: out_dir / f"{name}.tmp" for name, _ in payloads}
    try:
        for name, content in payloads:
            tmp_paths[name].write_text(content, encoding="utf-8")
    except Exception:
        for tmp in tmp_paths.values():
            if tmp.is_file():
                try:
                    tmp.unlink()
                except OSError:
                    pass  # 尽力清理；不吞原始异常（下方重抛）
        raise
    for name, _ in payloads:
        os.replace(tmp_paths[name], out_dir / name)


def load_bvids(data_dir, mid):
    """读 bvids.txt → BV 列表（文件顺序）；目录/文件缺失 → None。"""
    p = _up_dir(data_dir, mid) / BVIDS_NAME
    if not p.is_file():
        return None
    return [line for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_videos(data_dir, mid, offset, limit):
    """读 videos.jsonl → (total, [VideoRecord])；目录/文件缺失 → None。

    total 为切片前的全量条数；返回 videos[offset:offset+limit]
    （limit 为 None 时取 offset 之后全部）。
    """
    p = _up_dir(data_dir, mid) / VIDEOS_NAME
    if not p.is_file():
        return None
    records = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    total = len(records)
    if limit is None:
        return total, records[offset:]
    return total, records[offset : offset + limit]


def load_manifest(data_dir, mid):
    """读 manifest.json → dict；目录/文件缺失 → None。"""
    p = _up_dir(data_dir, mid) / MANIFEST_NAME
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))
