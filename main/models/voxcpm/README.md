# VoxCPM 本地模型目录

本目录用于放置项目内本地推理模式使用的 VoxCPM 模型权重。

默认路径：

```text
main/models/voxcpm/VoxCPM2
```

模型权重体积较大，不纳入 Git。开发机或 Firefly 上可以选择两种方式之一：

- 将 VoxCPM2 权重目录放到 `main/models/voxcpm/VoxCPM2`。
- 设置环境变量 `VOXCPM_MODEL_PATH` 指向实际模型目录。

项目内本地推理入口在 `visual_companion_robot.voice.voxcpm_local`。该入口直接调用 VoxCPM 官方 Python API，公网 API 和本地 Gradio 桥接只用于测试或临时兼容。

本地 Python 环境使用仓库根目录的 `environment.yml` 创建或更新。当前已验证的组合是 Python 3.11、VoxCPM 2.0.3、torch 2.11.0 和 torchaudio 2.11.0。

参考来源：

- https://github.com/OpenBMB/VoxCPM
- https://huggingface.co/openbmb/VoxCPM2
