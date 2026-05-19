"""Python 版本兼容性检查脚本。

项目最终运行在 Firefly/RK3588 上，而当前 Firefly 系统自带 Python 3.8。
Windows 本机可能安装了更新版本的 Python，所以本脚本用于在本地提前检查
源码是否仍符合 Python 3.8 语法，避免代码在本机能跑、上板后导入失败。
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGET_VERSION = "3.8"
DEFAULT_SCAN_PATHS = [
    PROJECT_ROOT / "main" / "app.py",
    PROJECT_ROOT / "main" / "scripts",
    PROJECT_ROOT / "main" / "src",
]


def parse_version(value: str) -> Tuple[int, int]:
    """把 `3.8` 这类版本字符串转换为 `(3, 8)`。"""

    parts = value.strip().split(".")
    if len(parts) < 2:
        raise ValueError(f"版本号必须包含主版本和次版本：{value}")
    return int(parts[0]), int(parts[1])


def iter_python_files(paths: Sequence[Path]) -> Iterable[Path]:
    """遍历待检查路径下的 Python 文件。"""

    for path in paths:
        resolved = path.resolve()
        if resolved.is_file() and resolved.suffix == ".py":
            yield resolved
        elif resolved.is_dir():
            for child in sorted(resolved.rglob("*.py")):
                if "__pycache__" not in child.parts:
                    yield child


def parse_with_target_grammar(source: str, path: Path, target_version: Tuple[int, int]) -> None:
    """用目标 Python 语法解析源码。

    新版 Python 支持 `feature_version` 参数，可以用新解释器模拟旧语法。
    如果脚本正好运行在 Python 3.8 上，则退回普通解析，本身就是目标语法。
    """

    try:
        ast.parse(source, filename=str(path), feature_version=target_version)
    except TypeError:
        ast.parse(source, filename=str(path))


def check_files(paths: Sequence[Path], target_version: Tuple[int, int]) -> List[str]:
    """检查所有 Python 文件，并返回错误列表。"""

    errors: List[str] = []
    for path in iter_python_files(paths):
        try:
            source = path.read_text(encoding="utf-8")
            parse_with_target_grammar(source, path, target_version)
        except SyntaxError as exc:
            errors.append(f"{path}:{exc.lineno}: {exc.msg}")
        except UnicodeDecodeError as exc:
            errors.append(f"{path}: 文件不是 UTF-8 编码（{exc}）")
    return errors


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(description="检查源码是否兼容指定 Python 语法版本。")
    parser.add_argument("--target", default=DEFAULT_TARGET_VERSION, help="目标 Python 版本，默认 3.8")
    parser.add_argument("paths", nargs="*", type=Path, help="可选的检查路径")
    return parser.parse_args()


def main() -> int:
    """脚本入口。"""

    args = parse_args()
    target_version = parse_version(args.target)
    paths = [path if path.is_absolute() else PROJECT_ROOT / path for path in args.paths]
    if not paths:
        paths = DEFAULT_SCAN_PATHS

    errors = check_files(paths, target_version)

    print("=== Python 版本兼容性检查 ===")
    print(f"当前解释器：Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    print(f"目标语法：  Python {target_version[0]}.{target_version[1]}")
    print(f"检查路径：  {len(paths)} 个入口")

    if errors:
        print("\n发现不兼容源码：")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("\n源码语法兼容目标 Python 版本。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
