"""bili-upstream — UP 主（mid/空间 URL）→ 全量视频/BV 清单 API 入口。

配置加载见 config.py；本文件提供 Flask app 工厂、run_collect 同步管线与 main()：
    GET /health → 200 {"status":"ok"}
    run_collect(up_input, cfg) -> payload   # parse_up → sync_up → storage.atomic_save（T-015）
（/collect 与 GET 缓存端点在 Phase 5 接入，见 TASKS.md）
"""
import sys
from datetime import datetime, timezone

from flask import Flask, jsonify

import storage
import wbi
from bili import parse_up, sync_up
from config import ConfigError, ensure_dirs, load_config


def create_app(cfg):
    """Flask app 工厂；cfg 来自 load_config。"""
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    return app


def run_collect(up_input, cfg):
    """全量同步管线：parse_up → sync_up → storage.atomic_save → 响应 payload。

    中途任何异常原样上抛：sync_up 失败 → 完全未落盘；atomic_save 失败 →
    storage 内部已清理 *.tmp，正式文件（旧 snapshot）不被触碰。
    payload 契约（TASKS.md）：mid/name/total_reported/total_fetched/total_unique/
    pages_fetched + bvids_file/videos_file/manifest_file（相对路径）+ bvids（去重后顺序）。
    """
    mid = parse_up(up_input)
    name, total_reported, total_fetched, records, pages_fetched = sync_up(mid, cfg)
    total_unique = len(records)
    bvids = [r["bvid"] for r in records]
    data_dir = str(cfg["storage"]["data_dir"]).rstrip("/")
    manifest = {
        "mid": mid,
        "name": name,
        "total_reported": total_reported,
        "total_fetched": total_fetched,
        "total_unique": total_unique,
        "synced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pages_fetched": pages_fetched,
    }
    storage.atomic_save(data_dir, mid, bvids, records, manifest)
    return {
        "mid": mid,
        "name": name,
        "total_reported": total_reported,
        "total_fetched": total_fetched,
        "total_unique": total_unique,
        "pages_fetched": pages_fetched,
        "bvids_file": f"{data_dir}/{mid}/bvids.txt",
        "videos_file": f"{data_dir}/{mid}/videos.jsonl",
        "manifest_file": f"{data_dir}/{mid}/manifest.json",
        "bvids": bvids,
    }


def main():
    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"[config] {e}", file=sys.stderr)
        sys.exit(1)
    ensure_dirs(cfg)
    wbi.configure(cfg)  # 启动时绑定 Cookie/超时（WBI key 为公共轮换，configure 只影响请求头）
    app = create_app(cfg)
    host = cfg["server"]["host"]
    port = int(cfg["server"]["port"])
    print(f"[startup] bili-upstream listening on http://{host}:{port} (data_dir={cfg['storage']['data_dir']})", flush=True)
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
