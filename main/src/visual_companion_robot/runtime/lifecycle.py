"""模块生命周期管理。

该模块后续负责统一启动、停止和监控各个子模块。多进程运行时需要在
这里集中处理退出信号、异常回收和健康状态上报。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ModuleSpec:
    """一个可运行模块的声明。"""

    name: str
    enabled: bool = True
    description: str = ""

