const assert = require("node:assert/strict");
const test = require("node:test");

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

test("录音达到单次上限后会继续监听，主动停止则不会重启", async () => {
  const handlers = {};
  let startCount = 0;
  const recorder = {
    start() { startCount += 1; handlers.start?.(); },
    stop() { handlers.stop?.(); },
    onStart(fn) { handlers.start = fn; },
    onStop(fn) { handlers.stop = fn; },
    onError(fn) { handlers.error = fn; },
    onFrameRecorded(fn) { handlers.frame = fn; },
  };
  global.wx = { getRecorderManager: () => recorder };
  delete require.cache[require.resolve("../core/audio-controller")];
  const { AudioController } = require("../core/audio-controller");
  const listening = [];
  const controller = new AudioController({ api: {}, onSegment() {}, onListening: (value) => listening.push(value) });

  controller.start();
  assert.equal(startCount, 1);
  handlers.stop();
  await new Promise((resolve) => setTimeout(resolve, 110));
  assert.equal(startCount, 2);
  assert.equal(controller.desiredListening, true);

  controller.stop();
  await new Promise((resolve) => setTimeout(resolve, 100));
  assert.equal(startCount, 2);
  assert.equal(controller.desiredListening, false);
  assert.deepEqual(listening, [true, false]);
});

test("小游戏优先消费边录边传的 ASR 结果，不再重复上传整段 PCM", async () => {
  global.wx = global.wx || {};
  const { CompanionGame } = require("../game/companion-game");
  const submitted = [];
  const game = Object.assign(Object.create(CompanionGame.prototype), {
    transcriptionRunning: false,
    api: {
      transcribe() {
        throw new Error("不应回退到整段 HTTP 上传");
      },
    },
    perception: {
      applyActiveSpeaker() {},
    },
    setStatus() {},
    log() {},
    submitText(text, source) {
      submitted.push({ text, source });
      return Promise.resolve();
    },
  });

  await game.handleAudioSegment(
    new Int16Array([1, 2, 3]),
    [],
    Promise.resolve({ text: "主人你好呀", speech_detected: true }),
  );

  assert.deepEqual(submitted, [{ text: "主人你好呀", source: "speech" }]);
});

test("录音控制器在说话期间上传音频块，并把句尾结果交给调用方", async () => {
  const recorder = {
    onStart() {}, onStop() {}, onError() {}, onFrameRecorded() {},
  };
  global.wx = { getRecorderManager: () => recorder };
  delete require.cache[require.resolve("../core/audio-controller")];
  const { AudioController } = require("../core/audio-controller");
  const received = [];
  const controller = new AudioController({
    api: {},
    onSegment: (pcm, realtimeResult) => received.push({ pcm, realtimeResult }),
  });
  const finishedResult = Promise.resolve({ text: "流式结果" });
  const calls = [];
  controller.realtimeAsr = {
    begin(chunks) { calls.push(["begin", chunks]); return true; },
    append(samples) { calls.push(["append", samples]); return true; },
    finish() { calls.push(["finish"]); return finishedResult; },
    cancel() {},
  };
  const firstChunk = new Int16Array([1, 2]);
  const finalSegment = new Int16Array([1, 2, 3, 4]);
  let pushCount = 0;
  controller.segmenter = {
    active: false,
    chunks: [firstChunk],
    push() {
      pushCount += 1;
      this.active = true;
      return pushCount === 2 ? finalSegment : null;
    },
  };

  controller._pushSpeechSamples(firstChunk);
  controller._pushSpeechSamples(new Int16Array([3, 4]));

  assert.deepEqual(calls.map(([name]) => name), ["begin", "append", "finish"]);
  assert.equal(received[0].pcm, finalSegment);
  assert.equal(received[0].realtimeResult, finishedResult);
});

test("摄像头停止后忽略尚未返回的板端视觉结果", async () => {
  const vision = deferred();
  const updates = [];
  let destroyed = false;
  const camera = {
    takePhoto() { return Promise.resolve({ tempImagePath: "photo.jpg" }); },
    destroy() { destroyed = true; },
  };
  global.wx = {
    createCamera: (options) => {
      queueMicrotask(() => options.success?.());
      return camera;
    },
    getFileSystemManager: () => ({ readFile({ success }) { success({ data: "ZmFrZQ==" }); } }),
  };
  delete require.cache[require.resolve("../core/perception-controller")];
  const { PerceptionController } = require("../core/perception-controller");
  const controller = new PerceptionController({
    api: { vision: () => vision.promise },
    onUpdate: (value) => updates.push(value),
  });

  controller.start();
  controller.capture();
  await Promise.resolve();
  await Promise.resolve();
  controller.stop();
  vision.resolve({
    ok: true,
    backend: "elf2-local-yolo-pose-yunet-sface-ferplus",
    scene_caption: "画面中有1人",
    has_face: true,
    emotion: "happy",
    confidence: 0.9,
  });
  await Promise.resolve();
  await Promise.resolve();

  assert.equal(controller.getContext().enabled, false);
  assert.equal(updates.at(-1).enabled, false);
  assert.equal(destroyed, true);
});

