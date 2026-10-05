"""配置加载：config.yaml → 校验后的 dict（契约见 TASKS.md 契约总览）。

    load_config(path=None) -> dict
    - 缺文件 / 解析失败 / 顶层非映射 / 缺必填项（server.host、server.port、
      storage.data_dir）→ 抛 ConfigError（清晰消息）
    - 可选项按 DEFAULTS 补全
    - config.yaml 已 gitignore（可含 Cookie 等敏感信息）；config.example.yaml 入库
"""
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"

#: 必填配置项，缺失或为空则拒绝启动
REQUIRED_KEYS = (("server", "host"), ("server", "port"), ("storage", "data_dir"))

#: 可选项默认值（缺省时补全）
DEFAULTS = {
    "bilibili": {"cookie": "", "page_size": 30, "request_interval_s": 1.0, "max_retries": 3},
    "timeout": {"request_s": 20},
}


class ConfigError(Exception):
    """配置缺失或非法。"""


def load_config(path=None):
    """加载并校验 config.yaml。

    - 文件缺失 / YAML 解析失败 / 必填项缺失 → 抛 ConfigError
    - 可选项按 DEFAULTS 补全
    """
    path = Path(path) if path else CONFIG_PATH
    if not path.exists():
        raise ConfigError(
            f"配置文件缺失: {path}（复制 config.example.yaml 为 config.yaml 并填写必填项）"
        )
    try:
        with path.open(encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"config.yaml 解析失败: {e}")
    if not isinstance(cfg, dict):
        raise ConfigError("config.yaml 顶层必须是键值映射")

    for section, values in DEFAULTS.items():
        node = cfg.setdefault(section, {})
        if not isinstance(node, dict):
            raise ConfigError(f"config.yaml 的 {section} 必须是映射")
        for k, v in values.items():
            node.setdefault(k, v)

    for keys in REQUIRED_KEYS:
        node = cfg
        for k in keys:
            if not isinstance(node, dict) or node.get(k) in (None, ""):
                raise ConfigError(f"config.yaml 缺少必填项: {'.'.join(keys)}")
            node = node[k]

    return cfg


def ensure_dirs(cfg):
    """启动时自动创建 data_dir（snapshot 根目录，结构 data/<mid>/）。"""
    Path(cfg["storage"]["data_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
