import assert from "node:assert/strict";
import test from "node:test";

import { detectActiveSpeaker } from "../src/active-speaker-client.js";

test("Web 主动说话人请求同时发送 PCM16 和连续画面", async () => {
  let body;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (_url, options) => {
    body = JSON.parse(options.body);
    return {
      ok: true,
      json: async () => ({ ok: true, backend: "elf2-local-light-asd", status: "confirmed" }),
    };
  };
  const frames = Array.from({ length: 20 }, (_, index) => ({ image: `frame-${index}`, timestamp_ms: index * 125 }));

  const result = await detectActiveSpeaker(new Float32Array(48000), frames);
  globalThis.fetch = originalFetch;

  assert.equal(result.status, "confirmed");
  assert.equal(body.sample_rate, 16000);
  assert.equal(body.frames.length, 16);
  assert.equal(body.frames[0].image, "frame-4");
  assert.equal(Buffer.from(body.audio_pcm_base64, "base64").byteLength, 32000 * 2);
});
