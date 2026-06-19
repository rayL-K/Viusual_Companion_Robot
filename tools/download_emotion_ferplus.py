"""下载 FER+ ONNX 情绪识别模型。

用法:
  python tools/download_emotion_ferplus.py

模型来源: Microsoft ONNX Model Zoo
"""

from __future__ import annotations

import logging
import urllib.request
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_DIR = Path("main/models/emotion")
MODEL_URL = "https://github.com/onnx/models/raw/main/validated/vision/body_analysis/emotion_ferplus/model/emotion-ferplus-8.onnx"
MODEL_FILENAME = "emotion-ferplus-8.onnx"


def download_model() -> Path:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODEL_DIR / MODEL_FILENAME

    if model_path.is_file():
        size_mb = model_path.stat().st_size / (1024 * 1024)
        logger.info("模型已存在: %s (%.1f MB)", model_path, size_mb)
        return model_path

    logger.info("正在下载 FER+ 模型 (%s) ...", MODEL_URL)
    urllib.request.urlretrieve(MODEL_URL, model_path)
    size_mb = model_path.stat().st_size / (1024 * 1024)
    logger.info("下载完成: %s (%.1f MB)", model_path, size_mb)
    return model_path


if __name__ == "__main__":
    download_model()
