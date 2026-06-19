"""YOLO ONNX → RKNN 模型导出脚本。

在 RK3588 SDK 环境中运行：
  python tools/export_yolo_rknn.py --onnx models/yolo/yolov26n.onnx --output models/yolo/yolov26n.rknn

在开发机（无 NPU）上可用 --cpu-fallback 测试 ONNX 路径。
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# YOLO26n 默认输入尺寸
INPUT_SIZE = (640, 640)


def export_rknn(
    onnx_path: str,
    output_path: str,
    target_platform: str = "rk3588",
    quantize: bool = True,
) -> None:
    """将 YOLO ONNX 模型转换为 RKNN 格式。

    Args:
        onnx_path: 输入 ONNX 模型路径。
        output_path: 输出 RKNN 模型路径。
        target_platform: 目标 NPU 平台。
        quantize: 是否量化（INT8）。
    """

    onnx_path = Path(onnx_path)
    if not onnx_path.is_file():
        raise FileNotFoundError(f"ONNX 模型不存在: {onnx_path}")

    try:
        from rknn.api import RKNN
    except ImportError:
        logger.error("需要 rknn-toolkit2，请从 RK3588 SDK 安装")
        raise

    rknn = RKNN(verbose=False)

    logger.info("配置 RKNN ...")
    rknn.config(
        target_platform=target_platform,
        quantize_algorithm="normal",
        quantized_dtype="asymmetric_quantized-8",
        batch_size=1,
    )

    logger.info("加载 ONNX 模型: %s", onnx_path)
    ret = rknn.load_onnx(model=str(onnx_path), inputs=["images"], outputs=["output0"], input_size_list=[INPUT_SIZE])
    if ret != 0:
        raise RuntimeError(f"ONNX 加载失败 (ret={ret})")

    if quantize:
        logger.info("INT8 量化 ...")
        dataset = _generate_dummy_dataset(onnx_path.parent)
        ret = rknn.quantize(dataset=str(dataset), rknn_batch_size=1)
        if ret != 0:
            raise RuntimeError(f"量化失败 (ret={ret})")

    logger.info("导出 RKNN: %s", output_path)
    ret = rknn.export_rknn(output_path=str(output_path))
    if ret != 0:
        raise RuntimeError(f"导出失败 (ret={ret})")

    rknn.release()
    logger.info("导出完成: %s", output_path)


def _generate_dummy_dataset(output_dir: Path) -> Path:
    """生成用于量化的虚拟数据集（一张随机图像）。"""

    import cv2
    import numpy as np

    dataset_path = output_dir / "quant_dataset.txt"
    dummy_img = output_dir / "dummy_640.jpg"

    if not dummy_img.is_file():
        fake = np.random.randint(0, 256, (640, 640, 3), dtype=np.uint8)
        cv2.imwrite(str(dummy_img), fake)

    with open(dataset_path, "w") as f:
        f.write(str(dummy_img) + "\n")

    return dataset_path


def main() -> None:
    parser = argparse.ArgumentParser(description="YOLO ONNX → RKNN 导出")
    parser.add_argument("--onnx", required=True, help="ONNX 模型路径")
    parser.add_argument("--output", default="models/yolo/yolov26n.rknn", help="输出 RKNN 路径")
    parser.add_argument("--target", default="rk3588", help="NPU 平台")
    parser.add_argument("--no-quantize", action="store_true", help="跳过量化")
    args = parser.parse_args()

    export_rknn(
        onnx_path=args.onnx,
        output_path=args.output,
        target_platform=args.target,
        quantize=not args.no_quantize,
    )


if __name__ == "__main__":
    main()
