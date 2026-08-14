# Anima Realtime Protocol（wire v2）

> `v2` 是网络协议版本，不是产品代号；当前产品版本为 Anima v0.0.1。

## 1. 连接

WebSocket 路径：`/v2/realtime`。

公网入口先通过 `/v2/admission/status` 与 Turnstile 完成准入，Gateway 以 Secure、HttpOnly、SameSite=Strict 的签名 admission/device cookie 建立匿名设备身份；WebSocket URL 不携带 session、user、anima 或 token。连接建立后客户端发送 `session.hello`，并每 25 秒发送一次 `session.heartbeat`。控制事件使用 JSON text frame，PCM、JPEG 和回复音频使用 binary frame，避免 Base64 体积和主线程编码开销。前端默认连接当前页面的同源 `ws(s)://<host>/v2/realtime`。

公网 Gateway 从签名 device cookie 派生稳定匿名 UserId 与 SessionId，使不同设备落入不同物理分库，并忽略客户端 session hint。正式账号必须由服务端 IdentityResolver/token 产生可信 UserId，不能把 query、JSON 或 localStorage 当作身份凭据。关闭公网准入的 loopback 开发模式仍保留 session query 测试能力，但它不属于生产协议。

## 2. JSON envelope

服务器事件：

```json
{
  "v": 2,
  "type": "reply.phase",
  "sessionId": "session-1",
  "turnId": "turn-9",
  "generation": 12,
  "seq": 81,
  "sentAtMs": 1780000000000,
  "payload": { "phase": "thinking" }
}
```

客户端目前只要求 `v`、`type` 和对象型 `payload`；`turn.user_text` 可在 payload 携带 `turnId`，否则服务器生成。生产协议应继续收紧 schema、大小、速率和鉴权校验。

## 3. 二进制帧

```text
0..3   magic = VSR2
4      kind: 1=pcm16, 2=jpeg, 3=audio, 4=avatar-viseme
5      flags: kind-specific；上行媒体 bit0=request ACK；下行 AUDIO bit0=PCM stream、bit1=stream start
6..7   header length = 24 (big endian)
8..15  sequence (uint64, big endian)
16..23 timestamp_ms (uint64, big endian)
24..   payload (当前上限 2 MiB)
```

- 上行麦克风：PCM16 little-endian、mono、16 kHz，目标每帧 320 samples/20 ms；
- 上行 PCM 单帧硬限 6,400 bytes（200 ms）；连接预算默认 32,000 B/s、最多预借 1 秒，超过实时速率的帧会以 `pcm_rate_limited` 拒绝；
- 上行视觉：缩小 JPEG 关键帧，不传本地 60 FPS 原始预览流；
- 下行 `kind=3`：默认为与 `reply.segment.ready` 配对的整段音频（当前 sherpa 为 `audio/wav`）；协商 `reply-audio-stream-v1` 后为与 `reply.segment.started/chunk` 配对的 24 kHz mono PCM S16LE；
- `sequence` 在每个方向独立单调递增，用于音频与文本配对或诊断；
- 上行 PCM/JPEG 的 ACK bit0 默认关闭，避免对每个 20 ms PCM 帧发送 ACK；下行 AUDIO 的 bit0/bit1 按流式协议解释。

## 4. 客户端事件

### `session.hello`

```json
{"v":2,"type":"session.hello","payload":{"capabilities":["pcm16","jpeg","reply-segments","reply-audio-stream-v1"]}}
```

Gateway 在 `session.ready.payload.serverCapabilities` 公布服务端可用能力，并在 `session.hello.ack.payload.capabilities` 仅返回双方完成协商的能力。浏览器只在 Web Audio 低时延 PCM 播放可初始化时才声明 `reply-audio-stream-v1`；未协商时服务端必须使用 WAV 兼容路径。

### `turn.user_text`

```json
{"v":2,"type":"turn.user_text","payload":{"text":"你现在看到什么？","turnId":"optional"}}
```

开始新轮并取消当前旧轮。空文本返回 `empty_user_text`。

### `turn.cancel`

```json
{"v":2,"type":"turn.cancel","payload":{}}
```

