import assert from "node:assert/strict";
import test from "node:test";

import { RealtimeAsrClient, realtimeAsrUrl } from "../src/offline-asr-client.js";

class FakeWebSocket {
  static OPEN = 1;

  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.bufferedAmount = 0;
    this.sent = [];
    this.listeners = new Map();
    queueMicrotask(() => {
      this.readyState = FakeWebSocket.OPEN;
      this.emit("open", {});
    });
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  send(raw) {
    this.sent.push(JSON.parse(raw));
  }

  close() {
    this.readyState = 3;
    this.emit("close", {});
  }

  emit(type, event) {
    for (const listener of this.listeners.get(type) || []) listener(event);
  }
}

test("公网地址会转换为同源 WSS 实时通道", () => {
  assert.equal(
    realtimeAsrUrl({ hostname: "robot.veyralux.org", origin: "https://robot.veyralux.org" }),
    "wss://robot.veyralux.org/realtime",
  );
});

test("语音块边录边上传，句尾消息返回板端识别结果", async () => {
  const client = new RealtimeAsrClient({
    url: "wss://robot.veyralux.org/realtime",
    WebSocketCtor: FakeWebSocket,
    timeoutMs: 1000,
  });
  await client.connect();
  assert.equal(client.begin([new Float32Array([0, 0.5, -0.5])], 16000), true);
  const socket = client.socket;
  assert.deepEqual(socket.sent.map((message) => message.type), ["asr_start", "asr_chunk"]);

  const resultPromise = client.finish();
  assert.equal(socket.sent.at(-1).type, "asr_end");
  socket.emit("message", {
    data: JSON.stringify({
      id: socket.sent[0].id,
      type: "asr_result",
      ok: true,
      data: { ok: true, text: "你好" },
    }),
  });

  assert.deepEqual(await resultPromise, { ok: true, text: "你好" });
  assert.equal(client.activeId, "");
});
