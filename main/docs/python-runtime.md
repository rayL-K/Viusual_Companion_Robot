# Python 版本策略

## 统一目标

项目运行目标统一为 Python 3.8.x。

原因很直接：Firefly 当前系统自带 Python 3.8.10，板端运行、硬件调试和比赛展示都以 Firefly 为准。本地 Windows 可以安装更新的 Python，但业务代码必须保持 Python 3.8 兼容。

## Windows 本地

Windows 本地终端默认使用 PowerShell 7.1 或更新版本，也就是 `pwsh`。本机当前检测到的 PowerShell 是 7.6.1，满足这个要求。

Windows 本地使用 Conda 专用环境：

```bat
tools\launchers\setup_conda.bat
```

环境名称：

```text
visual-companion-robot
```

运行本地测试时使用：

```bat
tools\launchers\test_live2d.bat
```

脚本会通过 `conda run -n visual-companion-robot python ...` 执行，避免误用 `base` 环境或系统 Python。

Windows `.bat` 启动器只作为入口，统一放在 `tools/launchers/`，实际逻辑转发给 `pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File ...`。

## Firefly 板端

Firefly 端使用系统 `python3`，并在 `tools\launchers\run_firefly.bat` 调用的远程脚本中检查版本是否为 Python 3.8。

如果 Firefly 后续升级系统 Python，应该先更新本文件、`pyproject.toml`、`.python-version` 和 `tools/run_firefly.ps1`，再改代码语法。

## 编码约束

- 不使用 Python 3.9+ 才支持的类型写法，例如 `list[str]`、`dict[str, int]`。
- 不使用 Python 3.10+ 才支持的语法，例如 `str | None`、`match/case`、`@dataclass(slots=True)`。
- 本地测试会运行 `main/scripts/check_python_compat.py`，用于检查源码是否符合 Python 3.8 语法。
