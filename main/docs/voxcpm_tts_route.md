# VoxCPM2 语音路线

## 当前判断

`E:\jieya\yzylauncher-voxcpm2-tts\python` 是一个完整 VoxCPM2 整合包，包含源码、模型、Gradio WebUI、虚拟环境、样例音频和保存音色。它不适合整包复制进本项目，原因是：

- `build_venv` 是完整 Python 虚拟环境，包含大量三方依赖和二进制文件。
- `models` 目录包含大模型权重，不应进入主仓库。
- `app.py` 是 Gradio WebUI，不是主项目需要直接内嵌的轻量接口。
- VoxCPM2 要求 Python 3.10+、PyTorch 2.5+、CUDA 12+，不适合塞进当前 Firefly 主环境。

因此项目采用“主工程只调用 TTS 服务”的路线：

```text
Live2D/LLM 控制服务 -> 统一 TTS HTTP 接口 -> VoxCPM2 API 或本地推理服务
```

## 两种运行模式

当前 `main/config/tts_models.json` 只保留 VoxCPM 路线：

- `voxcpm_hf_space_test`：公网 API 测试模式，调用 OpenBMB 的 Hugging Face Space。
- `voxcpm_local`：本地推理模式，默认连接 `http://127.0.0.1:7860`，也可以通过 `VOXCPM_LOCAL_URL` 覆盖。

两种模式都走 Gradio 队列接口：

```text
POST /gradio_api/upload -> 参考音频服务端临时路径
POST /gradio_api/call/generate -> event_id
GET  /gradio_api/call/generate/{event_id} -> 音频 URL
GET  音频 URL -> 音频二进制
```

公网 API 用来快速验证链路；本地推理模式用于后续正式比赛展示，避免依赖公网 Space 的排队、限流、休眠或接口变更。

## 参考音频

已从 `saved_voices` 复制少量 MP3 到：

```text
main/assets/tts/voxcpm_samples/
```

这些文件只作为 VoxCPM 的参考音频，用来约束音色，不再作为“语音模型”占位项展示。对应文本已保存到：

```text
main/assets/tts/voxcpm_samples/metadata.json
```

文本由本地 ASR 转写得到，已经同步填入 `main/config/tts_models.json` 的 `references` 配置。前端可以试听参考音频，也可以编辑参考文本；正式训练、微调或展示前仍需人工校对。

## 前端与服务端职责

前端展示台从 `/voices` 读取语音模式和参考音频列表。“更换语音模型”面板可以选择 VoxCPM 公网 API 或 VoxCPM 本地推理，也可以选择并试听参考音频、编辑参考文本。

页面请求 `/tts` 时会携带：

```text
voice       = voxcpm_hf_space_test 或 voxcpm_local
reference   = 参考音频 ID
promptText  = 参考音频对应文本
```

本地控制服务负责上传参考音频、调用 VoxCPM、修正音频 MIME，并把音频二进制返回给浏览器。浏览器只负责播放和驱动 Live2D 口型。

## 单独验证

可以用脚本单独验证公网 API：

```powershell
conda run -n visual-companion-robot python main/scripts/test_voxcpm_hf_space.py --text "你好，我是草莓兔兔，现在正在测试 VoxCPM 语音。"
```

测试本地推理模式时，先启动本地 VoxCPM Gradio 服务，再把 `voice` 切到 `voxcpm_local`。如果本地服务端口不是 `7860`，设置：

```powershell
$env:VOXCPM_LOCAL_URL = "http://127.0.0.1:<port>"
```

## 后续接入计划

1. 保留 `voxcpm_hf_space_test`，只做公网 API 临时验证。
2. 完善 `voxcpm_local`，对接本地 VoxCPM2 推理服务。
3. VoxCPM2 服务可以运行在有 CUDA 的台式机、云 GPU 或其他局域网机器上。
4. Firefly 只负责展示、控制、摄像头、麦克风和板端集成，不直接承受 20 亿参数 TTS 推理。