推进 generation、取消旧任务并返回 `turn.cancelled`。浏览器同时应立即停止本地旧音频，不能只等待服务器确认。

### `settings.get` / `settings.update`

```json
{"v":2,"type":"settings.get","payload":{}}
{"v":2,"type":"settings.update","payload":{"expectedRevision":3,"personaMarkdown":"# Anima\n自然、真诚。","maxReplyChars":160,"replyDelayMs":0,"voiceId":"default"}}
```

- `personaMarkdown`：1–20000 字符；写入该 User/Anima 的 `Anima.md` 和 SQLite revision；
- `maxReplyChars`：8–2000，既进入提示约束，也在流式输出端硬截断；
- `replyDelayMs`：0–10000，用户显式设置的延迟；默认 0，不用于伪造“思考感”；
- `voiceId`：受限标识符，由服务端 Catalog allowlist 验证；不能触发 Vox/SoulX 的隐式自动切换，更改后从下一条实时连接生效；
- `providers.tts.config.voice`：若随 Provider snapshot 提交，必须与兼容字段 `voiceId` 相同；服务端拒绝冲突值，避免界面选择与实际 TTS 音色分叉；
- `expectedRevision`：必须等于最近一次 `settings.current.revision`；多标签页/多设备旧编辑器会收到 `settings_conflict`，不能静默覆盖新设置；
- 未知字段、布尔伪装整数或越界值均返回稳定 `invalid_settings` 错误。

## 5. 服务器事件

| 事件 | 当前实现 | 语义 |
| --- | :---: | --- |
| `session.ready` | 是 | WebSocket 已就绪 |
| `session.hello.ack` | 是 | 协议版本确认 |
| `media.accepted` | 是（flags bit0） | 调试用媒体帧 ACK |
| `asr.partial` | 有 ASR 时 | 监听反馈；首次有效 partial 立即取消旧代并进入 listening/barge-in，不开始 LLM |
| `asr.final` | 有 ASR 时 | 最终文本；自动开始新轮 |
| `reply.phase` | 是 | 当前发送 `thinking` 和 RAG 是否超时 |
| `reply.segment.ready` | 是 | WAV 兼容路径：整段音频、文字和 `audioSeq` 已可用 |
| `reply.segment.started` | 协商后 | PCM 流首块元数据、文字、格式和 `audioSeq` |
| `reply.segment.chunk` | 协商后 | PCM 后续块的 `chunkIndex`、长度和 `audioSeq` |
| `reply.segment.completed` | 协商后 | 当前 segment 的分块数和字节数校验值 |
| `reply.completed` | 是 | 服务端本轮生成完成；前端延迟到播放队列空闲后发布 |
| `turn.cancelled` | 是 | 代际已推进 |
| `error` | 是 | 稳定错误码，不暴露 Python 异常 |
| `perception.snapshot` | 是（有 vision 时） | 5 秒调度后的语义摘要、帧序号、观察时间和置信度 |
| `perception.error` | 是（有 vision 时） | VLM 分析失败；当前返回截断后的内部错误文本，生产前需改稳定错误码 |
| `avatar.intent` | 是 | generation-safe 的连续情感与渲染意图；可绑定回复分段 |
| `settings.current` | 是 | 当前 User/Anima 设置与 revision；更新成功时带 `updated=true` |

`session.ready.payload` 还包含 `userId`、`animaId`、`anonymous` 和 `identityAssurance`。默认匿名值为 `anonymous_session_hint`；未来认证 resolver 必须返回 `authenticated`。`client_asserted` 只用于隔离测试/显式开发组合，不能冒充正式账号认证。

### `avatar.intent`

```json
{
  "v": 2,
  "type": "avatar.intent",
  "sessionId": "session-1",
  "turnId": "turn-9",
  "generation": 12,
  "seq": 82,
  "payload": {
    "phase": "speaking",
    "expression": "warm",
    "motion": "talk",
    "gazeStrength": 0.78,
    "bodyTension": 0.52,
    "smile": 0.66,
    "eyeOpen": 0.86,
    "speechRate": 1.04,
    "speechPitch": 1.03,
    "segmentIndex": 0,
    "affect": {
      "valence": 0.32,
      "arousal": 0.48,
      "dominance": 0.05,
      "affinity": 0.41,
      "trust": 0.36
    }
  }
}
```

