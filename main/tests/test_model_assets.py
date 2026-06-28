from __future__ import annotations

import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from visual_companion_robot.integrations.model_assets import extract_tar_safely


def archive_with(member: tarfile.TarInfo, content: bytes = b"") -> tarfile.TarFile:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:bz2") as archive:
        archive.addfile(member, io.BytesIO(content) if member.isfile() else None)
    buffer.seek(0)
    return tarfile.open(fileobj=buffer, mode="r:bz2")


class ModelAssetTests(unittest.TestCase):
    def test_regular_model_file_is_extracted(self) -> None:
        member = tarfile.TarInfo("model/tokens.txt")
        member.size = 6
        with tempfile.TemporaryDirectory() as temp_dir, archive_with(member, b"token\n") as archive:
            extract_tar_safely(archive, Path(temp_dir))
            self.assertEqual((Path(temp_dir) / "model" / "tokens.txt").read_text(), "token\n")

    def test_parent_traversal_is_rejected(self) -> None:
        member = tarfile.TarInfo("../outside.txt")
        member.size = 1
        with tempfile.TemporaryDirectory() as temp_dir, archive_with(member, b"x") as archive:
            with self.assertRaisesRegex(RuntimeError, "越界路径"):
                extract_tar_safely(archive, Path(temp_dir))

    def test_symbolic_link_is_rejected(self) -> None:
        member = tarfile.TarInfo("model/link")
        member.type = tarfile.SYMTYPE
        member.linkname = "../outside"
        with tempfile.TemporaryDirectory() as temp_dir, archive_with(member) as archive:
            with self.assertRaisesRegex(RuntimeError, "特殊文件"):
                extract_tar_safely(archive, Path(temp_dir))


if __name__ == "__main__":
    unittest.main()
