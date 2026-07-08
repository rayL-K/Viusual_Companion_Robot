from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.export_yolo_rknn import export_rknn


class FakeRknn:
    instance = None

    def __init__(self, verbose: bool) -> None:
        self.calls = []
        FakeRknn.instance = self

    def config(self, **kwargs) -> None:
        self.calls.append(("config", kwargs))

    def load_onnx(self, **kwargs) -> int:
        self.calls.append(("load_onnx", kwargs))
        return 0

    def build(self, **kwargs) -> int:
        self.calls.append(("build", kwargs))
        return 0

    def export_rknn(self, **kwargs) -> int:
        self.calls.append(("export_rknn", kwargs))
        return 0

    def release(self) -> None:
        self.calls.append(("release", {}))


class ExportYoloRknnTests(unittest.TestCase):
    def test_quantized_export_uses_build_with_real_dataset(self) -> None:
        api_module = types.ModuleType("rknn.api")
        api_module.RKNN = FakeRknn  # type: ignore[attr-defined]
        package = types.ModuleType("rknn")
        package.api = api_module  # type: ignore[attr-defined]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model = root / "model.onnx"
            dataset = root / "dataset.txt"
            model.write_bytes(b"onnx")
            dataset.write_text("frame.jpg\n", encoding="utf-8")
            output = root / "out" / "model.rknn"

            with patch.dict(sys.modules, {"rknn": package, "rknn.api": api_module}):
                export_rknn(str(model), str(output), dataset_path=str(dataset))

        calls = dict(FakeRknn.instance.calls)
        self.assertEqual(calls["load_onnx"], {"model": str(model)})
        self.assertEqual(calls["build"], {"do_quantization": True, "dataset": str(dataset)})
        self.assertEqual(calls["export_rknn"], {"export_path": str(output)})
        self.assertEqual(FakeRknn.instance.calls[-1][0], "release")

    def test_quantized_export_requires_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            model = Path(temp_dir) / "model.onnx"
            model.write_bytes(b"onnx")
            with self.assertRaisesRegex(ValueError, "--dataset"):
                export_rknn(str(model), str(Path(temp_dir) / "model.rknn"))


if __name__ == "__main__":
    unittest.main()
