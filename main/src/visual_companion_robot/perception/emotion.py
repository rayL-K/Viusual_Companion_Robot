"""FER+ 情绪识别 — ONNX 轻量人脸情绪分类。

模型: Microsoft ONNX Model Zoo (emotion-ferplus-8)
输入: 64×64 灰度 → 8 类情绪概率
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

import numpy as np

from visual_companion_robot.integrations.model_runtime import OnnxEngine

logger = logging.getLogger(__name__)

FERPLUS_LABELS = ["neutral", "happiness", "surprise", "sadness", "anger", "disgust", "fear", "contempt"]

EMOTION_MAP = {
    "neutral": "neutral", "happiness": "happy", "surprise": "surprise",
    "sadness": "sad", "anger": "angry", "disgust": "angry",
    "fear": "surprise", "contempt": "neutral",
}

DEFAULT_MODEL_PATH = "main/models/emotion/emotion-ferplus-8.onnx"


@dataclass
class EmotionResult:
    emotion: str
    confidence: float
    full_scores: Dict[str, float] = field(default_factory=dict)


class FerPlusEmotionRecognizer:
    def __init__(self, model_path: str = DEFAULT_MODEL_PATH) -> None:
        self._model_path = model_path
        self._engine: Optional[OnnxEngine] = None

    def load(self) -> None:
        path = Path(self._model_path)
        if not path.is_file():
            raise FileNotFoundError(f"FER+ 模型文件不存在: {path}")
        self._engine = OnnxEngine()
        self._engine.load(str(path))
        logger.info("FER+ 情绪模型已加载: %s", path.name)

    def is_loaded(self) -> bool:
        return self._engine is not None and self._engine.is_loaded()

    def classify(self, face_patch: np.ndarray) -> EmotionResult:
        if self._engine is None:
            raise RuntimeError("FER+ 模型未加载，请先调用 load()")

        input_tensor = self._preprocess(face_patch)
        outputs = self._engine.run(
            output_names=[],
            input_feed={self._engine._session.get_inputs()[0].name: input_tensor},
        )

        scores = outputs[0][0]
        probs = self._softmax(scores)
        full_scores = {FERPLUS_LABELS[i]: float(probs[i]) for i in range(len(FERPLUS_LABELS))}

        best_idx = int(np.argmax(probs))
        raw_emotion = FERPLUS_LABELS[best_idx]
        return EmotionResult(
            emotion=EMOTION_MAP.get(raw_emotion, "neutral"),
            confidence=float(probs[best_idx]),
            full_scores=full_scores,
        )

    @staticmethod
    def _preprocess(face_patch: np.ndarray) -> np.ndarray:
        import cv2
        gray = cv2.cvtColor(face_patch, cv2.COLOR_BGR2GRAY) if face_patch.ndim == 3 else face_patch
        resized = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA)
        return resized.astype(np.float32)[np.newaxis, np.newaxis, :, :] / 255.0

    @staticmethod
    def _softmax(scores: np.ndarray) -> np.ndarray:
        exp = np.exp(scores - np.max(scores))
        return exp / np.sum(exp)
