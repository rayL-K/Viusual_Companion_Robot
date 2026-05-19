"""配置加载模块。

配置文件是板端程序的第一个共享控制点。后续摄像头、语音、模型推理和
Live2D 显示都应从这里读取路径和开关，避免业务模块各自硬编码资源位置。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[4]
MAIN_ROOT = PROJECT_ROOT / "main"
DEFAULT_CONFIG_PATH = MAIN_ROOT / "config" / "app.yaml"


class ConfigError(ValueError):
    """配置文件内容不符合程序要求。"""


@dataclass
class Live2DDisplayConfig:
    """Live2D 显示模块配置。"""

    enabled: bool
    model_name: str
    model_path: Path
    manifest_path: Path


@dataclass
class AppConfig:
    """板端应用的结构化配置。"""

    app_name: str
    mode: str
    display: str
    log_level: str
    live2d_display: Live2DDisplayConfig
    modules: Dict[str, Dict[str, Any]] = field(default_factory=dict)


def resolve_project_path(relative_path: str) -> Path:
    """把相对项目根目录的路径转换为绝对路径。"""

    return PROJECT_ROOT / relative_path


def resolve_main_path(relative_path: str) -> Path:
    """把相对 `main/` 目录的路径转换为绝对路径。"""

    return MAIN_ROOT / relative_path


def load_raw_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """读取 YAML 配置文件并返回原始字典。"""

    path = config_path or DEFAULT_CONFIG_PATH
    if not path.is_file():
        raise ConfigError(f"配置文件不存在：{path}")

    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise ConfigError(f"配置文件顶层必须是对象：{path}")
    return data


def load_app_config(config_path: Optional[Path] = None) -> AppConfig:
    """读取并校验板端应用配置。"""

    data = load_raw_config(config_path)
    app = require_mapping(data, "app")
    runtime = require_mapping(data, "runtime")
    modules = require_mapping(data, "modules")
    live2d = require_mapping(modules, "live2d_display")

    live2d_config = Live2DDisplayConfig(
        enabled=require_bool(live2d, "enabled"),
        model_name=require_string(live2d, "model_name"),
        model_path=require_existing_main_file(require_string(live2d, "model_path"), "modules.live2d_display.model_path"),
        manifest_path=require_existing_main_file(
            require_string(live2d, "manifest_path"),
            "modules.live2d_display.manifest_path",
        ),
    )

    return AppConfig(
        app_name=require_string(app, "name"),
        mode=require_string(app, "mode"),
        display=require_string(runtime, "display"),
        log_level=require_string(runtime, "log_level"),
        modules=dict(modules),
        live2d_display=live2d_config,
    )


def require_mapping(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    """读取对象字段，并要求该字段仍是对象。"""

    value = data.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"配置项 `{key}` 必须是对象")
    return value


def require_string(data: Mapping[str, Any], key: str) -> str:
    """读取非空字符串配置项。"""

    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"配置项 `{key}` 必须是非空字符串")
    return value


def require_bool(data: Mapping[str, Any], key: str) -> bool:
    """读取布尔配置项。"""

    value = data.get(key)
    if not isinstance(value, bool):
        raise ConfigError(f"配置项 `{key}` 必须是布尔值")
    return value


def require_existing_main_file(relative_path: str, label: str) -> Path:
    """读取相对 `main/` 的文件路径，并确认文件存在。"""

    path = resolve_main_path(relative_path).resolve()
    try:
        path.relative_to(MAIN_ROOT.resolve())
    except ValueError:
        raise ConfigError(f"配置项 `{label}` 不能指向 main 目录外部：{relative_path}")
    if not path.is_file():
        raise ConfigError(f"配置项 `{label}` 指向的文件不存在：{path}")
    return path


def empty_config() -> Dict[str, Any]:
    """返回一个最小可用配置，供早期测试和单元测试使用。"""

    return {"app": {"name": "visual_companion_robot"}}

