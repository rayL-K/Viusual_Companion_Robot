// 入口必须在加载 Pixi/Cubism 前提交一帧，否则低端真机会一直显示微信官方启动页。
const { installRuntimeCompat } = require("./core/runtime-compat");
const runtime = installRuntimeCompat();
const windowInfo = typeof wx.getWindowInfo === "function" ? wx.getWindowInfo() : wx.getSystemInfoSync();
const screenCanvas = wx.createCanvas();
screenCanvas.width = Math.max(1, windowInfo.windowWidth);
screenCanvas.height = Math.max(1, windowInfo.windowHeight);
const bootstrapContext = screenCanvas.getContext("webgl", {
  alpha: false,
  antialias: false,
  premultipliedAlpha: true,
  preserveDrawingBuffer: false,
  powerPreference: "high-performance",
}) || screenCanvas.getContext("experimental-webgl");

if (bootstrapContext) {
  bootstrapContext.viewport(0, 0, screenCanvas.width, screenCanvas.height);
  bootstrapContext.clearColor(0.985, 0.965, 0.925, 1);
  bootstrapContext.clear(bootstrapContext.COLOR_BUFFER_BIT);
}

runtime.__VISUAL_COMPANION_BOOTSTRAP__ = {
  canvas: screenCanvas,
  context: bootstrapContext,
};

setTimeout(() => require("./game/main"), 0);
