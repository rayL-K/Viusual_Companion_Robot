"""人脸检测 — OpenCV Haar Cascade（零下载，opencv-python 自带）"""
from __future__ import annotations

import cv2

from fusion.state import FaceInfo


class SCRFDDetector:
    """使用 OpenCV 内置 Haar Cascade 做初筛人脸检测。

    适用于没有 GPU 的板端场景，模型文件随 opencv-python 一起安装。
    """

    def __init__(self, model_path: str = "") -> None:
        """初始化检测器，不立即加载分类器。"""
        self._cascade = None

    def load(self) -> None:
        """加载 OpenCV Haar 级联分类器。"""
        path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self._cascade = cv2.CascadeClassifier(path)

    def __call__(self, bgr_frame):
        """对 BGR 图像执行人脸检测。

        Returns:
            FaceInfo 对象列表，未检测到人脸时返回空列表。
        """
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
