# Anima v0.0.1 交互时延 SLO

> 下表是发布目标，不是已达成的宣传数据。桌面/移动浏览器、不同网络和每种生产 Provider 组合必须分别记录 p50/p95/超时率。

## 1. 用户可感知硬指标

| 场景 | p50 | p95 | 硬上限 | 起止口径 |
| --- | ---: | ---: | ---: | --- |
| 语音轮次首个有意义音频 | ≤ 1.2 s | ≤ 2.5 s | 3.5 s | `speech_ended` -> 实际 playback start |
| 文本提交首个有意义音频 | ≤ 0.85 s | ≤ 1.8 s | 2.5 s | submit ack -> 实际 playback start |
| barge-in 旧音频静音 | ≤ 100 ms | ≤ 180 ms | 250 ms | `speech_started`/cancel -> 旧 generation 无声 |
| 连续语音句间空洞 | ≤ 80 ms | ≤ 180 ms | 300 ms | 前一 segment end -> 下一 segment start |
| 文本/口型同步偏差 | ≤ 80 ms | ≤ 160 ms | 250 ms | 实际 playback clock 与 UI/viseme |
| 断线自动恢复 | ≤ 1.0 s | ≤ 3.0 s | 8.0 s | 网络可用 -> session ready |

**有意义音频**指当前回复正文的可理解开头，不包括固定填充词、假“嗯”、预录提示音或与当前上下文无关的死答案。

文本不先于语音把整段答案显示出来。对应文本在音频真正开始播放时呈现；如果 TTS 失败，UI 应显示可理解的故障状态，而不用文本抢跑伪造低时延。

## 2. 分阶段诊断目标

| 阶段 | p50 | p95 | 起止口径 |
| --- | ---: | ---: | --- |
| 客户端音频帧 -> Gateway | 60 ms | 150 ms | `media_frame_sent` -> `media_frame_received` |
| ASR partial 首字 | 220 ms | 500 ms | 有效语音开始 -> 首个非空 partial |
| 用户停止 -> endpoint | 220 ms | 500 ms | 最后有声帧 -> endpoint |
| 用户停止 -> ASR final | 350 ms | 750 ms | 最后有声帧 -> final publish |
| ContextPlanner | 25 ms | 80 ms | context start -> frozen prompt ready |
| LLM 首 content delta | 250 ms | 700 ms | request write -> first non-empty content delta |
| LLM 首个可说 clause | 450 ms | 1.1 s | request write -> clause boundary |
| TTS 首音频块 | 220 ms | 600 ms | first clause submit -> first playable PCM |
| Gateway -> 客户端播放 | 80 ms | 220 ms | reply audio frame send -> playback start |

这些子目标不能直接相加当作端到端指标，因为 ASR 端点、context prefetch、LLM 分句和 TTS 可以重叠。优化方向是流水线并行和可取消的有界队列，不是让某一阶段长期占满全部 CPU 并饿饿浏览器、网络或其他会话。

## 3. 视觉与渲染 SLO

| 路径 | 目标 | 口径 |
| --- | ---: | --- |
| Live2D 渲染 | 60 FPS 目标，p95 frame time ≤ 20 ms | `requestAnimationFrame` + 渲染器 ticker |
| 本地摄像头预览 | 60 FPS 目标，p95 ≥ 50 FPS | `requestVideoFrameCallback` 2 s 滑窗 |
| 视觉关键帧上传 | 默认 2 Hz，p95 ≥ 1.5 Hz | 通话活动且前台 |
| 语义刷新 | 默认 5 s，p95 ≤ 8 s | server observed frame -> snapshot published |
| 视觉队列 | 最多 1 张待处理帧 | 新帧覆盖旧帧，不追帧 |

60 FPS 只属于客户端预览/Live2D，不表示每秒上传或推理 60 张图。JPEG 缩放、编码、WebSocket 发送和 VLM 不得进入 `<video>` 和 Live2D 的渲染关键路径。

## 4. TurnTrace 统一时间线

至少记录：

```text
media_frame_received
speech_started / speech_ended
asr_partial_first / asr_final
context_started / context_ready
llm_request_started / llm_first_delta / llm_first_clause / llm_completed
tts_submitted / tts_first_audio / tts_completed
reply_frame_first / audio_enqueued / audio_started
reply_completed / cancelled / error
```

每个事件携带：

- `tenant/user/session/turn/generation/sequence` 的不可逆内部摘要；
- 同进程耗时使用 `monotonic_ns`；
- 跨端关联使用 wall clock 及时钟偏差样本；
- provider/model、输入长度分桶、输出长度、缓存命中和 usage（供应商返回时）；
- 完成、取消或错误终态，所有 turn 都必须闭合。

禁止记录 API key、Authorization/Cookie、prompt/回复正文、ASR/VLM 原文、原始音视频、文档 chunk、`Anima.md` 或用户绝对路径。不能直接相减未校时的两台设备日志时间。

## 5. 测量方法

每个环境至少：

1. 10 轮预热不计入统计；
2. 不少于 100 轮中文、30 轮中英混合和 30 轮打断；
3. 短句/长句、无视觉/有视觉、热缓存/冷缓存分桶；
4. PC Wi-Fi、移动网络、注入丢包/高 RTT 各自报告；
5. 超过硬上限的轮次必须附 trace 分解，不被 p50 掩盖；
6. 目标服务器同时记录 RSS、CPU/GPU/NPU、温度、频率、热降频与 Provider 限流。

## 6. 当前证据边界

- `new_code/artifacts/memory-benchmark.json` 只证明运行该脚本的本机 SQLite/FTS/RAG 量级。
- 本机 Chrome E2E 可证明 Live2D、fake media、协议、同步显字与响应式生命周期，不证明真实 ASR/LLM/TTS/VLM 速度。
- `frameRate: { ideal: 60, max: 60 }` 只是请求，必须结合 `MediaStreamTrack.getSettings()` 和实际帧回调验证。
- 只有真实目标服务器、生产 Provider、HTTPS/WSS 与手机数据能对上表 SLO 给出“通过”结论。
