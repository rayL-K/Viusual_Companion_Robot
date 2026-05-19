# Windows 启动器

这里集中存放 Windows `.bat` 薄启动器，避免项目根目录被临时入口文件占满。

这些脚本只负责检查 `pwsh.exe` 并转发到 `tools/` 下对应的 PowerShell 脚本。日常开发优先直接使用 `pwsh` 或 `tools/*.ps1`，需要双击或从 `cmd.exe` 启动时再使用这里的 `.bat`。

`start_live2d_tts.bat` 和 `open_live2d_stage.bat` 适合双击使用。它们会在结束时暂停窗口，方便查看是否启动成功；自动化调用时可先设置 `VCR_NO_PAUSE=1` 跳过暂停。

VoxCPM 本地推理的模型路径不要写死进脚本。复制 `main/config/local.env.example` 为 `main/config/local.env`，再在其中设置 `VOXCPM_MODEL_PATH`。该文件会被 Git 忽略，只保存在本机。
