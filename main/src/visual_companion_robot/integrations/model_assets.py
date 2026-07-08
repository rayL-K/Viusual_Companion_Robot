"""模型压缩包下载与安全解压。"""

from __future__ import annotations

import tarfile
import tempfile
import urllib.request
from pathlib import Path


def download_tar_bz2(url: str, target_dir: Path) -> None:
    """下载 tar.bz2 模型包并安全解压到目标目录。"""

    target_dir.mkdir(parents=True, exist_ok=True)
    archive_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".tar.bz2", delete=False) as archive:
            archive_path = archive.name
        urllib.request.urlretrieve(url, archive_path)
        with tarfile.open(archive_path, "r:bz2") as bundle:
            extract_tar_safely(bundle, target_dir)
    finally:
        if archive_path:
            Path(archive_path).unlink(missing_ok=True)


def extract_tar_safely(bundle: tarfile.TarFile, target_dir: Path) -> None:
    """只允许普通文件和目录，拒绝链接、设备文件与越界路径。"""

    target_root = target_dir.resolve()
    for member in bundle.getmembers():
        if not (member.isfile() or member.isdir()):
            raise RuntimeError(f"模型压缩包含不安全的特殊文件: {member.name}")
        target = (target_root / member.name).resolve()
        if not target.is_relative_to(target_root):
            raise RuntimeError(f"模型压缩包包含越界路径: {member.name}")
    bundle.extractall(path=target_root)
