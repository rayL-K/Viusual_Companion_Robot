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


# ── 后端配置 ──────────────────────────────────────────────────────

@dataclass
class BackendConfig:
    """每个模块的后端选择。"""

    llm: str = "cloud"          # cloud / local
    vision: str = "cloud"       # cloud / local
    asr: str = "local"
    tts: str = "local"
    vad: str = "local"

    VALID_BACKENDS = {"cloud", "local"}

    @classmethod
    def from_mapping(cls, data: Mapping[str, str]) -> "BackendConfig":
        def _valid(key: str, fallback: str) -> str:
            value = data.get(key, fallback)
            if value not in cls.VALID_BACKENDS:
                raise ConfigError(f"后端 `{key}` 值 `{value}` 无效，须为 cloud/local")
            return value
        return cls(
            llm=_valid("llm", "cloud"),
            vision=_valid("vision", "cloud"),
            asr=_valid("asr", "local"),
            tts=_valid("tts", "local"),
            vad=_valid("vad", "local"),
        )


# ── NPU 配置 ──────────────────────────────────────────────────────

@dataclass
class NpuConfig:
    """RK3588 NPU 配置。"""

    target: str = "rk3588"
    core_mask: int = 0


# ── 模型路径配置 ──────────────────────────────────────────────────

@dataclass
class ModelPaths:
    """本地模型文件路径（相对 main/ 目录）。"""

    yolo: str = "models/yolo/yolov26n.rknn"
    llm: str = "models/qwen/Qwen2.5-1.5B-Q4_K_M.gguf"
    vision_llm: str = "models/qwen/Qwen2.5-0.5B-Q4_K_M.gguf"
    onnx: str = "models/onnx/"

    @classmethod
    def from_mapping(cls, data: Mapping[str, str]) -> "ModelPaths":
        return cls(
            yolo=str(data.get("yolo", cls.yolo)),
            llm=str(data.get("llm", cls.llm)),
            vision_llm=str(data.get("vision_llm", cls.vision_llm)),
            onnx=str(data.get("onnx", cls.onnx)),
        )

    def resolve_yolo(self) -> Path:
        return resolve_main_path(self.yolo)

    def resolve_llm(self) -> Path:
        return resolve_main_path(self.llm)

    def resolve_vision_llm(self) -> Path:
        return resolve_main_path(self.vision_llm)

    def resolve_onnx_dir(self) -> Path:
        return resolve_main_path(self.onnx)


# ── Live2D 配置 ───────────────────────────────────────────────────

@dataclass
class Live2DDisplayConfig:
    """Live2D 显示模块配置。"""

    enabled: bool
    model_name: str
    model_path: Path
    manifest_path: Path


# ── 应用配置 ──────────────────────────────────────────────────────

@dataclass
class AppConfig:
    """板端应用的结构化配置。"""

    app_name: str
    mode: str
    display: str
    log_level: str
    backend: BackendConfig
    model_paths: ModelPaths
    npu: NpuConfig
    live2d_display: Live2DDisplayConfig
    modules: Dict[str, Dict[str, Any]] = field(default_factory=dict)


# ── 路径工具 ──────────────────────────────────────────────────────

def resolve_project_path(relative_path: str) -> Path:
    return PROJECT_ROOT / relative_path


def resolve_main_path(relative_path: str) -> Path:
    return MAIN_ROOT / relative_path


# ── 加载器 ───────────────────────────────────────────────────────

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
    backend = BackendConfig.from_mapping(data.get("backend", {}))
    model_paths = ModelPaths.from_mapping(data.get("model_paths", {}))
    npu_raw = data.get("npu", {})
    npu = NpuConfig(
        target=str(npu_raw.get("target", "rk3588")),
        core_mask=int(npu_raw.get("core_mask", 0)),
    )
    modules = require_mapping(data, "modules")
    live2d = require_mapping(modules, "live2d_display")

    live2d_config = Live2DDisplayConfig(
        enabled=require_bool(live2d, "enabled"),
        model_name=require_string(live2d, "model_name"),
        model_path=require_existing_main_file(
            require_string(live2d, "model_path"),
            "modules.live2d_display.model_path",
        ),
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
        backend=backend,
        model_paths=model_paths,
        npu=npu,
        modules=dict(modules),
        live2d_display=live2d_config,
    )


# ── 校验工具 ─────────────────────────────────────────────────────

def require_mapping(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"配置项 `{key}` 必须是对象")
    return value


def require_string(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"配置项 `{key}` 必须是非空字符串")
    return value


def require_bool(data: Mapping[str, Any], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise ConfigError(f"配置项 `{key}` 必须是布尔值")
    return value


def require_existing_main_file(relative_path: str, label: str) -> Path:
    path = resolve_main_path(relative_path).resolve()
    try:
        path.relative_to(MAIN_ROOT.resolve())
    except ValueError:
        raise ConfigError(f"配置项 `{label}` 不能指向 main 目录外部：{relative_path}")
    if not path.is_file():
        raise ConfigError(f"配置项 `{label}` 指向的文件不存在：{path}")
    return path


def empty_config() -> Dict[str, Any]:
    return {"app": {"name": "visual_companion_robot"}}
