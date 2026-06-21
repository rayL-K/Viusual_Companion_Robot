"""YOLO ONNX → RKNN 模型导出工具。

量化时必须提供真实代表性图片列表，不能使用随机图片校准。
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def export_rknn(
    onnx_path: str,
    output_path: str,
    target_platform: str = "rk3588",
    quantize: bool = True,
    dataset_path: Optional[str] = None,
) -> None:
    """构建并导出 RKNN 模型。"""

    source = Path(onnx_path)
    if not source.is_file():
        raise FileNotFoundError(f"ONNX 模型不存在: {source}")

    dataset = None
    if quantize:
        if not dataset_path:
            raise ValueError("INT8 量化需要 --dataset 指向代表性图片列表")
        dataset = Path(dataset_path)
        if not dataset.is_file():
            raise FileNotFoundError(f"量化数据集列表不存在: {dataset}")

    try:
        from rknn.api import RKNN
    except ImportError:
        logger.error("需要 rknn-toolkit2，请从 RK3588 SDK 安装")
        raise

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    rknn = RKNN(verbose=False)
    try:
        rknn.config(
            target_platform=target_platform,
            quantize_algorithm="normal",
            quantized_dtype="asymmetric_quantized-8",
            batch_size=1,
        )

        logger.info("加载 ONNX 模型: %s", source)
        ret = rknn.load_onnx(model=str(source))
        if ret != 0:
            raise RuntimeError(f"ONNX 加载失败 (ret={ret})")

        logger.info("构建 RKNN%s ...", "（INT8）" if quantize else "")
        ret = rknn.build(do_quantization=quantize, dataset=str(dataset) if dataset else None)
        if ret != 0:
            raise RuntimeError(f"RKNN 构建失败 (ret={ret})")

        logger.info("导出 RKNN: %s", output)
        ret = rknn.export_rknn(export_path=str(output))
        if ret != 0:
            raise RuntimeError(f"导出失败 (ret={ret})")
    finally:
        rknn.release()
    logger.info("导出完成: %s", output)


def main() -> None:
    parser = argparse.ArgumentParser(description="YOLO ONNX → RKNN 导出")
    parser.add_argument("--onnx", required=True, help="ONNX 模型路径")
    parser.add_argument("--output", default="models/yolo/yolov26n.rknn", help="输出 RKNN 路径")
    parser.add_argument("--target", default="rk3588", help="NPU 平台")
    parser.add_argument("--dataset", help="INT8 量化校准图片列表，每行一个图片路径")
    parser.add_argument("--no-quantize", action="store_true", help="跳过 INT8 量化")
    args = parser.parse_args()

    export_rknn(
        onnx_path=args.onnx,
        output_path=args.output,
        target_platform=args.target,
        quantize=not args.no_quantize,
        dataset_path=args.dataset,
    )


if __name__ == "__main__":
    main()
