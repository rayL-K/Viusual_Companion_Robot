# 交互时延 SLO

所有时延以真实手机公网、PC 公网和板内三种路径分别记录 p50/p95；“感觉快”不是验收指标。

| 阶段 | p50 目标 | p95 目标 | 说明 |
| --- | ---: | ---: | --- |
| 音频帧到板端 | 80 ms | 180 ms | 20 ms PCM 二进制帧 |
| ASR partial 首字 | 250 ms | 600 ms | 从有效语音开始 |
| 端点确认 | 280 ms | 650 ms | 从用户停止说话开始 |
| ASR final | 450 ms | 900 ms | 包含 SenseVoice 校正 |
| RAG + 感知快照 | 35 ms | 100 ms | 不等待新视觉推理 |
| LLM 首个可用短句 | 700 ms | 1800 ms | thinking disabled + stream |
| TTS 首个音频块 | 450 ms | 1000 ms | 已有首短句后 |
| 停止说话到角色开口 | 1.8 s | 3.5 s | 首音频与文字同步 |
| 打断生效 | 120 ms | 250 ms | 停止旧音频和动作 |
| Live2D 帧率 | 60 FPS | ≥50 FPS | 2 秒滑窗 |
| 视觉快路径新鲜度 | 500 ms | 1200 ms | 最新值背压 |
| 场景语义新鲜度 | 5 s | 8 s | 变化触发，非逐帧 |

## 测量事件

统一事件时间线至少记录：

`speech_started`、`speech_ended`、`asr_partial_first`、`asr_final`、`context_ready`、`llm_first_token`、`llm_first_sentence`、`tts_first_chunk`、`audio_started`、`reply_completed`、`interrupted`。

每个事件携带 `session_id / turn_id / generation / monotonic_ns`，禁止用前端日志时间互相减得出板端时延。
