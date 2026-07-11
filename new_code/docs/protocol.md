# Realtime Protocol v2

## WebSocket

路径：`/v2/realtime`

连接建立后先发送 JSON `hello`，之后控制事件使用 JSON text frame，音频/图片使用 binary frame，避免 Base64 的体积与主线程编码开销。

### JSON envelope

```json
{
  "v": 2,
  "type": "turn.cancel",
  "sessionId": "...",
  "turnId": "...",
  "generation": 12,
  "seq": 81,
  "sentAtMs": 1780000000000,
  "payload": {}
}
```

### Binary header

```text
0..3   magic = VSR2
4      kind: 1=pcm16, 2=jpeg, 3=opus, 4=avatar-viseme
5      flags
6..7   header length (big endian)
8..15  sequence (big endian)
16..23 timestamp_ms (big endian)
24..   payload
```

音频默认 `PCM16 mono 16kHz`，每帧 20 ms；视觉关键帧默认 JPEG，不传本地 60 FPS 预览流。

## 关键服务器事件

- `asr.partial` / `asr.final`
- `perception.snapshot`
- `reply.phase`
- `reply.segment.ready`：一个文字片段与对应音频已同时可用
- `avatar.intent`
- `turn.cancelled`
- `error`：稳定错误码，不把 Python 异常直接显示给用户
