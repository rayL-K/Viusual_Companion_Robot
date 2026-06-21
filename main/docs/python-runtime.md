# Python 与 Windows 运行时策略

## Python 版本

Windows 开发环境和 ELF2/RK3588 部署环境统一使用 Python 3.11。根目录
`.python-version`、两个 `pyproject.toml`、`environment.yml`、板端依赖说明和
远程启动检查必须保持一致。

创建或更新 Windows Conda 环境：

```bat
tools\launchers\setup_conda.bat
```

环境名称为 `visual-companion-robot`。运行完整本地检查：

```bat
tools\launchers\test_live2d.bat
```

该入口会使用 `conda run -n visual-companion-robot`，不会误用 `base` 或系统
Python。`main/scripts/check_python_compat.py` 默认按 Python 3.11 语法检查。

## Windows PowerShell

PowerShell 7 是可选项，不是前置条件。`tools/launchers/*.bat` 会优先使用
`pwsh.exe`；未安装时自动通过 Windows 10 自带的 Windows PowerShell 5.1
执行 UTF-8 PowerShell 脚本。不要直接用 PowerShell 5.1 的 `-File` 运行这些
UTF-8 无 BOM 脚本，应始终从 `.bat` 入口启动。

## Firefly 板端

板端需要提供 Python 3.11 环境，再安装
`main/config/requirements-board.txt`。`tools/launchers/run_firefly.bat` 会在远程
启动前检查版本；如果板端仍只有 Python 3.8，必须先升级运行时，不能依靠
语法检查掩盖依赖和标准库不兼容。