test("视觉上下文包含板端场景并在超时后标记为陈旧", () => {
  const { CONTEXT_MAX_AGE_MS, normalizeVisionResult } = require("../core/perception-controller");
  const receivedAt = 1000;
  const context = normalizeVisionResult({
    ok: true,
    backend: "elf2-local-yolo-pose-yunet-sface-ferplus",
    timestamp: "2026-07-05T06:44:00+00:00",
    scene_caption: "画面中有1人、1台笔记本电脑",
    semantic_caption: "一名微笑的人坐在电脑前，背景是室内书桌。",
    semantic_status: "ready",
    person_activity: "人物可能正在使用电脑",
    person_count: 1,
    objects_detected: ["person", "laptop"],
    has_face: true,
    emotion: "happy",
    confidence: 0.88,
    full_scores: { happy: 0.88 },
  }, receivedAt);
  const controller = Object.assign(Object.create(null), { context });
  const { PerceptionController } = require("../core/perception-controller");

  assert.equal(PerceptionController.prototype.getContext.call(controller, receivedAt).stale, undefined);
  assert.equal(PerceptionController.prototype.getContext.call(controller, receivedAt + CONTEXT_MAX_AGE_MS + 1).stale, true);
  assert.equal(context.sceneCaption, "画面中有1人、1台笔记本电脑");
  assert.equal(context.semanticCaption, "一名微笑的人坐在电脑前，背景是室内书桌。");
});

test("Live2D 每帧都会恢复模型默认隐藏项并关闭水印", () => {
  const { AvatarController } = require("../core/avatar-controller");
  const writes = [];
  const controller = new AvatarController();
  controller.model = {
    internalModel: {
      coreModel: {
        setParameterValueById(id, value) {
          writes.push([id, value]);
        },
      },
    },
  };
  controller.renderer = { render() {} };
  controller.stage = {};
  controller.canvas = { requestAnimationFrame() { return 1; } };
  controller.running = true;
  controller.heldParameters.set("Param261", 0);

  controller._renderFrame();

  const finalValues = new Map(writes);
  assert.equal(finalValues.get("Param261"), 1);
  ["Param44", "Param59", "Param60", "Param61", "Param62", "Param63", "Param64", "Param65", "Param78"]
    .forEach((id) => assert.equal(finalValues.get(id), 0));
});

test("Live2D 指针平滑不随 30/60 FPS 改变速度", () => {
  const { AvatarController } = require("../core/avatar-controller");
  const run = (fps) => {
    const controller = new AvatarController();
    controller.running = true;
    controller.renderer = { render() {} };
    controller.stage = {};
    controller.canvas = { requestAnimationFrame() { return 1; } };
    controller.pointerTarget.x = 1;
    for (let frame = 0; frame <= fps; frame += 1) {
      controller._renderFrame(frame * 1000 / fps);
    }
    return controller.pointer.x;
  };

  assert.ok(Math.abs(run(30) - run(60)) < 0.01);
});

test("Live2D 播放语音时持续写入口型，并在待机时呼吸和眨眼", () => {
  const { AvatarController } = require("../core/avatar-controller");
  const writes = [];
  const controller = new AvatarController();
  controller.model = {
    internalModel: {
      coreModel: {
        setParameterValueById(id, value) { writes.push([id, value]); },
      },
    },
  };
  controller.renderer = { render() {} };
  controller.stage = {};
  controller.canvas = { requestAnimationFrame() { return 1; } };
  controller.running = true;
  controller.setMouthSync(true);

  controller._renderFrame(1000);
  const first = new Map(writes);
  writes.length = 0;
  controller._renderFrame(1033);
  const second = new Map(writes);

  assert.ok(first.get("ParamMouthOpenY") > 0);
  assert.notEqual(first.get("ParamMouthOpenY"), second.get("ParamMouthOpenY"));
  assert.ok(second.has("ParamMouthForm"));
  assert.ok(second.has("ParamBreath"));
  assert.ok(second.has("ParamEyeLOpen"));
  assert.ok(second.has("ParamAngleZ"));
});
