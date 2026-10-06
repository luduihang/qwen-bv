"""bili-upstream — UP 主（mid/空间 URL）→ 全量视频/BV 清单 API 入口。

配置加载见 config.py；本文件提供 Flask app 工厂、路由、run_collect 同步管线与 main()：
    GET /health → 200 {"status":"ok"}
    POST /collect {"mid":...} | {"up":...} → 200 payload / 错误 JSON（T-016）
（GET 缓存端点 T-017 接入；同步日志 T-020，见 TASKS.md）
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
