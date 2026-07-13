# Realtime Protocol v2

## 1. 连接

WebSocket 路径：`/v2/realtime?session=<stable-session-id>&anima=<optional-anima-id>`

连接建立后客户端发送 `session.hello`。控制事件使用 JSON text frame，PCM、JPEG 和回复音频使用 binary frame，避免 Base64 体积和主线程编码开销。前端默认连接当前页面的同源 `ws(s)://<host>/v2/realtime`。

缺省 `user` 时，Gateway 将严格校验后的稳定 session hint 哈希为匿名 UserId，使不同浏览器默认落入不同物理分库。默认组合根会**拒绝所有显式 `user` query**；正式账号必须由服务端 IdentityResolver/token 产生可信 UserId，不能把 query、JSON 或 localStorage 当作身份凭据。测试可注入 `client_asserted` resolver 验证分库，但该 resolver 不进入默认运行组合。

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
5      flags: bit0=request media.accepted acknowledgement
6..7   header length = 24 (big endian)
8..15  sequence (uint64, big endian)
16..23 timestamp_ms (uint64, big endian)
24..   payload (当前上限 2 MiB)
```

- 上行麦克风：PCM16 little-endian、mono、16 kHz，目标每帧 320 samples/20 ms；
- 上行视觉：缩小 JPEG 关键帧，不传本地 60 FPS 原始预览流；
- 下行 `kind=3`：通用音频容器，实际类型由配对事件的 `contentType` 指定；当前 sherpa TTS 发送 `audio/wav`；
- `sequence` 在每个方向独立单调递增，用于音频与文本配对或诊断；
- bit0 默认关闭，避免对每个 20 ms PCM 帧发送 ACK。调试时才按需打开。

## 4. 客户端事件

### `session.hello`

```json
{"v":2,"type":"session.hello","payload":{"capabilities":["pcm16","jpeg","reply-segments"]}}
```

当前 Gateway 只返回 `session.hello.ack`，尚未执行能力协商。

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
{"v":2,"type":"settings.update","payload":{"expectedRevision":3,"personaMarkdown":"# 草莓兔兔\n自然、真诚。","maxReplyChars":160,"replyDelayMs":0,"voiceId":"default"}}
```

- `personaMarkdown`：1–20000 字符；写入该 User/Anima 的 `Anima.md` 和 SQLite revision；
- `maxReplyChars`：8–2000，既进入提示约束，也在流式输出端硬截断；
- `replyDelayMs`：0–10000，用户显式设置的延迟；默认 0，不用于伪造“思考感”；
- `voiceId`：受限标识符，由当前 TTS Port 验证；不能触发 Vox/SoulX 的隐式自动切换；
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
| `reply.segment.ready` | 是 | 配对文字和 `audioSeq` 已可用 |
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

每个回复片段严格按以下顺序发送：

1. binary `kind=3`，其 header `sequence=N`；
2. JSON `reply.segment.ready`，payload 包含 `audioSeq=N`、`text`、`index`、`contentType`；
3. 浏览器确认两者均存在后加入音频队列；
4. 该音频实际开始播放时才向 UI 发布 `reply.segment.ready`，从而显示文字；
5. 新 generation 会清空未播放音频和未配对 map。

WebSocket 保序是该策略的当前传输前提。若未来切换 WebRTC data channel 或多连接，必须保留显式 `audioSeq` 配对和代际检查。

## 7. 可取消代际

- `reply.phase` 建立浏览器的 active generation；
- 有效 ASR partial 可先用 listening intent 建立更高 generation，从而立刻停止旧音频；
- 只有匹配 active generation 的音频/文本/完成事件可以生效；
- 服务端每次新轮先取消旧 `asyncio.Task`，再推进内核 generation；
- 只有当前 generation 能提交记忆；
- 断开连接会关闭 ASR session 并取消当前轮。

当前协议尚缺 `speech_started`/`speech_ended`、显式 audio playback ACK、断线续传和 backpressure 水位事件；这些属于后续低时延/弱网阶段。
