import assert from "node:assert/strict";
import test from "node:test";

import { apiBaseUrl, apiUrl } from "../src/runtime-config.js";

test("本地开发继续连接板端控制服务", () => {
  assert.equal(apiBaseUrl({ hostname: "localhost", origin: "http://localhost:5174" }), "http://127.0.0.1:8765");
  assert.equal(apiUrl("chat", { hostname: "127.0.0.1", origin: "http://127.0.0.1:5174" }), "http://127.0.0.1:8765/chat");
});

test("公网网页使用 anima.veyralux.org 同源 API", () => {
  const locationLike = { hostname: "anima.veyralux.org", origin: "https://anima.veyralux.org" };
  assert.equal(apiBaseUrl(locationLike), "https://anima.veyralux.org");
  assert.equal(apiUrl("/tts", locationLike), "https://anima.veyralux.org/tts");
});
