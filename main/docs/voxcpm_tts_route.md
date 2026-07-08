# ELF2 本地 VoxCPM 语音路线

## 结论

Vox 音色现在运行在 **ELF2 开发板本地**，不依赖 Windows、Hugging Face Space 或外部 Gradio。生产保留两个互补后端：

- `matcha_baker`：默认实时女声，适合连续对话。
- `voxcpm_board`：VoxCPM1.5 Q4 参考音色，使用 `soft_girl` 配置，适合强调音色质量的短句。

VoxCPM 在 RK3588 CPU 上不能达到实时：已登记音色后的 2.56 秒短句需要约 15–19 秒生成。因此它不会替换实时默认后端，也不会常驻占用内存；控制网关按请求启动 VoxCPM.cpp，合成结束后立即释放进程。

## 固定版本与资产

| 项目 | 固定值 |
| --- | --- |
| 引擎 | `bluryar/VoxCPM.cpp` |
| 提交 | `6d84d9e4fd23785f0b943722ff354863cda52497` |
| 模型 | `voxcpm1.5-q4_k-audiovae-f16.gguf` |
| 模型大小 | `677811936` bytes |
| SHA-256 | `ce5edb331e869d89a8f816c9288fba4c1cffa636099808d240974a34f2ce8361` |
| 参考音色 | `soft_girl` |
| 推理步数 | 4 |
| CPU 线程 | 4 |

参考音频与文本位于 `main/assets/tts/voxcpm_samples/` 和 `main/config/tts_models.json`。参考音色首次使用时会注册到 `/var/lib/visual-companion-voxcpm/voices`，以后直接复用预编码特征。

## 安装

在 ELF2 项目根目录执行：

```bash
chmod +x tools/board/install_voxcpm_cpp.sh
tools/board/install_voxcpm_cpp.sh
```

如果开发板不能直连 Hugging Face，先在其他机器下载并校验模型，再传到板端：

```bash
VOXCPM_MODEL_SOURCE=/path/to/voxcpm1.5-q4_k-audiovae-f16.gguf \
  tools/board/install_voxcpm_cpp.sh
```

如果 GitHub 也不可达，可额外传入 GitHub 源码归档及其 SHA-256：

```bash
VOXCPM_SOURCE_ARCHIVE=/path/to/VoxCPM.cpp.tar.gz \
VOXCPM_SOURCE_SHA256=<archive-sha256> \
VOXCPM_MODEL_SOURCE=/path/to/voxcpm1.5-q4_k-audiovae-f16.gguf \
  tools/board/install_voxcpm_cpp.sh
```

安装脚本会校验提交和模型 SHA、CPU 构建服务端、安装到 `/opt/visual-companion-voxcpm`，但不会启用常驻服务。`visual-companion-control.service` 会在 `/tts` 请求期间启动子进程；子进程继承控制服务的 cgroup 内存上限。

## 调用链

```text
Web / Live2D
  -> POST /tts (voice=voxcpm_board, reference=soft_girl)
  -> ELF2 control gateway
  -> loopback http://127.0.0.1:8770
  -> VoxCPM.cpp + Q4 model
  -> WAV -> browser playback -> Live2D mouth timeline
```

`voxcpm_cpp.py` 只允许回环 HTTP 地址，外部客户端无法直接访问模型服务。公网仍只暴露统一网关。

## ELF2 实测

- Q4 模型服务合成峰值 RSS 约 2.3 GiB。
- CLI 包含参考音频编码时，3.04 秒音频总耗时约 27–34 秒。
- 服务端预注册 `soft_girl` 后，2.56 秒音频约 15–19 秒。
- 输出是有效 WAV；板端 SenseVoice 能重新识别出目标短句。

以上数据说明链路可用但不实时。UI 中应把 Matcha 用作默认连续语音，把 VoxCPM 作为用户主动选择的高质量音色。

## 验证

```bash
curl -fsS http://127.0.0.1:8765/tts-health?voice=voxcpm_board
```

统一 `/tts` 受设备令牌保护。通过网页“语音模型”面板选择“开发板 VoxCPM 参考音色”并试听，可同时验证自动启动、参考音色注册、WAV 返回、播放和口型。合成结束后确认没有残留进程：

```bash
pgrep -af voxcpm-server || true
```

## 不再采用的生产路径

- Windows CUDA VoxCPM2：RTX 2060 6 GiB 接近显存上限，生成速度不可接受，而且不满足板端本地要求。
- VoxCPM2 Python 进程内后端：依赖和内存不适合与 8 GiB ELF2 的视觉服务常驻共存。
- 公网 Hugging Face Space / 本地 Gradio：不作为可选生产音色，避免网络排队和额外运行时。
