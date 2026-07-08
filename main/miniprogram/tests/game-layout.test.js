const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const { containsPoint, createGameLayout, paginate } = require("../game/layout");

test("全面屏安全区不会遮挡标题或底部四个按钮", () => {
  const layout = createGameLayout(1624, { top: 88, bottom: 68 });
  assert.ok(layout.header.y >= 88);
  const buttons = [...layout.primaryButtons, ...layout.secondaryButtons];
  assert.equal(buttons.length, 4);
  buttons.forEach((button) => {
    assert.ok(button.y >= 0);
    assert.ok(button.y + button.height <= 1624 - 68);
  });
  assert.equal(layout.primaryButtons[0].width, layout.primaryButtons[1].width);
  assert.equal(layout.secondaryButtons[0].width, layout.secondaryButtons[1].width);
});

test("Live2D 展示区与聊天气泡不重叠", () => {
  const layout = createGameLayout(1624, { top: 88, bottom: 68 });
  const modelBottom = layout.bubble.y - 18;
  assert.ok(modelBottom < layout.bubble.y);
  assert.ok(layout.header.y + layout.header.height < modelBottom);
});

test("动作分页和点击命中保持在合法范围", () => {
  const data = Array.from({ length: 27 }, (_, index) => index);
  assert.deepEqual(paginate(data, 99, 9), { page: 2, pageCount: 3, items: data.slice(18) });
  assert.equal(containsPoint({ x: 10, y: 20, width: 100, height: 50 }, 110, 70), true);
  assert.equal(containsPoint({ x: 10, y: 20, width: 100, height: 50 }, 111, 70), false);
});

test("小游戏入口包含完整的四个主按钮和六个面板入口", () => {
  const source = fs.readFileSync(path.join(__dirname, "..", "game", "view.js"), "utf8");
  ["开启语音对话", "发送消息", "动作盘", "运行后端"].forEach((label) => assert.match(source, new RegExp(label)));
  ["actions", "runtime", "voices", "device", "history", "logs"].forEach((id) => assert.match(source, new RegExp(`\\[\\"${id}\\"`)));
});

test("真机 WebGL 初始化失败时展示可截图的启动错误", () => {
  const source = fs.readFileSync(path.join(__dirname, "..", "game", "main.js"), "utf8");
  assert.match(source, /try\s*{/);
  assert.ok(source.indexOf("try {") < source.indexOf('require("./companion-game")'));
  assert.match(source, /wx\.showModal/);
  assert.match(source, /restartMiniProgram/);
});

test("小游戏先提交首帧再加载较重的 Cubism 运行时", () => {
  const entrySource = fs.readFileSync(path.join(__dirname, "..", "game.js"), "utf8");
  const gameSource = fs.readFileSync(path.join(__dirname, "..", "game", "companion-game.js"), "utf8");
  const avatarSource = fs.readFileSync(path.join(__dirname, "..", "core", "avatar-controller.js"), "utf8");
  assert.ok(entrySource.indexOf("bootstrapContext.clear") < entrySource.indexOf('require("./game/main")'));
  assert.match(entrySource, /__VISUAL_COMPANION_BOOTSTRAP__/);
  assert.match(avatarSource, /context: bootstrapContext/);
  assert.ok(gameSource.indexOf("requestAnimationFrame(resolve)") < gameSource.indexOf("this._loadAvatar()"));
  assert.ok(avatarSource.indexOf("_installLive2dRuntime()") > avatarSource.indexOf("async loadModel(modelUrl)"));
  assert.ok(avatarSource.indexOf('require("../libs/live2dcubismcore.min")') > avatarSource.indexOf("_installLive2dRuntime()"));
});

test("缺少 Intl 的微信真机仍能加载 Pixi 运行时", () => {
  const savedIntl = global.Intl;
  const pixiPath = require.resolve("../libs/pixi.miniprogram");
  try {
    delete global.Intl;
    const { installRuntimeCompat } = require("../core/runtime-compat");
    installRuntimeCompat(global);
    delete require.cache[pixiPath];
    assert.doesNotThrow(() => require(pixiPath));
    assert.equal(typeof global.Intl, "object");
  } finally {
    global.Intl = savedIntl;
    delete require.cache[pixiPath];
  }
});
