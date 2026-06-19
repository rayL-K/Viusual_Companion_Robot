"""板端模型运行时 — RKNN / RKLLM / ONNX 推理引擎。

所有本地模型推理统一经过这里，不散落到业务模块中。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


# ── 异常 ───────────────────────────────────────────────────────────

class ModelRuntimeError(RuntimeError):
    """模型运行时通用错误。"""


class ModelNotLoadedError(ModelRuntimeError):
    """模型尚未加载。"""


# ── 检测结果 ──────────────────────────────────────────────────────

@dataclass
class Detection:
    """单个目标检测结果。"""

    class_id: int
    class_name: str
    confidence: float
    x1: int
    y1: int
    x2: int
    y2: int


@dataclass
class DetectionResult:
    """一帧的检测结果。"""

    detections: List[Detection] = field(default_factory=list)
    frame_width: int = 0
    frame_height: int = 0


# ── 引擎抽象 ──────────────────────────────────────────────────────

class InferenceEngine(ABC):
    """推理引擎基类。"""

    @abstractmethod
    def load(self, model_path: str) -> None:
        ...

    @abstractmethod
    def is_loaded(self) -> bool:
        ...

    def unload(self) -> None:
        """释放模型资源。子类可覆写。"""


# ── RKNN 引擎（YOLO NPU 推理） ────────────────────────────────────

class RknnEngine(InferenceEngine):
    """RKNN NPU 推理引擎，用于 YOLO 模型。

    需要 rknn-toolkit2 或 rknpu2 运行库。在无 NPU 环境（开发机）下降级到
    ONNX CPU 推理，方便开发调试。
    """

    def __init__(self, target_platform: str = "rk3588", cpu_fallback: bool = True) -> None:
        self._target = target_platform
        self._cpu_fallback = cpu_fallback
        self._model = None
        self._input_size: tuple[int, int] = (640, 640)

    def load(self, model_path: str) -> None:
        path = Path(model_path)
        if not path.is_file():
            raise ModelRuntimeError(f"RKNN 模型文件不存在: {path}")

        try:
            from rknnlite.api import RKNNLite
        except ImportError:
            if not self._cpu_fallback:
                raise ModelRuntimeError("rknnlite 不可用且 CPU 降级未开启")
            self._load_cpu_fallback(str(path))
            return

        rknn = RKNNLite()
        ret = rknn.load_rknn(str(path))
        if ret != 0:
            raise ModelRuntimeError(f"RKNN 模型加载失败 (ret={ret})")

        ret = rknn.init_runtime(target=self._target)
        if ret != 0:
            raise ModelRuntimeError(f"RKNN 运行时初始化失败 (ret={ret})")

        self._model = rknn
        logger.info("RKNN 引擎已加载: %s", path.name)

    def _load_cpu_fallback(self, model_path: str) -> None:
        """开发环境降级：用 ONNX Runtime 跑 RKNN 导出的 ONNX。"""
        try:
            import onnxruntime as ort
        except ImportError:
            raise ModelRuntimeError("CPU 降级需要 onnxruntime")

        self._model = ort.InferenceSession(
            model_path.replace(".rknn", ".onnx"),
            providers=["CPUExecutionProvider"],
        )
        logger.info("RKNN 引擎（CPU 降级）已加载: %s", Path(model_path).name)

    def is_loaded(self) -> bool:
        return self._model is not None

    def unload(self) -> None:
        if self._model is not None and hasattr(self._model, "release"):
            self._model.release()
        self._model = None

    def detect(self, image: np.ndarray, conf_threshold: float = 0.5) -> DetectionResult:
        """对输入帧执行目标检测。

        Args:
            image: BGR 图像 (H, W, 3)。
            conf_threshold: 置信度阈值。

        Returns:
            DetectionResult 包含所有检测框。
        """
        if self._model is None:
            raise ModelNotLoadedError("RKNN 引擎未加载")

        import cv2

        h, w = image.shape[:2]
        resized = cv2.resize(image, self._input_size)
        input_data = np.expand_dims(resized.transpose(2, 0, 1), axis=0).astype(np.float32) / 255.0

        if hasattr(self._model, "inference"):
            outputs = self._model.inference(inputs=[input_data])
        else:
            outputs = self._model.run(None, {self._model.get_inputs()[0].name: input_data})

        return self._postprocess(outputs, w, h, conf_threshold)

    def _postprocess(
        self, outputs: List[np.ndarray], orig_w: int, orig_h: int, conf_threshold: float
    ) -> DetectionResult:
        """YOLO 输出的后处理。支持 YOLO26n / YOLOv26N 格式。

        输入: outputs[0].shape = (1, N, 6) — [x1, y1, x2, y2, score, cls]
        """
        raw = outputs[0]
        if raw.ndim == 3:
            raw = raw[0]

        detections: List[Detection] = []
        class_names = _COCO_CLASSES

        x_scale = orig_w / self._input_size[0]
        y_scale = orig_h / self._input_size[1]

        for box in raw:
            x1, y1, x2, y2, score, cls_id = box[:6]
            if score < conf_threshold:
                continue
            cls_idx = int(cls_id)
            detections.append(Detection(
                class_id=cls_idx,
                class_name=class_names[cls_idx] if cls_idx < len(class_names) else str(cls_idx),
                confidence=float(score),
                x1=int(x1 * x_scale),
                y1=int(y1 * y_scale),
                x2=int(x2 * x_scale),
                y2=int(y2 * y_scale),
            ))

        return DetectionResult(detections=detections, frame_width=orig_w, frame_height=orig_h)


# ── RKLLM 引擎（本地 LLM 推理） ──────────────────────────────────

class RkllmEngine(InferenceEngine):
    """RKLLM 本地 LLM 推理引擎，用于 Qwen2.5-1.5B-Q4。

    基于 llama.cpp (llama-cpp-python) 在 CPU 上运行 GGUF 模型。
    在 RK3588 上预期 8-12 tokens/s。
    """

    def __init__(self, n_threads: int = 4, max_tokens: int = 512) -> None:
        self._n_threads = n_threads
        self._max_tokens = max_tokens
        self._model = None

    def load(self, model_path: str) -> None:
        path = Path(model_path)
        if not path.is_file():
            raise ModelRuntimeError(f"GGUF 模型文件不存在: {path}")

        try:
            from llama_cpp import Llama
        except ImportError:
            raise ModelRuntimeError("需要 llama-cpp-python: pip install llama-cpp-python")

        self._model = Llama(
            model_path=str(path),
            n_ctx=2048,
            n_threads=self._n_threads,
            n_gpu_layers=0,
            verbose=False,
        )
        logger.info("RKLLM 引擎已加载: %s (%d threads)", path.name, self._n_threads)

    def is_loaded(self) -> bool:
        return self._model is not None

    def unload(self) -> None:
        self._model = None

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """生成文本回复。

        Args:
            prompt: 用户输入。
            system_prompt: 系统提示词。
            temperature: 采样温度。
            max_tokens: 最大生成 token 数，默认使用构造函数设定值。

        Returns:
            生成的文本。
        """
        if self._model is None:
            raise ModelNotLoadedError("RKLLM 引擎未加载")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        output = self._model.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens or self._max_tokens,
            temperature=temperature,
        )

        content = output["choices"][0]["message"]["content"]
        return str(content).strip()


# ── ONNX 引擎（通用 CPU 推理） ────────────────────────────────────

class OnnxEngine(InferenceEngine):
    """通用 ONNX CPU 推理引擎，用于 sherpa-onnx 等模型。

    RK3588 上 sherpa-onnx 有官方的 ARM64 预编译包，走 CPU 推理即可。
    """

    def __init__(self, providers: Optional[List[str]] = None) -> None:
        self._providers = providers or ["CPUExecutionProvider"]
        self._session = None

    def load(self, model_path: str) -> None:
        path = Path(model_path)
        if not path.is_file():
            raise ModelRuntimeError(f"ONNX 模型文件不存在: {path}")

        try:
            import onnxruntime as ort
        except ImportError:
            raise ModelRuntimeError("需要 onnxruntime: pip install onnxruntime")

        self._session = ort.InferenceSession(str(path), providers=self._providers)
        logger.info("ONNX 引擎已加载: %s", path.name)

    def is_loaded(self) -> bool:
        return self._session is not None

    def run(self, output_names: List[str], input_feed: Dict[str, np.ndarray]) -> List[np.ndarray]:
        if self._session is None:
            raise ModelNotLoadedError("ONNX 引擎未加载")
        return self._session.run(output_names, input_feed)


# ── YOLO COCO 类别 ────────────────────────────────────────────────

_COCO_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
    "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
    "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
    "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator",
    "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
]
