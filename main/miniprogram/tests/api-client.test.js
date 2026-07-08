const assert = require("node:assert/strict");
const test = require("node:test");

const requests = [];
global.wx = {
  arrayBufferToBase64(buffer) { return Buffer.from(buffer).toString("base64"); },
  request(options) {
    requests.push(options);
    options.success({ statusCode: 200, data: { ok: true } });
  },
};

const { DeviceApiClient } = require("../core/api-client");

test("公网模式把所有推理请求汇聚到同一 HTTPS 网关", async () => {
  requests.length = 0;
  const client = new DeviceApiClient(() => ({
    mode: "public",
    publicUrl: "https://robot.veyralux.org",
    host: "192.168.5.21",
    controlPort: 8765,
    token: "device-token",
  }));

  await client.health();
  await client.vision("ZmFrZQ==");

  assert.equal(requests[0].url, "https://robot.veyralux.org/health");
  assert.equal(requests[1].url, "https://robot.veyralux.org/vision");
  assert.equal(requests[1].header["X-Device-Token"], "device-token");
});

test("局域网模式直接访问同一个板端视觉接口", async () => {
  requests.length = 0;
  const client = new DeviceApiClient(() => ({
    mode: "local",
    publicUrl: "https://robot.veyralux.org",
    host: "192.168.5.22",
    controlPort: 8765,
    token: "",
  }));

  await client.visionHealth();
  assert.equal(requests[0].url, "http://192.168.5.22:8765/vision-health");
});

test("主动说话人请求同时携带 PCM16 和连续画面", async () => {
  requests.length = 0;
  const client = new DeviceApiClient(() => ({
    mode: "public",
    publicUrl: "https://robot.veyralux.org",
    host: "192.168.5.22",
    controlPort: 8765,
    token: "",
  }));

  await client.activeSpeaker(
    new Int16Array(48000).map((_, index) => index),
    Array.from({ length: 20 }, (_, index) => ({ image: `frame-${index}` })),
  );

  assert.equal(requests[0].url, "https://robot.veyralux.org/active-speaker");
  assert.equal(requests[0].data.sample_rate, 16000);
  assert.equal(requests[0].data.frames.length, 16);
  assert.equal(requests[0].data.frames[0].image, "frame-4");
  assert.equal(Buffer.from(requests[0].data.audio_pcm_base64, "base64").byteLength, 32000 * 2);
  assert.ok(requests[0].data.audio_pcm_base64.length > 1000);
});
