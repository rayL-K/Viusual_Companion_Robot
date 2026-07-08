function installRuntimeCompat(target) {
  const runtime = target || (typeof GameGlobal !== "undefined" ? GameGlobal : globalThis);
  // Pixi 7 的压缩产物会直接读取 Intl.Segmenter；部分微信真机没有 Intl 全局。
  if (typeof runtime.Intl === "undefined") runtime.Intl = {};
  return runtime;
}

module.exports = { installRuntimeCompat };
