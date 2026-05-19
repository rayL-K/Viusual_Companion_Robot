# Visual Companion Robot

比赛项目重新从 `main/` 开始组织。当前阶段只搭结构，不实现复杂业务逻辑。

## 开发方式

- Windows: 主开发与 Git 管理目录。
- Firefly: 运行、硬件调试、VNC GUI 展示目录。
- Firefly 目标路径: `~/wwk/Visual_Companion_Robot`
- 本地终端: 默认使用 PowerShell 7.1 或更新版本，也就是 `pwsh`，不再使用 Windows PowerShell 5 的 `powershell`。
- Python: 统一使用 Conda 环境 `visual-companion-robot`，当前本地推理链路以 Python 3.11 为准。

## 本地 Conda 环境

第一次在 Windows 本地测试前运行：

```bat
tools\launchers\setup_conda.bat
```

之后本地脚本会默认通过 `conda run -n visual-companion-robot ...` 执行，避免误用 `base` 环境或系统 Python。

Windows `.bat` 启动器统一放在 `tools/launchers/`，都会先检查 `pwsh.exe`，再转发到 `tools/` 下的 PowerShell 7 脚本。

## VoxCPM 本地推理

VoxCPM2 权重体积较大，不进入 Git。需要本地推理时，先复制配置模板：

```bat
copy main\config\local.env.example main\config\local.env
```

然后把 `main\config\local.env` 里的 `VOXCPM_MODEL_PATH` 改成实际的 VoxCPM2 模型目录。`tools\launchers\start_live2d_tts.bat` 会自动读取这个本机配置。

## 常用脚本

```bat
tools\launchers\setup_conda.bat
tools\launchers\sync_firefly.bat
tools\launchers\run_firefly.bat
tools\launchers\start.bat
tools\launchers\connect.bat
tools\launchers\test_live2d.bat
tools\launchers\test_mouth_visual.bat
tools\launchers\test_live2d_stage.bat
tools\launchers\generate_llm_control.bat
tools\launchers\open_live2d_stage.bat
```

嘴型可视化测试的参数配置在：

```text
main/config/mouth_shapes.json
```

这里可以调整每个音的张嘴、横向展开、圆唇、下颌、嘴角和临时合成声音参数。

## 板端入口

板端项目结构说明见 `main/README.md`。

Live2D 动画展示方向参考:

https://github.com/AkagawaTsurunaki/ZerolanLiveRobot
