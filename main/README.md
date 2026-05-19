# Visual Companion Robot 板端应用

这个目录是 Firefly/RK3588 端应用的主体代码。

当前状态：先完成清晰的项目结构、模块边界和 Live2D 资源测试。真实摄像头、语音识别、对话模型、语音合成和图形渲染会按模块逐步接入。

## 设计参考

Live2D 展示方向可以参考 ZerolanLiveRobot：

- 仓库：https://github.com/AkagawaTsurunaki/ZerolanLiveRobot
- 借鉴点：角色显示层要和设备采集、语音识别、对话模型解耦；Live2D 控制应独立支持呼吸、眨眼、口型同步、表情切换和动作播放。
- 处理原则：不直接复制对方代码，只借鉴架构思路，并按 Firefly 板端运行环境重新实现。

后续语音、LLM 控制 Live2D 和口型同步的外部参考评估见：

```text
docs/external_reference_assessment.md
```

VoxCPM2 语音路线和开发占位样本说明见：

```text
docs/voxcpm_tts_route.md
```

LLM 输出到 Live2D 的结构化控制协议见：

```text
docs/live2d_control_protocol.md
```

Live2D 展示台声音默认优先连接本地 TTS 服务：

```text
../tools/launchers/start_live2d_tts.bat
```

当前 Strawberry_Rabbit 模型的原始使用说明、热键和水印参数整理见：

```text
docs/live2d_model_usage.md
```

## 目录结构

```text
main/
  app.py                         板端程序入口
  config/                        应用配置
  docs/                          架构与任务文档
  scripts/                       本地测试与资源检查脚本
  src/visual_companion_robot/    可复用业务模块
  tests/                         后续自动化测试
```

## 运行方向

Windows 笔记本作为主要编辑环境，Firefly 作为运行和硬件调试环境。

Windows 本地终端默认使用 PowerShell 7.1 或更新版本，也就是 `pwsh`。根目录批处理脚本会检查并调用 `pwsh.exe`，避免退回 Windows PowerShell 5。

Python 版本以 Firefly 当前 Python 3.8.x 为目标。Windows 本地通过根目录的 Conda 环境 `visual-companion-robot` 运行测试，避免使用 `base` 环境。

Firefly 远程项目路径：

```text
~/wwk/Visual_Companion_Robot
```

在 Windows 项目根目录使用这些脚本：

```bat
tools\launchers\sync_firefly.bat
tools\launchers\run_firefly.bat
```

## Live2D 资源

当前本地测试模型：

```text
assets/live2d/Strawberry_Rabbit/Strawberry_Rabbit.model3.json
```

模型目录内的 `manifest.json` 是我们自己的资源清单，用来统一记录表情和动作名称，避免业务代码直接依赖零散文件名。

运行本地资源结构测试：

```bat
tools\launchers\test_live2d.bat
```

运行嘴型同步可视化测试：

```bat
tools\launchers\test_mouth_visual.bat
```

运行真实 Live2D 展示台静态检查：

```bat
tools\launchers\test_live2d_stage.bat
```

生成一次 DeepSeek 结构化控制文件：

```bat
tools\launchers\generate_llm_control.bat
```

打开真实 Live2D 展示台：

```bat
tools\launchers\open_live2d_stage.bat
```

展示台位于 `live2d_stage/`，通过 Vite 加载本地 Strawberry_Rabbit 模型。浏览器端只请求本地控制服务，由服务侧调用 LLM 和 VoxCPM，不接触 API key 或模型服务细节。

每个音对应的嘴型和临时合成声音参数在：

```text
config/mouth_shapes.json
```

报告页面支持实时调参、恢复当前音初始值、恢复全部初始值、保存调整值到浏览器本地缓存，并下载调整后的完整配置 JSON。

测试会检查模型引用、贴图、全部表情文件和全部动作文件，并生成报告：

```text
main/reports/live2d_asset_test_report.json
```

嘴型可视化测试会生成：

```text
main/reports/mouth_visual_test.html
```
