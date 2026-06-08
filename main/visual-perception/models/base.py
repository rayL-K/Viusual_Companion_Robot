"""模型基类 — 定义统一的 load / __call__ 接口。"""
from abc import ABC, abstractmethod
from pathlib import Path


class BaseModel(ABC):
    """所有视觉感知模型的抽象基类。

    子类必须实现 load（加载权重）和 __call__（推理），模型路径通过
    model_path 属性统一管理。
    """

    def __init__(self, model_path: str | Path) -> None:
        """存储模型权重路径，不立即加载。

        Args:
            model_path: ONNX 或 TFLite 权重文件路径。
        """
        self._model_path = Path(model_path)

    @abstractmethod
    def load(self) -> None:
        """加载模型权重到内存。"""
        ...

    @abstractmethod
    def __call__(self, *args, **kwds):
        """执行一次推理。"""
        ...

    @property
    def model_path(self) -> Path:
        """模型权重文件的绝对路径。"""
        return self._model_path
