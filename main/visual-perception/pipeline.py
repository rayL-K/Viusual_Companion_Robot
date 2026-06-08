"""视觉感知主管线 — 基于 MediaPipe FaceLandmarker"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from pathlib import Path

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

logger = logging.getLogger(__name__)
_HERE = Path(__file__).parent
_MODEL_PATH = str(_HERE / "models" / "weights" / "face_landmarker.task")


class PerceptionPipeline:
    def __init__(self):
        self._camera_id = 0
        self._cap = None
        self._streaming = False
        self._broadcast_fn = None

        options = vision.FaceLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=_MODEL_PATH),
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=False,
            num_faces=1,
        )
        self._detector = vision.FaceLandmarker.create_from_options(options)

    def set_broadcast(self, fn) -> None:
        self._broadcast_fn = fn

    async def handle_command(self, cmd: dict) -> None:
        if cmd.get("cmd") == "start":
            await self._start_stream()
        elif cmd.get("cmd") == "stop":
            await self._stop_stream()

    async def _start_stream(self) -> None:
        if self._streaming:
            return
        # 尝试多个摄像头索引
        for cam_id in range(3):
            cap = cv2.VideoCapture(cam_id)
            if cap.isOpened():
                self._camera_id = cam_id
                self._cap = cap
                break
            cap.release()

        if not self._cap:
            logger.error("无法打开任何摄像头 (0-2)")
            if self._broadcast_fn:
                self._broadcast_fn({"error": "camera_not_found"})
            return

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self._streaming = True
        logger.info("感知已启动 (摄像头 #%d)", self._camera_id)
        asyncio.get_event_loop().create_task(self._inference_loop())

    async def _stop_stream(self) -> None:
        self._streaming = False
        if self._cap:
            self._cap.release()
            self._cap = None
        logger.info("感知已停止")

    async def _inference_loop(self) -> None:
        loop = asyncio.get_event_loop()
        while self._streaming and self._cap and self._cap.isOpened():
            t0 = time.perf_counter()
            ret, frame = self._cap.read()
            if not ret:
                await asyncio.sleep(0.01)
                continue
            result = await loop.run_in_executor(None, self._process_frame, frame)
            if self._broadcast_fn:
                self._broadcast_fn(result)
            elapsed = time.perf_counter() - t0
            await asyncio.sleep(max(0, 1 / 30 - elapsed))

    def _process_frame(self, frame) -> dict:
        """处理单帧图像，返回包含人脸检测+姿态+情绪的字典。

        MediaPipe 推理异常不会抛出，返回统一的"未检测到人脸"结构。
        """

        h, w = frame.shape[:2]
        data = {
            "face": {"detected": False, "bbox": [0, 0, 0, 0]},
            "head_pose": {"pitch": 0, "yaw": 0, "roll": 0},
            "emotion": {"dominant": "neutral", "scores": {}},
            "landmarks": {"smile_ratio": 0, "brow_raise": 0,
                          "left_eye_ear": 0, "right_eye_ear": 0},
        }

        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = self._detector.detect(mp_img)
        except Exception:
            logger.exception("MediaPipe 帧处理异常，返回默认空结果")
            return data

        if not result.face_landmarks:
            return data

        lm = result.face_landmarks[0]

        # ---- 人脸框 ----
        xs = [p.x for p in lm]
        ys = [p.y for p in lm]
        x1, y1 = max(0, min(xs)), max(0, min(ys))
        x2, y2 = min(1, max(xs)), min(1, max(ys))
        data["face"] = {"detected": True, "bbox": [x1, y1, x2 - x1, y2 - y1]}

        # ---- 头部姿态（从鼻尖相对位移估算） ----
        nose = lm[1]
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        nw, nh = x2 - x1 + 0.01, y2 - y1 + 0.01
        nx, ny = (nose.x - cx) / nw, (nose.y - cy) / nh

        # roll: 双眼外角连线角度
        eye_dx = lm[263].x - lm[33].x
        eye_dy = lm[263].y - lm[33].y
        roll = math.degrees(math.atan2(eye_dy, eye_dx)) if abs(eye_dx) > 1e-6 else 0

        data["head_pose"] = {
            "yaw": round(nx * -40, 1),
            "pitch": round(ny * -30, 1),
            "roll": round(roll, 1),
        }

        # ---- Blendshapes → 面部动作指标 ----
        if result.face_blendshapes:
            bs = {b.category_name: b.score for b in result.face_blendshapes[0]}

            data["landmarks"] = {
                "smile_ratio": round(bs.get("mouthSmileLeft", 0) + bs.get("mouthSmileRight", 0) / 2, 3),
                "brow_raise": round((bs.get("browInnerUp", 0) + bs.get("browOuterUpLeft", 0) + bs.get("browOuterUpRight", 0)) / 3, 3),
                "left_eye_ear": round(bs.get("eyeBlinkLeft", 0), 3),
                "right_eye_ear": round(bs.get("eyeBlinkRight", 0), 3),
                "mouth_open": round(bs.get("jawOpen", 0), 3),
            }

            # 情绪推断
            emotion = self._infer_emotion(bs)
            data["emotion"] = emotion

        return data

    @staticmethod
    def _infer_emotion(bs: dict) -> dict:
        """从 MediaPipe Blendshapes 推断基本情绪。"""
        smile = max(bs.get("mouthSmileLeft", 0), bs.get("mouthSmileRight", 0))
        brow_up = bs.get("browInnerUp", 0)
        brow_down = max(bs.get("browOuterUpLeft", 0), bs.get("browOuterUpRight", 0))
        jaw_open = bs.get("jawOpen", 0)
        eye_blink = (bs.get("eyeBlinkLeft", 0) + bs.get("eyeBlinkRight", 0)) / 2

        scores = {"happy": 0, "sad": 0, "surprise": 0, "angry": 0, "neutral": 0}

        if smile > 0.3:
            scores["happy"] = min(1, smile * 1.5)
        if jaw_open > 0.3 and brow_up > 0.2:
            scores["surprise"] = min(1, (jaw_open + brow_up) * 0.8)
        if smile < 0.05 and brow_up < 0.05 and eye_blink < 0.1:
            scores["sad"] = 0.3
        if brow_down > 0.3 and smile < 0.1:
            scores["angry"] = min(1, brow_down)

        dominant = max(scores, key=scores.get)
        if scores[dominant] < 0.3:
            scores["neutral"] = 1.0
            dominant = "neutral"

        return {"dominant": dominant, "scores": scores}
