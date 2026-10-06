"""bili-upstream — UP 主（mid/空间 URL）→ 全量视频/BV 清单 API 入口。

配置加载见 config.py；本文件提供 Flask app 工厂、路由、run_collect 同步管线与 main()：
    GET /health → 200 {"status":"ok"}
    POST /collect {"mid":...} | {"up":...} → 200 payload / 错误 JSON（T-016）
    GET /up/<mid>/bvids → 200 {mid, count, bvids}（T-017）
    GET /up/<mid>/videos?offset&limit → 200 {mid, total, offset, limit, videos}（T-017）
（同步日志 T-020，见 TASKS.md）
"""
import sys
import traceback
from datetime import datetime, timezone

from flask import Flask, jsonify, request

import storage
import wbi
from bili import BiliError, parse_up, sync_up
from config import ConfigError, ensure_dirs, load_config

#: BiliError 错码 → HTTP 状态映射（契约见 TASKS.md 契约总览）
ERROR_STATUS = {
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


def _error_response(code, message):
    """错误 JSON 契约：{"error": {"code", "message"}} + 契约映射的状态码。"""
    return jsonify(error={"code": code, "message": message}), ERROR_STATUS.get(code, 500)


def _clamp_param(raw, default, lo=None, hi=None):
    """GET 查询参数 → int：None/非整数 → 默认值，再 clamp 到 [lo, hi]（契约）。"""
    try:
        n = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        n = default
    if lo is not None and n < lo:
        n = lo
    if hi is not None and n > hi:
        n = hi
    return n


def create_app(cfg):
    """Flask app 工厂；cfg 来自 load_config。"""
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.post("/collect")
    def collect_route():
        """POST /collect：{"mid": int} 或 {"up": int|数字串|空间 URL} → 全量同步。

        两者都给或都缺 / 解析失败 → 400 invalid_up；成功 → 200 payload（T-015 契约）；
        BiliError → 契约映射状态码 + 错误 JSON；未预期异常 → 500 internal。
        """
        body = request.get_json(silent=True) or {}
        has_mid, has_up = "mid" in body, "up" in body
        if has_mid == has_up:
            return _error_response("invalid_up", "请求必须且只能提供 mid 或 up 之一")
        up_input = body["mid"] if has_mid else body["up"]
        try:
            payload = run_collect(up_input, cfg)
        except BiliError as e:
            return _error_response(e.code, str(e))
        except Exception as e:
            traceback.print_exc()
            return _error_response("internal", f"内部错误: {e}")
        return jsonify(payload)

    @app.get("/up/<mid_str>/bvids")
    def up_bvids(mid_str):
        """GET /up/<mid>/bvids → 200 {mid, count, bvids}；从未同步 → 404 not_found。"""
        try:
            mid = parse_up(mid_str)
        except BiliError as e:
            return _error_response(e.code, str(e))
        data_dir = cfg["storage"]["data_dir"]
        if storage.load_manifest(data_dir, mid) is None:
            return _error_response("not_found", f"UP {mid} 从未同步（无 manifest.json）")
        bvids = storage.load_bvids(data_dir, mid)
        if bvids is None:  # 原子写保证三文件同生同灭，正常不会走到
            return _error_response("not_found", f"UP {mid} 从未同步（无 bvids.txt）")
        return jsonify(mid=mid, count=len(bvids), bvids=bvids)

    @app.get("/up/<mid_str>/videos")
    def up_videos(mid_str):
        """GET /up/<mid>/videos?offset&limit → 200 {mid, total, offset, limit, videos}。

        limit 默认 100 clamp [1,500]；offset 默认 0 clamp >=0；非整数参数按默认值；
        从未同步 → 404 not_found。
        """
        try:
            mid = parse_up(mid_str)
        except BiliError as e:
            return _error_response(e.code, str(e))
        data_dir = cfg["storage"]["data_dir"]
        if storage.load_manifest(data_dir, mid) is None:
            return _error_response("not_found", f"UP {mid} 从未同步（无 manifest.json）")
        offset = _clamp_param(request.args.get("offset"), 0, lo=0)
        limit = _clamp_param(request.args.get("limit"), 100, lo=1, hi=500)
        result = storage.load_videos(data_dir, mid, offset, limit)
        if result is None:  # 原子写保证三文件同生同灭，正常不会走到
            return _error_response("not_found", f"UP {mid} 从未同步（无 videos.jsonl）")
        total, videos = result
        return jsonify(mid=mid, total=total, offset=offset, limit=limit, videos=videos)

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
