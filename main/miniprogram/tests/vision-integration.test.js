const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

test("小游戏对话使用最新板端视觉上下文且不再硬编码 neutral", () => {
  const source = fs.readFileSync(path.join(__dirname, "../game/companion-game.js"), "utf8");
  assert.match(source, /this\.perception\.getContext\(\)/);
  assert.match(source, /this\.api\.visionHealth\(\)/);
  assert.doesNotMatch(source, /const vision = \{ emotion: "neutral"/);
  assert.match(source, /activeSpeaker/);
  assert.match(source, /startSpeakerBurst/);
});

test("运行面板提供明确的环境视觉开关", () => {
  const source = fs.readFileSync(path.join(__dirname, "../game/view.js"), "utf8");
  assert.match(source, /开启环境视觉/);
  assert.match(source, /toggle-vision/);
});

test("小游戏锁定 60 FPS，并让连续视觉按请求背压运行", () => {
  const avatar = fs.readFileSync(path.join(__dirname, "../core/avatar-controller.js"), "utf8");
  const perception = require("../core/perception-controller");
  assert.match(avatar, /setPreferredFramesPerSecond\?\.\(60\)/);
  assert.ok(perception.CAPTURE_INTERVAL_MS <= 50);
  const realtimeVision = fs.readFileSync(path.join(__dirname, "../core/realtime-vision-client.js"), "utf8");
  assert.match(realtimeVision, /type: "vision"/);
});
