"""PFLD 面部关键点 — ONNX 封装"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import onnxruntime

from models.base import BaseModel
from fusion.state import FaceLandmarks


class PFLDLandmarks(BaseModel):
    INPUT_SIZE = (112, 112)

    def load(self) -> None:
        self._session = onnxruntime.InferenceSession(
            str(self._model_path), providers=["CPUExecutionProvider"],
        )

    def __call__(self, bgr_face: np.ndarray) -> FaceLandmarks:
        img = cv2.cvtColor(bgr_face, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, (self.INPUT_SIZE[1], self.INPUT_SIZE[0]))
        img = img.astype(np.float32) / 127.5 - 1.0
        img = np.transpose(img, (2, 0, 1))[np.newaxis, ...]

        iname = self._session.get_inputs()[0].name
        out = self._session.run(None, {iname: img})[0]
        pts = out.squeeze().reshape(-1, 2)  # [106, 2] 归一化 [0,1]

        result = FaceLandmarks()
        h, w = bgr_face.shape[:2]
        result.points = [(float(p[0] * w), float(p[1] * h)) for p in pts]
        return result
