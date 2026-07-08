const assert = require("node:assert/strict");
const test = require("node:test");

function createSocket() {
  const handlers = {};
  const sent = [];
  return {
    handlers,
    sent,
    onOpen(callback) { handlers.open = callback; },
    onMessage(callback) { handlers.message = callback; },
    onError(callback) { handlers.error = callback; },
    onClose(callback) { handlers.close = callback; },
    send({ data }) { sent.push(JSON.parse(data)); },
    close() { handlers.close?.(); },
  };
}

test("小游戏连续视觉复用同源 WebSocket 并接收板端结果", async () => {
  const socket = createSocket();
  const wxApi = {
    connectSocket(options) {
      assert.equal(options.url, "wss://robot.veyralux.org/realtime");
      assert.equal(options.header["X-Device-Token"], "test-token");
      queueMicrotask(() => socket.handlers.open());
      return socket;
    },
  };
  const api = {
    config: () => ({ token: "test-token" }),
    websocketUrl: () => "wss://robot.veyralux.org/realtime",
  };
  const { RealtimeVisionClient } = require("../core/realtime-vision-client");
  const client = new RealtimeVisionClient({ api, wxApi, timeoutMs: 100 });

  await client.connect();
  const resultPromise = client.analyze("ZmFrZQ==");
  const request = socket.sent[0];
  assert.equal(request.type, "vision");
  assert.equal(request.image, "ZmFrZQ==");
  socket.handlers.message({
    data: JSON.stringify({
      id: request.id,
      type: "vision",
      ok: true,
      data: { ok: true, backend: "elf2-local-yolo-pose-yunet-sface-ferplus" },
    }),
  });

  assert.equal((await resultPromise).backend, "elf2-local-yolo-pose-yunet-sface-ferplus");
  client.close();
});

test("小游戏视觉实时通道断开会拒绝正在等待的帧", async () => {
  const socket = createSocket();
  const wxApi = {
    connectSocket() {
      queueMicrotask(() => socket.handlers.open());
      return socket;
    },
  };
  const api = { config: () => ({}), websocketUrl: () => "wss://example.test/realtime" };
  const { RealtimeVisionClient } = require("../core/realtime-vision-client");
  const client = new RealtimeVisionClient({ api, wxApi, timeoutMs: 100 });

  await client.connect();
  const resultPromise = client.analyze("ZmFrZQ==");
  socket.handlers.close();

  await assert.rejects(resultPromise, /已断开/);
  assert.equal(client.ready, false);
});
