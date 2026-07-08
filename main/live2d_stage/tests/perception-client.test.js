import assert from "node:assert/strict";
import test from "node:test";

import {
  RealtimeVisionClient,
  VISION_FRAME_GAP_MS,
  normalizeVisionResult,
  realtimeVisionUrl,
} from "../src/perception-client.js";

test("Web 连续视觉采用背压后的最小帧间隔", () => {
  assert.ok(VISION_FRAME_GAP_MS <= 50);
});

test("Web 视觉上下文只接受统一 ELF2 本地结果", () => {
  assert.throws(
    () => normalizeVisionResult({ ok: true, backend: "browser-mediapipe" }, 1),
    /本地视觉结果/,
  );

  const result = normalizeVisionResult({
    ok: true,
    backend: "elf2-local-yolo-pose-yunet-sface-ferplus",
    scene_caption: "画面中有1人",
    semantic_caption: "一名戴眼镜的人坐在书桌前。",
    semantic_status: "ready",
    person_activity: "画面中有人",
    person_count: 1,
    objects_detected: ["person"],
    has_face: true,
    emotion: "happy",
    confidence: 0.9,
    full_scores: { happy: 0.9 },
  }, 123);

  assert.equal(result.sceneCaption, "画面中有1人");
  assert.equal(result.receivedAt, 123);
  assert.equal(result.emotionSource, "ferplus-onnx");
  assert.equal(result.semanticCaption, "一名戴眼镜的人坐在书桌前。");
});

test("Web 连续视觉通过同源长连接传帧并接收板端结果", async () => {
  class FakeWebSocket {
    static OPEN = 1;
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      this.listeners = new Map();
      queueMicrotask(() => {
        this.readyState = FakeWebSocket.OPEN;
        this.emit("open", {});
      });
    }
    addEventListener(type, callback) {
      const callbacks = this.listeners.get(type) || [];
      callbacks.push(callback);
      this.listeners.set(type, callbacks);
    }
    emit(type, event) {
      for (const callback of this.listeners.get(type) || []) callback(event);
    }
    send(raw) {
      const request = JSON.parse(raw);
      assert.equal(request.type, "vision");
      assert.equal(request.image, "ZmFrZQ==");
      queueMicrotask(() => this.emit("message", {
        data: JSON.stringify({
          id: request.id,
          type: "vision",
          ok: true,
          data: { ok: true, backend: "elf2-local-yolo-pose-yunet-sface-ferplus" },
        }),
      }));
    }
    close() {
      this.readyState = 3;
      this.emit("close", {});
    }
  }

  assert.equal(
    realtimeVisionUrl({ hostname: "robot.veyralux.org", origin: "https://robot.veyralux.org" }),
    "wss://robot.veyralux.org/realtime",
  );
  const client = new RealtimeVisionClient({ WebSocketCtor: FakeWebSocket, timeoutMs: 100 });
  await client.connect();
  const result = await client.analyze("ZmFrZQ==");
  assert.equal(result.backend, "elf2-local-yolo-pose-yunet-sface-ferplus");
  client.close();
});
