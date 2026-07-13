const assert = require("node:assert/strict");
const test = require("node:test");

const { ACTIONS } = require("../core/actions");
const { STORAGE_KEY, loadDeviceConfig, normalizeDeviceConfig } = require("../core/config");
const { normalizePlan } = require("../core/protocol");

test("动作目录覆盖原网页全部 27 个可见动作", () => {
  assert.equal(ACTIONS.length, 27);
  for (const name of ["right_hand_up", "microphone", "heart", "captain", "plus", "scene1"]) {
    assert(ACTIONS.some((action) => action.name === name));
  }
});

test("控制计划只保留已知动作并限制语速", () => {
  const plan = normalizePlan({
    text: "你好",
    actions: [{ name: "heart", duration_ms: 50 }, { name: "unknown" }],
    speech: { rate: 99 },
  }, ACTIONS);
  assert.equal(plan.actions.length, 1);
  assert.equal(plan.actions[0].name, "heart");
  assert.equal(plan.actions[0].durationMs, 300);
  assert.equal(plan.speech.rate, 1.35);
  assert.equal(normalizePlan({ speech: { rate: "not-a-number" } }, ACTIONS).speech.rate, 0.85);
});

test("设备配置拒绝路径和非法端口", () => {
  assert.deepEqual(normalizeDeviceConfig({ mode: "local", host: "http://192.168.5.21", controlPort: 8765 }), {
    mode: "local",
    publicUrl: "https://robot.veyralux.org",
    host: "192.168.5.21",
    controlPort: 8765,
    token: "",
  });
  assert.throws(() => normalizeDeviceConfig({ host: "192.168.5.21/path" }), /设备地址/);
  assert.throws(() => normalizeDeviceConfig({ host: "192.168.5.999" }), /设备地址/);
  assert.throws(() => normalizeDeviceConfig({ host: "192.168.5.21?redirect=evil" }), /设备地址/);
  assert.throws(() => normalizeDeviceConfig({ controlPort: 70000 }), /设备端口/);
  assert.throws(() => normalizeDeviceConfig({ publicUrl: "http://robot.veyralux.org" }), /HTTPS/);
  assert.equal(normalizeDeviceConfig({}).mode, "public");
});

test("旧版局域网配置迁移后恢复公网默认链路", () => {
  const savedWx = global.wx;
  const writes = new Map();
  global.wx = {
    getStorageSync(key) {
      if (key === "visual-companion.device-config.v1") {
        return { mode: "local", host: "192.168.5.21", controlPort: 8765 };
      }
      return writes.get(key);
    },
    setStorageSync(key, value) { writes.set(key, value); },
  };
  try {
    const config = loadDeviceConfig();
    assert.equal(config.mode, "public");
    assert.equal(config.publicUrl, "https://robot.veyralux.org");
    assert.equal(writes.get(STORAGE_KEY).mode, "public");
  } finally {
    global.wx = savedWx;
  }
});

test("非 Error 异常也会显示可诊断信息", () => {
  const { errorMessage } = require("../core/error-message");
  assert.equal(errorMessage({ errMsg: "request:fail url not in domain list" }), "request:fail url not in domain list");
  assert.equal(errorMessage(undefined, "模型加载失败"), "模型加载失败");
});
