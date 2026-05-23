"""MoveNet 身体姿态 — TFLite 封装"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from models.base import BaseModel
from fusion.state import BodyKeypoints


class MoveNetPose(BaseModel):
    INPUT_SIZE = (192, 192)

    def load(self) -> None:
        import tflite_runtime.interpreter as tflite
        self._interp = tflite.Interpreter(model_path=str(self._model_path))
        self._interp.allocate_tensors()
        self._inp = self._interp.get_input_details()[0]
        self._out = self._interp.get_output_details()[0]

    def __call__(self, bgr_frame: np.ndarray) -> BodyKeypoints:
        img = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, (self.INPUT_SIZE[1], self.INPUT_SIZE[0]))
        img = img.astype(np.float32)[np.newaxis, ...] / 255.0

        self._interp.set_tensor(self._inp["index"], img)
        self._interp.invoke()
        kps = self._interp.get_tensor(self._out["index"]).squeeze()

        result = BodyKeypoints()
        for i in range(min(17, len(kps))):
            y, x, conf = kps[i]
            result.points.append((float(x), float(y), float(conf)))
        return result
