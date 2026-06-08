"""Moondream 2 场景分析器。

通过 HuggingFace Inference API 调用 Moondream 2，将摄像头帧转换为
自然语言场景描述。后续可切换为本地量化模型。

用法::

    analyzer = SceneAnalyzer(api_key="hf_xxx")
    frame = PerceptionFrame()
    analyzer.analyze(camera_frame, frame)
    print(frame.scene_caption)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from huggingface_hub import InferenceClient

from .vision import DetectedObject, PerceptionFrame, encode_frame_to_base64, now_iso

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "vikhyatk/moondream2"
DEFAULT_CAPTION_MAX_TOKENS = 80
DEFAULT_QUERY_MAX_TOKENS = 40


class SceneAnalyzer:
    """基于 Moondream 2 的场景理解器。

    Args:
        api_key: HuggingFace API token，默认读取 HF_TOKEN 环境变量。
        model_id: 模型 ID，默认 Moondream 2。
        timeout_sec: 单次 API 请求超时秒数。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: str = DEFAULT_MODEL_ID,
        timeout_sec: int = 30,
    ) -> None:
        self._client = InferenceClient(model=model_id, token=api_key, timeout=timeout_sec)
        self._model_id = model_id
        self._last_frame_time = 0.0
        self._min_interval = 0.8  # 最小间隔秒数，避免 API 限流

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def analyze(self, frame_bgr, frame: Optional[PerceptionFrame] = None) -> PerceptionFrame:
        """分析一帧摄像头画面，填充场景描述。

        Args:
            frame_bgr: OpenCV BGR 格式帧（numpy array）。
            frame: 已有的 PerceptionFrame，为 None 时创建新的。

        Returns:
            填充后的 PerceptionFrame，包含 scene/activity/emotion/objects。
        """

        if frame is None:
            frame = PerceptionFrame()

        # 限制调用频率
        now = time.perf_counter()
        if now - self._last_frame_time < self._min_interval:
            return frame
        self._last_frame_time = now

        frame.timestamp = now_iso()
        b64 = encode_frame_to_base64(frame_bgr)

        try:
            # 图片 URL（base64 data URI）
            image_uri = f"data:image/jpeg;base64,{b64}"

            # 三步推理：caption → activity → emotion + count
            frame.scene_caption = self._caption(image_uri)
            frame.person_activity = self._query(image_uri, "What is the person doing in this scene? Answer in one sentence.")
            frame.emotion_impression = self._query(
                image_uri,
                "What emotion does the person show? Answer with one word: happy, sad, surprised, angry, or neutral.",
            )
            frame.person_count = self._count_people(image_uri)

            logger.info("Moondream 分析完成: %s", frame.summary())
        except Exception:
            logger.exception("Moondream API 调用失败")

        return frame

    # ------------------------------------------------------------------
    # 底层 API 调用
    # ------------------------------------------------------------------

    def _caption(self, image_uri: str, max_tokens: int = DEFAULT_CAPTION_MAX_TOKENS) -> str:
        """生成场景描述。"""

        prompt = "Describe this image in detail, especially the person and their surroundings. Keep it under two sentences."
        response = self._infer(prompt, image_uri, max_tokens)
        return self._clean(response)

    def _query(self, image_uri: str, question: str, max_tokens: int = DEFAULT_QUERY_MAX_TOKENS) -> str:
        """向画面对话式提问。"""

        response = self._infer(question, image_uri, max_tokens)
        return self._clean(response)

    def _count_people(self, image_uri: str) -> int:
        """统计画面中的人数。"""

        text = self._query(image_uri, "How many people are visible in this image? Answer with just a number, e.g. 0, 1, 2.")
        try:
            return int(text.strip())
        except ValueError:
            return 0

    def _infer(self, prompt: str, image_uri: str, max_tokens: int) -> str:
        """原始 API 调用。"""

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_uri}},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        result = self._client.chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.0,
        )
        return result.choices[0].message.content

    @staticmethod
    def _clean(text: str) -> str:
        """去掉模型输出的额外标记和首尾空白。"""

        return text.strip().strip('"').strip("'").strip()
