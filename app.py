"""bili-upstream — UP 主（mid/空间 URL）→ 全量视频/BV 清单 API 入口。

配置加载见 config.py；本文件提供 Flask app 工厂与 main()：
    GET /health → 200 {"status":"ok"}
（/collect 与 GET 缓存端点在 Phase 5 接入，见 TASKS.md）
"""
import sys

from flask import Flask, jsonify

from config import ConfigError, ensure_dirs, load_config


def create_app(cfg):
    """Flask app 工厂；cfg 来自 load_config。"""
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    return app


def main():
    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"[config] {e}", file=sys.stderr)
        sys.exit(1)
    ensure_dirs(cfg)
    app = create_app(cfg)
    host = cfg["server"]["host"]
    port = int(cfg["server"]["port"])
    print(f"[startup] bili-upstream listening on http://{host}:{port} (data_dir={cfg['storage']['data_dir']})", flush=True)
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
