"""Moondream 2 场景分析器。

支持两种模式：
- **API 模式**（默认）：通过 HuggingFace Inference API 调用。
- **本地模式**：设置 ``local_model_path`` 参数直接加载本地模型。

用法::

    # API 模式
    analyzer = SceneAnalyzer(api_key="hf_xxx")

    # 本地模式
    analyzer = SceneAnalyzer(local_model_path="main/models/moondream2")

    frame = PerceptionFrame()
    analyzer.analyze(camera_frame, frame)
    print(frame.scene_caption)
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .vision import DetectedObject, PerceptionFrame, encode_frame_to_base64, now_iso

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "vikhyatk/moondream2"
DEFAULT_LOCAL_MODEL_PATH = "main/models/moondream2"
DEFAULT_CAPTION_MAX_TOKENS = 80
DEFAULT_QUERY_MAX_TOKENS = 40


class SceneAnalyzer:
    """基于 Moondream 2 的场景理解器。

    Args:
        api_key: HF API token（API 模式）。
        model_id: 模型 ID（API 模式）。
        local_model_path: 本地模型路径（本地模式），设为非 None 启用本地推理。
        timeout_sec: API 请求超时秒数。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: str = DEFAULT_MODEL_ID,
        local_model_path: Optional[str] = None,
        timeout_sec: int = 30,
    ) -> None:
        self._model_id = model_id
        self._local_path = local_model_path
        self._last_frame_time = 0.0
        self._min_interval = 0.8

        # 本地模型
        self._local_model = None
        if self._local_path:
            self._load_local_model()

        # API 客户端（仅 API 模式需要）
        self._client = None
        if not self._local_path:
            from huggingface_hub import InferenceClient

            self._client = InferenceClient(model=model_id, token=api_key, timeout=timeout_sec)

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def analyze(self, frame_bgr, frame: Optional[PerceptionFrame] = None) -> PerceptionFrame:
        """分析一帧摄像头画面，填充场景描述。

        Args:
            frame_bgr: OpenCV BGR 格式帧（numpy array）。
            frame: 已有的 PerceptionFrame，为 None 时创建新的。

        Returns:
            填充后的 PerceptionFrame。
        """

        if frame is None:
            frame = PerceptionFrame()

        now = time.perf_counter()
        if now - self._last_frame_time < self._min_interval:
            return frame
        self._last_frame_time = now

        frame.timestamp = now_iso()

        try:
            if self._local_model:
                self._analyze_local(frame_bgr, frame)
            else:
                self._analyze_api(frame_bgr, frame)

            logger.info("Moondream 分析完成: %s", frame.summary())
        except Exception:
            logger.exception("Moondream 分析失败")

        return frame

    # ------------------------------------------------------------------
    # 本地推理
    # ------------------------------------------------------------------

    def _load_local_model(self) -> None:
        """加载本地 Moondream 2 模型。

        模型文件结构：moondream.py + model.safetensors + config.json。
        使用 importlib 动态加载自定义模型代码。
        """

        import json

        import torch
        from safetensors.torch import load_file

        model_dir = str(Path(self._local_path).resolve())

        # 动态导入 moondream 模块（作为包加载以支持相对导入）
        import importlib.util
        import sys

        spec = importlib.util.spec_from_file_location(
            "moondream",
            str(Path(model_dir) / "moondream.py"),
            submodule_search_locations=[model_dir],
        )
        if not spec or not spec.loader:
            raise RuntimeError(f"无法加载 moondream.py: {model_dir}")

        module = importlib.util.module_from_spec(spec)
        sys.modules["moondream"] = module
        spec.loader.exec_module(module)

        # 加载配置
        with open(f"{model_dir}/config.json") as f:
            config = module.MoondreamConfig.from_dict(json.load(f))

        # 加载模型权重
        logger.info("加载 Moondream 2 模型权重...")
        self._local_model = module.MoondreamModel(config, dtype=torch.float32)
        state = load_file(f"{model_dir}/model.safetensors", device="cpu")
        state = {k: v.float() for k, v in state.items()}  # bf16 → f32
        self._local_model.load_state_dict(state, strict=False)
        self._local_model.eval()
        logger.info("Moondream 2 本地模型已加载 [path=%s]", model_dir)

    def _analyze_local(self, frame_bgr, frame: PerceptionFrame) -> None:
        """本地模型推理。"""

        import numpy as np
        from PIL import Image

        # BGR → RGB → PIL
        rgb = frame_bgr[..., ::-1]
        img = Image.fromarray(rgb)

        try:
            frame.scene_caption = self._local_model.caption(img, length="normal")["caption"]
        except Exception:
            frame.scene_caption = ""

        try:
            frame.person_activity = self._local_model.query(img, "What is the person doing?")
        except Exception:
            pass

        try:
            emotion = self._local_model.query(img, "What emotion? Answer with one word.")
            frame.emotion_impression = emotion.strip().lower()
        except Exception:
            pass

        try:
            people = self._local_model.query(img, "How many people? Answer with a number.")
            frame.person_count = int(people.strip()) if people.strip().isdigit() else 0
        except Exception:
            pass

    # ------------------------------------------------------------------
    # API 推理
    # ------------------------------------------------------------------

    def _analyze_api(self, frame_bgr, frame: PerceptionFrame) -> None:
        """HF API 推理。"""

        b64 = encode_frame_to_base64(frame_bgr)
        image_uri = f"data:image/jpeg;base64,{b64}"

        frame.scene_caption = self._caption(image_uri)
        frame.person_activity = self._query(image_uri, "What is the person doing in this scene? Answer in one sentence.")
        frame.emotion_impression = self._query(
            image_uri,
            "What emotion does the person show? Answer with one word: happy, sad, surprised, angry, or neutral.",
        )
        frame.person_count = self._count_people(image_uri)

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
        """原始 API 调用。

        通过 HTTPS_PROXY 环境变量配置代理访问 HF Inference API。
        图片以 base64 data URI 形式嵌入 inputs 字段。
        """

        import base64
        import os

        import requests

        b64_data = image_uri.split(",", 1)[1] if "," in image_uri else image_uri
        token = getattr(self._client, "token", "")

        api_url = f"https://api-inference.huggingface.co/models/{self._model_id}"
        headers = {"Authorization": f"Bearer {token}"}

        payload = {
            "inputs": f"data:image/jpeg;base64,{b64_data}",
            "parameters": {"max_new_tokens": max_tokens, "temperature": 0.0},
        }

        # 使用 requests 以支持环境变量代理（HTTPS_PROXY / HTTP_PROXY）
        proxies = {}
        for var in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
            val = os.environ.get(var)
            if val:
                proxies["https"] = val
                proxies["http"] = val
                break

        resp = requests.post(
            api_url,
            headers=headers,
            json=payload,
            timeout=self._client.timeout,
            proxies=proxies if proxies else None,
        )

        if resp.status_code == 503:
            # 模型正在加载（冷启动），等待后重试一次
            import time
            time.sleep(3)
            resp = requests.post(
                api_url,
                headers=headers,
                json=payload,
                timeout=self._client.timeout,
                proxies=proxies if proxies else None,
            )

        if resp.status_code != 200:
            raise RuntimeError(f"HF API {resp.status_code}: {resp.text[:300]}")

        result = resp.json()

        # 兼容多种返回格式
        if isinstance(result, list) and result:
            item = result[0]
            if isinstance(item, dict):
                return item.get("generated_text", str(item))
            return str(item)
        if isinstance(result, dict):
            return result.get("generated_text", str(result))
        return str(result)

    @staticmethod
    def _clean(text: str) -> str:
        """去掉模型输出的额外标记和首尾空白。"""

        return text.strip().strip('"').strip("'").strip()
