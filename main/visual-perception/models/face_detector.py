"""人脸检测 — OpenCV Haar Cascade（零下载，opencv-python 自带）"""
from __future__ import annotations

import cv2

from fusion.state import FaceInfo


class SCRFDDetector:
    """使用 OpenCV 内置 Haar Cascade 做初筛。"""

    def __init__(self, model_path: str = "") -> None:
        self._cascade = None

    def load(self) -> None:
        path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self._cascade = cv2.CascadeClassifier(path)

    def __call__(self, bgr_frame):
        if self._cascade is None:
            return []
        gray = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2GRAY)
        faces = self._cascade.detectMultiScale(gray, 1.1, 3, minSize=(80, 80))
        h, w = bgr_frame.shape[:2]
        results = []
        for (x, y, bw, bh) in faces:
            results.append(FaceInfo(
                detected=True,
                bbox=(x / w, y / h, bw / w, bh / h),
                confidence=1.0,
            ))
        return results
