# VoxCPM2 语音路线

## 当前判断

`E:\jieya\yzylauncher-voxcpm2-tts\python` 是一个完整 VoxCPM2 整合包，包含源码、模型、Gradio WebUI、虚拟环境、样例音频和保存音色。它不适合整包复制进本项目，原因是：

- `build_venv` 是完整 Python 虚拟环境，包含大量三方依赖和二进制文件。
- `models` 目录包含大模型权重，不应进入主仓库。
- `app.py` 是 Gradio WebUI，不是主项目需要直接内嵌的轻量接口。
- VoxCPM2 要求 Python 3.10+、PyTorch 2.5+、CUDA 12+，不适合塞进当前 Firefly 主环境。

因此项目通过统一 TTS 接口隔离前端和模型实现：

```text
Live2D -> 本地控制服务 `/tts` -> VoxCPM2 公网/项目内/Gradio 兼容后端
```

## 三种运行模式

当前 `main/config/tts_models.json` 只保留 VoxCPM 路线：

- `voxcpm_hf_space_test`：公网 API 测试模式，调用 OpenBMB 的 Hugging Face Space。
- `voxcpm_local`：项目内 Python 模块直接加载 VoxCPM2，模型路径由配置或 `VOXCPM_MODEL_PATH` 指定。
- `voxcpm_local_gradio`：兼容外部 Gradio 服务，默认连接 `http://127.0.0.1:7860`。

公网 API 和 Gradio 兼容模式走 Gradio 队列接口：

```text
POST /gradio_api/upload -> 参考音频服务端临时路径
POST /gradio_api/call/generate -> event_id
GET  /gradio_api/call/generate/{event_id} -> 音频 URL
GET  音频 URL -> 音频二进制
```

项目内模式不经过 HTTP 或 Gradio，直接使用进程内模型缓存。公网 API 仅用于临时验证；正式展示必须验证项目内模式或受控的局域网服务。

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
voice       = voxcpm_hf_space_test、voxcpm_local 或 voxcpm_local_gradio
reference   = 参考音频 ID
promptText  = 参考音频对应文本
```

本地控制服务负责上传参考音频、调用 VoxCPM、修正音频 MIME，并把音频二进制返回给浏览器。浏览器只负责播放和驱动 Live2D 口型。

## 单独验证

可以用脚本单独验证公网 API：

```powershell
conda run -n visual-companion-robot python main/scripts/test_voxcpm_hf_space.py --text "你好，我是草莓兔兔，现在正在测试 VoxCPM 语音。"
```

测试项目内推理模式时，准备模型目录并设置：

```powershell
$env:VOXCPM_MODEL_PATH = "E:\models\VoxCPM2"
```

只有测试 `voxcpm_local_gradio` 时才需要先启动 Gradio 服务，并在
`main/config/tts_models.json` 中调整 `endpoint`。

sherpa-onnx VITS 是 `TTSInterface` 的另一种轻量实现，目前不在网页的 VoxCPM
音色列表中；可通过 `create_tts_engine("sherpa")` 单独使用。

## 后续接入计划

1. `voxcpm_hf_space_test` 只用于公网 API 临时验证。
2. `voxcpm_local` 作为项目内正式推理入口，缺少模型时必须明确失败并回退选择。
3. `voxcpm_local_gradio` 只保留为受控局域网服务兼容模式。
4. 是否在 Firefly 上运行 VoxCPM2，必须以实测内存、延迟和温度决定；无法满足时改用 sherpa VITS 或局域网推理。
