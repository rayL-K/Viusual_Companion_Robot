"""板端模型运行时适配器。

该模块用于集中管理 RKNN、RKLLM、ONNX Runtime 等推理后端。视觉模型、
语音模型和语言模型的部署细节应封装在这里，避免散落到业务代码中。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ModelRuntimeInfo:
    """一个本地模型运行实例的基本信息。"""

    name: str
    backend: str
    model_path: str

