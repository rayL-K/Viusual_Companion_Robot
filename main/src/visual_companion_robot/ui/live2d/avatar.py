"""Live2D 角色资源描述与清单加载。

该模块是 Live2D 资源的共享入口。业务代码只关心角色名、表情名和动作名，
不应直接拼接资源路径；具体文件位置统一由 `manifest.json` 解析得到。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


class Live2DAssetError(ValueError):
    """Live2D 资源清单或文件结构不符合要求。"""


@dataclass
class Live2DAvatar:
    """一个 Live2D 角色资源包。"""

    name: str
    root_dir: Path
    model3_path: Path
    expressions: Dict[str, Path] = field(default_factory=dict)
    motions: Dict[str, Path] = field(default_factory=dict)

    def expression_path(self, name: str) -> Path:
        """按稳定名称取得表情文件路径。"""

        return require_named_asset(self.expressions, name, "表情")

    def motion_path(self, name: str) -> Path:
        """按稳定名称取得动作文件路径。"""

        return require_named_asset(self.motions, name, "动作")


def load_live2d_avatar(
    manifest_path: Path,
    expected_name: Optional[str] = None,
    expected_model3_path: Optional[Path] = None,
) -> Live2DAvatar:
    """从 `manifest.json` 加载 Live2D 角色资源。"""

    manifest_file = manifest_path.resolve()
    root_dir = manifest_file.parent
    manifest = load_json_object(manifest_file, "manifest")

    name = require_string(manifest, "name", "manifest.name")
    if expected_name is not None and name != expected_name:
        raise Live2DAssetError(f"Live2D 模型名不一致：配置为 {expected_name}，清单为 {name}")

    model3_path = resolve_asset_file(root_dir, require_string(manifest, "model3", "manifest.model3"), "manifest.model3")
    if expected_model3_path is not None and model3_path != expected_model3_path.resolve():
        raise Live2DAssetError(f"Live2D model3 路径不一致：配置为 {expected_model3_path}，清单为 {model3_path}")

    expressions = load_named_assets(root_dir, require_mapping(manifest, "expressions", "manifest.expressions"), "表情")
    motions = load_named_assets(root_dir, require_mapping(manifest, "motions", "manifest.motions"), "动作")

    return Live2DAvatar(
        name=name,
        root_dir=root_dir,
        model3_path=model3_path,
        expressions=expressions,
        motions=motions,
    )


def load_json_object(path: Path, label: str) -> Dict[str, Any]:
    """读取 JSON 文件，并要求顶层结构是对象。"""

    if not path.is_file():
        raise Live2DAssetError(f"{label} 文件不存在：{path}")
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise Live2DAssetError(f"{label} 顶层必须是对象：{path}")
    return data


def load_named_assets(root_dir: Path, assets: Mapping[str, Any], label: str) -> Dict[str, Path]:
    """加载表情或动作映射，并校验每个资源文件都存在。"""

    loaded: Dict[str, Path] = {}
    for name, relative_path in assets.items():
        if not isinstance(name, str) or not name.strip():
            raise Live2DAssetError(f"{label}名称必须是非空字符串：{name!r}")
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise Live2DAssetError(f"{label} `{name}` 的路径必须是非空字符串")
        loaded[name] = resolve_asset_file(root_dir, relative_path, f"{label} `{name}`")
    return loaded


def resolve_asset_file(root_dir: Path, relative_path: str, label: str) -> Path:
    """把清单中的相对路径解析成模型目录内的真实文件。"""

    path = (root_dir / relative_path).resolve()
    try:
        path.relative_to(root_dir.resolve())
    except ValueError:
        raise Live2DAssetError(f"{label} 不能指向模型目录外部：{relative_path}")
    if not path.is_file():
        raise Live2DAssetError(f"{label} 文件不存在：{path}")
    return path


def require_mapping(data: Mapping[str, Any], key: str, label: str) -> Mapping[str, Any]:
    """读取对象字段，并要求该字段仍是对象。"""

    value = data.get(key)
    if not isinstance(value, dict) or not value:
        raise Live2DAssetError(f"{label} 必须是非空对象")
    return value


def require_string(data: Mapping[str, Any], key: str, label: str) -> str:
    """读取非空字符串字段。"""

    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise Live2DAssetError(f"{label} 必须是非空字符串")
    return value


def require_named_asset(assets: Mapping[str, Path], name: str, label: str) -> Path:
    """按名称读取已经校验过的资源路径。"""

    try:
        return assets[name]
    except KeyError:
        available = ", ".join(sorted(assets))
        raise Live2DAssetError(f"未知{label}：{name}。可用{label}：{available}")

