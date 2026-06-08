"""视觉场景分析器 — 硅基流动 Qwen3-VL。

通过 OpenAI 兼容 API 调用 Qwen3-VL-8B，将摄像头帧转换为中文场景描述。

用法::

    analyzer = SceneAnalyzer(api_key="sk-xxx")
    frame = PerceptionFrame()
    analyzer.analyze(camera_frame, frame)
    print(frame.scene_caption)  # "画面中一个人坐在沙发上，正在看手机。"
"""

from __future__ import annotations

import logging
import re
import time
from typing import Optional

import requests

from .vision import PerceptionFrame, encode_frame_to_base64, now_iso

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "Qwen/Qwen3-VL-8B-Instruct"
DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"


class SceneAnalyzer:
    """基于 Qwen3-VL 的场景理解器（硅基流动 API）。

    Args:
        api_key: 硅基流动 API token，以 ``sk-`` 开头。
        model_id: 模型 ID，默认 Qwen3-VL-8B-Instruct。
        base_url: API 基地址。
        timeout_sec: 单次请求超时秒数。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout_sec: int = 60,
    ) -> None:
        self._api_key = api_key
        self._model_id = model_id
        self._base_url = base_url
        self._timeout = timeout_sec
        self._last_frame_time = 0.0
        self._min_interval = 1.0

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def analyze(self, frame_bgr, frame: Optional[PerceptionFrame] = None) -> PerceptionFrame:
        """分析一帧摄像头画面，填充场景描述。"""

        if frame is None:
            frame = PerceptionFrame()

        now = time.perf_counter()
        if now - self._last_frame_time < self._min_interval:
            return frame
        self._last_frame_time = now

        frame.timestamp = now_iso()

        try:
            b64 = encode_frame_to_base64(frame_bgr)
            image_url = f"data:image/jpeg;base64,{b64}"

            # 四步推理
            frame.scene_caption = self._chat(
                "请用一句话描述这个画面，重点描述画面中的人物及其周围环境。",
                image_url,
            )
            frame.person_activity = self._chat(
                "画面中的人物在做什么？用一句话回答。",
                image_url,
            )
            frame.emotion_impression = self._chat(
                "画面中的人物表现出什么情绪？只回答一个词：开心、难过、惊讶、生气、或中性。",
                image_url,
            )
            frame.person_count = self._parse_count(
                self._chat("画面中有几个人？只回答数字，如 0、1、2。", image_url)
            )

            logger.info("视觉分析: %s", frame.summary())
        except Exception:
            logger.exception("视觉分析失败")

        return frame

    # ------------------------------------------------------------------
    # API 调用
    # ------------------------------------------------------------------

    def _chat(self, prompt: str, image_url: str, max_tokens: int = 100) -> str:
        """OpenAI 兼容的 vision chat 请求。"""

        resp = requests.post(
            f"{self._base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self._model_id,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": image_url}},
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
                "max_tokens": max_tokens,
                "temperature": 0.0,
            },
            timeout=self._timeout,
        )

        if resp.status_code != 200:
            raise RuntimeError(f"硅基流动 API {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()

    @staticmethod
    def _parse_count(text: str) -> int:
        """从文本中提取数字。"""

        match = re.search(r"\d+", str(text))
        return int(match.group()) if match else 0
