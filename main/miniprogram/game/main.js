function reportBootFailure(error) {
  const message = String(error?.message || error || "未知错误");
  console.error("[草莓兔兔] 小游戏启动失败", error);
  wx.showModal?.({
    title: "草莓兔兔启动失败",
    content: `${message}\n\n请截图保留此信息，然后点击确定重试。`,
    showCancel: false,
    confirmText: "重试",
    success: () => wx.restartMiniProgram?.(),
  });
}

try {
  // 保持在保护边界内加载完整运行时；依赖解析失败时真机也能展示明确错误，而非卡在微信启动页。
  const { CompanionGame } = require("./companion-game");
  const runtime = typeof GameGlobal !== "undefined" ? GameGlobal : globalThis;
  const screenCanvas = runtime.__VISUAL_COMPANION_BOOTSTRAP__?.canvas || wx.createCanvas();
  const game = new CompanionGame(screenCanvas);
  game.start().catch(reportBootFailure);
} catch (error) {
  reportBootFailure(error);
}
