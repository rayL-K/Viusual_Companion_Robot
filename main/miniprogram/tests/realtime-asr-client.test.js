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

test("小游戏通过同源 WebSocket 边录边传并接收板端 ASR 结果", async () => {
  const socket = createSocket();
  const wxApi = {
    arrayBufferToBase64(buffer) { return Buffer.from(buffer).toString("base64"); },
    connectSocket(options) {
      assert.equal(options.url, "wss://anima.veyralux.org/realtime");
      assert.equal(options.header["X-Device-Token"], "test-token");
      queueMicrotask(() => socket.handlers.open());
      return socket;
    },
  };
  const api = {
    config: () => ({ token: "test-token" }),
    websocketUrl: () => "wss://anima.veyralux.org/realtime",
  };
  const { RealtimeAsrClient } = require("../core/realtime-asr-client");
  const client = new RealtimeAsrClient({ api, wxApi });

  await client.connect();
  assert.equal(client.begin([new Int16Array([1, 2])]), true);
  client.append(new Int16Array([3, 4]));
  const resultPromise = client.finish();
  const requestId = socket.sent[0].id;
  socket.handlers.message({
    data: JSON.stringify({ id: requestId, type: "asr_result", ok: true, data: { text: "主人你好" } }),
  });

  assert.equal((await resultPromise).text, "主人你好");
  assert.deepEqual(socket.sent.map((message) => message.type), ["asr_start", "asr_chunk", "asr_chunk", "asr_end"]);
  assert.equal(client.activeId, "");
});

test("实时通道断开会释放当前会话并拒绝待处理结果", async () => {
  const socket = createSocket();
  const wxApi = {
    arrayBufferToBase64: () => "AA==",
    connectSocket() {
      queueMicrotask(() => socket.handlers.open());
      return socket;
    },
  };
  const api = { config: () => ({}), websocketUrl: () => "wss://example.test/realtime" };
  const { RealtimeAsrClient } = require("../core/realtime-asr-client");
  const client = new RealtimeAsrClient({ api, wxApi });

  await client.connect();
  client.begin([]);
  const resultPromise = client.finish();
  socket.handlers.close();

  await assert.rejects(resultPromise, /已断开/);
  assert.equal(client.activeId, "");
  assert.equal(client.ready, false);
});
