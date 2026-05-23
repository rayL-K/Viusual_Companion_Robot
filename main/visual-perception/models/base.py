"""模型基类"""
from abc import ABC, abstractmethod
from pathlib import Path


class BaseModel(ABC):
    def __init__(self, model_path: str | Path) -> None:
        self._model_path = Path(model_path)

    @abstractmethod
    def load(self) -> None:
        ...

    @abstractmethod
    def __call__(self, *args, **kwds):
        ...

    @property
    def model_path(self) -> Path:
        return self._model_path