- `phase` 仅允许 `listening/thinking/speaking/idle`；
- `segmentIndex` 仅在对应回复分段时出现；它与 `reply.segment.ready.payload.index` 指向同一分段；
- speaking intent 在对应二进制音频之前发送，文字仍保持“音频先到、实际播放时显示”；
- 浏览器按 `sessionId + generation + seq` 过滤，不能让断线前或旧轮意图覆盖当前角色；
- expression/motion 是渲染中立语义，连续参数才是主要驱动力，不要求模型随机硬切动作。

## 6. 音频与文字同步

### 6.1 WAV 兼容路径

1. 服务端发送 binary `kind=3`，其 header `sequence=N`；
2. 随后发送 `reply.segment.ready`，payload 包含 `audioSeq=N`、`text`、`index`、`contentType`；
3. 浏览器配对二者后加入 WAV 队列，只在实际起播时向 UI 发布文字；
4. 新 generation、取消或断线清空未播放音频和未配对 map。

### 6.2 `reply-audio-stream-v1`

此路径默认关闭。只有 OpenAI-compatible TTS binding 在经过真实上游验证后显式设置 `ANIMA_TTS_STREAMING_ENABLED=true`，且客户端成功协商该能力，服务端才请求并下发 PCM 流。未协商、浏览器不支持或服务端开关关闭时，使用 6.1 的 WAV 路径。流式请求已开始后不自动重试或二次计费式切换。

1. 每块仍先发 binary `kind=3`，再发带同一 `audioSeq` 的 JSON；首块使用 `reply.segment.started` 和 `chunkIndex=0`，后续块使用 `reply.segment.chunk`；
2. 服务端限制单块最多 40 ms，首块直接下发，再以 monotonic 媒体时钟维持约 140 ms 最大预发 lead；时钟跨同 generation 的 segment 连续，慢上游不增加额外等待；
3. 浏览器对 `generation/turnId/index/chunkIndex/audioSeq`、PCM 格式、flags 和字节数做严格检查。由于 binary 先于 JSON 到达，未配对 map 硬限为 8 帧/1 MiB；
4. 播放器预缓冲目标为 120 ms、硬上限为 200 ms，同一回复的多个 segment 共用一条连续播放时间线，不会在每句结尾主动排空；
5. 首块实际起播时才显示对应文字；`reply.segment.completed` 只收尾当前句，`reply.completed` 需等播放尾部真正耗尽后才向 UI 发布；
6. 新 generation、取消、断线或协议错误会立即停止 PCM 播放并清空未配对帧。

WebSocket 保序是两条路径的当前传输前提。若未来切换 WebRTC data channel 或多连接，必须保留显式 `audioSeq` 配对和代际检查。

## 7. 可取消代际

- `reply.phase` 建立浏览器的 active generation；
- 有效 ASR partial 可先用 listening intent 建立更高 generation，从而立刻停止旧音频；
- 只有匹配 active generation 的音频/文本/完成事件可以生效；
- 服务端每次新轮先取消旧 `asyncio.Task`，再推进内核 generation；
- ASR capture 使用独立 epoch；`turn.cancel` 和有效 `turn.user_text` 先使待处理/在途识别失效，ASR 回调在发送事件与启动 turn 前都复核 epoch；
- 云 ASR 只在取得独立请求 lease 后调用上游；拒绝时返回稳定的 `asr_rate_limited` 或 `server_busy`，且不发起付费 HTTP 请求；
- 只有当前 generation 能提交记忆；
- 断开连接会关闭 ASR session 并取消当前轮。

当前协议尚缺 `speech_started`/`speech_ended`、显式 audio playback ACK、断线续传和 backpressure 水位事件；这些属于后续低时延/弱网阶段。OpenAI-compatible ASR 仍是端点后的整句 HTTP 转写，epoch 和准入只解决取消正确性与成本边界，不代表已经具备供应商原生增量转写。
