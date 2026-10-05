"""app 入口测试：/health 响应、data_dir 自动创建。"""
from pathlib import Path

from app import create_app, ensure_dirs


def make_cfg(tmp_path):
    return {
        "server": {"host": "127.0.0.1", "port": 5001},
        "storage": {"data_dir": str(tmp_path / "data")},
        "bilibili": {
            "cookie": "",
            "page_size": 30,
            "request_interval_s": 1.0,
            "max_retries": 3,
        },
        "timeout": {"request_s": 1},
    }


def test_health_200(tmp_path):
    # 注意：Flask 2.2 的 JSON provider 弱引用 app，测试需持有 app 引用
    app = create_app(make_cfg(tmp_path))
    r = app.test_client().get("/health")
    assert r.status_code == 200
    assert r.get_json() == {"status": "ok"}


def test_health_content_type_json(tmp_path):
    app = create_app(make_cfg(tmp_path))
    r = app.test_client().get("/health")
    assert r.content_type.startswith("application/json")


def test_ensure_dirs_creates_data_dir(tmp_path):
    cfg = make_cfg(tmp_path)
    data_dir = Path(cfg["storage"]["data_dir"])
    assert not data_dir.exists()
    ensure_dirs(cfg)
    assert data_dir.is_dir()


def test_ensure_dirs_idempotent(tmp_path):
    cfg = make_cfg(tmp_path)
    ensure_dirs(cfg)
    ensure_dirs(cfg)  # 已存在不报错
    assert Path(cfg["storage"]["data_dir"]).is_dir()
