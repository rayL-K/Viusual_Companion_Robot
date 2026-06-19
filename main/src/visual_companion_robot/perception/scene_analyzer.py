"""视觉场景分析器 — 双后端。

cloud: Qwen3-VL-8B API
local: YOLO NPU 检测 + Qwen2.5-0.5B 描述
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import requests

from visual_companion_robot.integrations.model_runtime import DetectionResult, RkllmEngine
from .detector import YoloDetector
from .vision import PerceptionFrame, encode_frame_to_base64, now_iso

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "Qwen/Qwen3-VL-8B-Instruct"
DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"


@dataclass
class SceneAnalyzerConfig:
    backend: str = "cloud"
    api_key: str = ""
    model_id: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    yolo_model_path: str = ""
    vision_llm_path: str = ""
    conf_threshold: float = 0.5


class SceneAnalyzer:
    def __init__(self, config: SceneAnalyzerConfig) -> None:
        self._cfg = config
        self._base_url = config.base_url.rstrip("/")
        self._detector: Optional[YoloDetector] = None
        self._vision_llm: Optional[RkllmEngine] = None

        if config.backend == "local":
            if not config.yolo_model_path:
                raise ValueError("local 后端需要 yolo_model_path")
            self._detector = YoloDetector(model_path=config.yolo_model_path, conf_threshold=config.conf_threshold)
            if config.vision_llm_path:
                self._vision_llm = RkllmEngine(n_threads=4, max_tokens=128)

    def load(self) -> None:
        if self._detector is not None and not self._detector.is_loaded():
            self._detector.load()
            logger.info("本地 YOLO 检测器已加载")
        if self._vision_llm is not None and not self._vision_llm.is_loaded():
            self._vision_llm.load(str(self._cfg.vision_llm_path))
            logger.info("本地视觉小 LLM 已加载")

    def analyze(self, frame_bgr: np.ndarray, frame: Optional[PerceptionFrame] = None) -> PerceptionFrame:
        result = frame or PerceptionFrame()
        result.timestamp = now_iso()
        result.frame_width = frame_bgr.shape[1]
        result.frame_height = frame_bgr.shape[0]

        if self._cfg.backend == "local":
            self._analyze_local(frame_bgr, result)
        else:
            self._analyze_cloud(frame_bgr, result)
        return result

    def _analyze_cloud(self, frame_bgr: np.ndarray, frame: PerceptionFrame) -> None:
        if not self._cfg.api_key:
            frame.scene_caption = "未配置视觉 API 密钥"
            return

        base64_image = encode_frame_to_base64(frame_bgr)
        payload = {
            "model": self._cfg.model_id,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
                    {"type": "text", "text": "请用一句中文描述画面中的场景、人物活动和情绪。"},
                ],
            }],
            "max_tokens": 200,
        }

        try:
            resp = requests.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._cfg.api_key}", "Content-Type": "application/json"},
                json=payload, timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            caption = data["choices"][0]["message"]["content"].strip()
            frame.scene_caption = caption
            frame.scene_raw = caption
        except Exception as exc:
            logger.warning("云端视觉分析失败: %s", exc)
            frame.scene_caption = "视觉分析暂时不可用"

    def _analyze_local(self, frame_bgr: np.ndarray, frame: PerceptionFrame) -> None:
        if self._detector is None:
            frame.scene_caption = "本地检测器未初始化"
            return

        try:
            det_result = self._detector.detect(frame_bgr)
        except Exception as exc:
            logger.warning("本地 YOLO 检测失败: %s", exc)
            frame.scene_caption = "视觉检测暂时不可用"
            return

        frame.scene_caption = self._detector.detect_for_scene(frame_bgr)
        frame.objects_detected = [d.class_name for d in det_result.detections]

        if self._vision_llm and det_result.detections:
            try:
                frame.scene_caption = self._generate_description(det_result)
            except Exception as exc:
                logger.warning("视觉小 LLM 描述生成失败: %s", exc)

    def _generate_description(self, det_result: DetectionResult) -> str:
        objects_str = ", ".join(f"{d.class_name}({d.confidence:.0%})" for d in det_result.detections[:8])
        return self._vision_llm.generate(
            prompt=f"摄像头检测到以下物体：{objects_str}。请用一句自然的中文描述这个场景，像在和朋友说话。",
            system_prompt="你是一个场景解说助手，用一句自然的中文描述画面。",
            temperature=0.3, max_tokens=60,
        )
