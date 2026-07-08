# 当前架构边界

```text
响应式 Web
  -> Cloudflare Worker / VPC Service / QUIC Tunnel
  -> ELF2 control gateway
     -> 实时结构化视觉：YOLO + Pose + YuNet/SFace + FER+
     -> 异步语义视觉：Qwen3-VL-2B W8A8
     -> 音画说话人：Light-ASD
     -> ASR：WebRTC VAD + SenseVoice INT8
     -> TTS：Matcha/Vocos（默认）或 VoxCPM1.5 Q4（按请求）
     -> 记忆：SQLite 最近对话 + 显式长期记忆
     -> 对话计划：DeepSeek Flash
```

## 不变量

1. 原始摄像头画面、PCM、身份向量和 TTS 参考音频不发送给第三方模型。
2. 人数、身份、情绪和动作以专用模型为准；Qwen3-VL 只补充背景、外观和整体状态。
3. Live2D 渲染不等待语义 VLM；关键帧语义异步进入后续对话上下文。
4. Matcha 满足实时交互；VoxCPM 是高质量慢速选项，合成后必须释放约 2.3 GiB 内存。
5. 公网请求只经统一 Worker 和设备令牌进入 ELF2，浏览器不持有板端令牌或 API key。
6. 所有采集、推理与播放循环都有超时、背压、取消和过期结果丢弃。

更细的部署、模型来源和 Vox 实测分别见 `board-deployment.md`、`model-provenance.md` 与 `voxcpm_tts_route.md`。
