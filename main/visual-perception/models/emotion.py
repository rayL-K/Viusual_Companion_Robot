"""Mini-Xception 情绪 — ONNX 封装"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import onnxruntime

from models.base import BaseModel
from fusion.state import Emotion

EMO_LABELS = ["angry", "disgust", "fear", "happy", "sad", "surprise", "neutral"]


class MiniXceptionEmotion(BaseModel):
    INPUT_SIZE = (48, 48)

    def load(self) -> None:
        self._session = onnxruntime.InferenceSession(
            str(self._model_path), providers=["CPUExecutionProvider"],
        )

    def __call__(self, bgr_face: np.ndarray) -> Emotion:
        gray = cv2.cvtColor(bgr_face, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (self.INPUT_SIZE[1], self.INPUT_SIZE[0]))
        img = gray.astype(np.float32)[np.newaxis, np.newaxis, ...] / 255.0

        iname = self._session.get_inputs()[0].name
        out = self._session.run(None, {iname: img})[0]
        probs = np.exp(out - np.max(out))
        probs = probs.squeeze() / (probs.sum() + 1e-10)

        result = Emotion()
        for i, label in enumerate(EMO_LABELS):
            result.scores[label] = float(probs[i])
        result.dominant = EMO_LABELS[int(np.argmax(probs))]
        return result
