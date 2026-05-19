# Windows 启动器

这里集中存放 Windows `.bat` 薄启动器，避免项目根目录被临时入口文件占满。

这些脚本只负责检查 `pwsh.exe` 并转发到 `tools/` 下对应的 PowerShell 脚本。日常开发优先直接使用 `pwsh` 或 `tools/*.ps1`，需要双击或从 `cmd.exe` 启动时再使用这里的 `.bat`。

`live2d_stage.bat` 是 Live2D 网页开发的统一入口。双击后可在菜单中选择一键开启控制服务、Live2D 网页和浏览器，也可单独开启网页、控制服务、运行静态检查或刷新 LLM 控制文件。旧的网页相关分散启动器已经合并到这个菜单中，避免误点不同入口导致状态不一致。

VoxCPM 本地推理的模型路径不要写死进脚本。复制 `main/config/local.env.example` 为 `main/config/local.env`，再在其中设置 `VOXCPM_MODEL_PATH`。该文件会被 Git 忽略，只保存在本机。
