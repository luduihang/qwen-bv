"""配置加载测试：正常 / example 可直接加载 / 缺文件 / 解析失败 / 缺必填项 / 可选默认补全。"""
import copy
from pathlib import Path

import pytest
import yaml

from config import ConfigError, load_config

EXAMPLE = {
    "server": {"host": "127.0.0.1", "port": 5001},
    "storage": {"data_dir": "./data"},
    "bilibili": {
        "cookie": "",
        "page_size": 30,
        "request_interval_s": 1.0,
        "max_retries": 3,
    },
    "timeout": {"request_s": 20},
}


def write_cfg(tmp_path, data):
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


def test_load_ok(tmp_path):
    cfg = load_config(write_cfg(tmp_path, EXAMPLE))
    assert cfg["server"] == {"host": "127.0.0.1", "port": 5001}
    assert cfg["storage"]["data_dir"] == "./data"
    assert cfg["bilibili"]["page_size"] == 30
    assert cfg["timeout"]["request_s"] == 20


def test_example_file_is_loadable():
    """config.example.yaml 本身必须能直接作为 config.yaml 加载（契约：以 example 为 config 可正常启动）。"""
    example = Path(__file__).resolve().parent.parent / "config.example.yaml"
    cfg = load_config(example)
    assert cfg["server"]["host"] == "127.0.0.1"
    assert cfg["server"]["port"] == 5001
    assert cfg["storage"]["data_dir"] == "./data"


def test_defaults_filled_for_optional(tmp_path):
    minimal = {
        "server": {"host": "127.0.0.1", "port": 5001},
        "storage": {"data_dir": "./data"},
    }
    cfg = load_config(write_cfg(tmp_path, minimal))
    assert cfg["bilibili"] == {
        "cookie": "",
        "page_size": 30,
        "request_interval_s": 1.0,
        "max_retries": 3,
    }
    assert cfg["timeout"] == {"request_s": 20}


def test_missing_file_clear_error(tmp_path):
    with pytest.raises(ConfigError, match="配置文件缺失"):
        load_config(tmp_path / "nope.yaml")


def test_invalid_yaml(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("server: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="解析失败"):
        load_config(p)


def test_top_level_not_mapping(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="顶层必须是键值映射"):
        load_config(p)


@pytest.mark.parametrize(
    "mutate,expected",
    [
        (lambda d: d["server"].pop("host"), "server.host"),
        (lambda d: d["server"].pop("port"), "server.port"),
        (lambda d: d["server"].update(host=None), "server.host"),
        (lambda d: d["server"].update(port=""), "server.port"),
        (lambda d: d.pop("storage"), "storage.data_dir"),
        (lambda d: d["storage"].update(data_dir=""), "storage.data_dir"),
    ],
)
def test_missing_required_key(tmp_path, mutate, expected):
    data = copy.deepcopy(EXAMPLE)
    mutate(data)
    with pytest.raises(ConfigError, match=expected):
        load_config(write_cfg(tmp_path, data))


def test_non_mapping_section(tmp_path):
    data = copy.deepcopy(EXAMPLE)
    data["bilibili"] = "oops"
    with pytest.raises(ConfigError, match="bilibili 必须是映射"):
        load_config(write_cfg(tmp_path, data))
