# 交互时延 SLO 与测量口径

> 下表全部是目标，不是当前实测成绩。除内存检索微基准外，仓库目前还没有能证明端到端指标已达成的板端数据。

真实手机公网、PC 公网和板内路径必须分别记录 p50/p95；“感觉快”和单次演示不能替代统计数据。

| 阶段 | p50 目标 | p95 目标 | 起止口径 |
| --- | ---: | ---: | --- |
| 音频帧到板端 | 80 ms | 180 ms | 浏览器帧发送 → Gateway 收到 |
| ASR partial 首字 | 250 ms | 600 ms | 有效语音开始 → 首个非空 partial |
| 端点确认 | 280 ms | 650 ms | 用户停止说话 → endpoint |
| ASR final | 450 ms | 900 ms | 用户停止说话 → final 发布 |
| RAG + 感知快照 | 35 ms | 100 ms | context assemble 开始 → 结束 |
| LLM 首 token | 350 ms | 1000 ms | API 请求开始 → 首个 content delta |
| LLM 首个可说短句 | 700 ms | 1800 ms | API 请求开始 → 首句边界 |
| TTS 首段就绪 | 450 ms | 1000 ms | 首句提交 TTS → WAV/首音频块就绪 |
| 停止说话到角色开口 | 1.8 s | 3.5 s | speech_ended → `audio.play()` 成功 |
| 打断生效 | 120 ms | 250 ms | speech_started/cancel → 旧音频停止 |
| 本地摄像头预览 | 60 FPS | ≥50 FPS | 2 秒滑窗的实际呈现帧率 |
| 视觉关键帧上传 | 2 Hz | ≥1.5 Hz | 通话活动且页面前台 |
| 视觉快路径新鲜度 | 500 ms | 1200 ms | observed_at → snapshot published |
| 场景语义新鲜度 | 5 s | 8 s | 最短周期/变化触发；非逐帧 |

## 频率不变量

- **60 FPS** 是用户本地预览/Live2D 的目标，不代表每秒上传 60 张图；
- 当前前端目标每 **500 ms** 上传一张缩小 JPEG；
- Qwen/VLM 的 **5 秒**是当前固定最短语义间隔；等待窗口中只保留最新帧。场景变化提前触发仍是后续目标；
- JPEG 编码、上传和语义推理不得位于本地 `<video>` 的渲染关键路径。

## 统一时间线

至少记录：

`media_frame_sent`、`media_frame_received`、`speech_started`、`speech_ended`、`asr_partial_first`、`asr_final`、`context_started`、`context_ready`、`llm_request_started`、`llm_first_token`、`llm_first_sentence`、`tts_started`、`tts_first_chunk`、`audio_enqueued`、`audio_started`、`reply_completed`、`interrupted`。

每个事件携带：

- `session_id / turn_id / generation / sequence`；
- 同进程内用于耗时的 `monotonic_ns`；
- 跨端关联的 wall-clock 时间与时钟偏差样本；
- 模型名、线程数、输入长度、缓存命中（若供应商返回）、网络路径。

禁止用不同设备上未校准的日志时钟直接相减。

## 当前已有证据

`new_code/artifacts/memory-benchmark.json` 记录 2,000 条数据、100 次检索的本机微基准。它只证明当前机器上的 Memory/RAG 路径量级，不能证明 ELF2 性能、LLM/TTS 时延或公网端到端时延。

`new_code/artifacts/e2e-local.json` 记录真实 Chrome 在桌面 1440×900、移动 390×844 和横屏 844×390 下的本机纵切片结果：Live2D 已加载、fake camera 正在播放、文字经过真实音频播放边界后出现、三个通话按钮无裁切、文档无横纵溢出且无 pageerror。该链路使用确定性 LLM/VLM/TTS 桩，只能证明协议与 UI 生命周期，不代表真实模型时延或效果。

前端请求 `frameRate: { ideal: 60, max: 60 }` 也不等于已实现 60 FPS。验收必须读取 `MediaStreamTrack.getSettings().frameRate`，再结合 `requestVideoFrameCallback` 或等价采样统计实际呈现帧率。

## 尚缺的测量设施

- Gateway 统一 telemetry 事件和持久化；
- 浏览器首音频真实播放时刻回传；
- DeepSeek 首 token/首句和连接复用指标；
- ASR endpoint、队列深度与丢帧指标；
- TTS 冷启动/热启动/句长分桶；
- Live2D 与摄像头各自的 FPS/长任务统计；
- ELF2 RSS、CPU/NPU、温度、频率和 OOM 观测。
