const { containsPoint, createGameLayout, paginate } = require("./layout");

const COLORS = Object.freeze({
  background: 0xffedf5,
  surface: 0xfffbfd,
  surfaceStrong: 0xffffff,
  border: 0xf0cfdd,
  text: 0x52213d,
  muted: 0x8b6b7d,
  accent: 0xd34e8b,
  accentSoft: 0xf8d8e7,
  success: 0x46aa7a,
  danger: 0xc94f63,
  shadow: 0x6b2748,
});

const PANEL_NAV = Object.freeze([
  ["actions", "动作盘"],
  ["runtime", "运行后端"],
  ["voices", "语音模型"],
  ["device", "设备连接"],
  ["history", "历史记录"],
  ["logs", "运行日志"],
]);

function destroyChildren(container) {
  container.removeChildren().forEach((child) => child.destroy?.({ children: true, texture: true, baseTexture: true }));
}

class GameView {
  constructor(scene, insets = {}) {
    this.PIXI = scene.PIXI;
    this.width = scene.width;
    this.height = scene.height;
    this.layout = createGameLayout(scene.height, insets);
    this.root = new this.PIXI.Container();
    this.hitRegions = [];
    scene.overlayLayer.addChild(this.root);
    this._drawBackground(scene.backgroundLayer);
  }

  render(state) {
    destroyChildren(this.root);
    this.hitRegions = [];
    this._drawHeader(state);
    this._drawConversation(state);
    this._drawControls(state);
    if (state.activePanel) {
      this._drawPanel(state);
    }
  }

  hitTest(x, y) {
    for (let index = this.hitRegions.length - 1; index >= 0; index -= 1) {
      const region = this.hitRegions[index];
      if (containsPoint(region.rect, x, y)) {
        return region.action;
      }
    }
    return null;
  }

  modelBounds() {
    return {
      top: this.layout.header.y + this.layout.header.height + 24,
      bottom: this.layout.bubble.y - 18,
    };
  }

  destroy() {
    destroyChildren(this.root);
    this.root.destroy?.();
  }

  _drawBackground(layer) {
    destroyChildren(layer);
    const graphics = new this.PIXI.Graphics();
    graphics.beginFill(COLORS.background, 1);
    graphics.drawRect(0, 0, this.width, this.height);
    graphics.endFill();
    graphics.beginFill(0xffffff, 0.34);
    graphics.drawCircle(90, 310, 210);
    graphics.drawCircle(680, 650, 250);
    graphics.endFill();
    layer.addChild(graphics);
  }

  _drawHeader(state) {
    const { header } = this.layout;
    this._roundedRect(header, 22, COLORS.surfaceStrong, 0.94, COLORS.border);
    const onlineColor = state.connected ? COLORS.success : COLORS.danger;
    const onlineLabel = state.connected ? "ELF2 在线" : "ELF2 离线";
    this._roundedRect({ x: header.x + 12, y: header.y + 11, width: 174, height: 42 }, 18, onlineColor, 1);
    this._text(onlineLabel, header.x + 99, header.y + 32, {
      size: 22,
      color: 0xffffff,
      anchorX: 0.5,
      anchorY: 0.5,
    });
    this._text("草莓兔兔", this.width / 2, header.y + 22, {
      size: 27,
      color: COLORS.text,
      weight: "600",
      anchorX: 0.5,
    });
    this._text(String(state.deviceHost || "robot.veyralux.org"), this.width / 2, header.y + 48, {
      size: 16,
      color: COLORS.muted,
      anchorX: 0.5,
    });
  }

  _drawConversation(state) {
    const { bubble, input } = this.layout;
    this._roundedRect(bubble, 24, COLORS.surfaceStrong, 0.96, COLORS.border);
    this._text("草莓兔兔", bubble.x + 22, bubble.y + 20, {
      size: 22,
      color: COLORS.accent,
      weight: "600",
    });
    this._text(String(state.replyText || "主人，你好呀！"), bubble.x + 22, bubble.y + 52, {
      size: 25,
      color: COLORS.text,
      width: bubble.width - 44,
      lineHeight: 36,
      maxLines: 2,
    });
    this._text(String(state.statusText || "正在准备……"), bubble.x + 22, bubble.y + bubble.height - 28, {
      size: 17,
      color: COLORS.muted,
      width: bubble.width - 44,
      maxLines: 1,
    });

    this._roundedRect(input, 20, COLORS.surfaceStrong, 1, COLORS.border);
    const inputText = String(state.inputText || "");
    this._text(inputText || "点击输入要说的话", input.x + 22, input.y + input.height / 2, {
      size: 23,
      color: inputText ? COLORS.text : COLORS.muted,
      anchorY: 0.5,
      width: input.width - 44,
      maxLines: 1,
    });
    this._hit(input, { type: "keyboard", field: "chat" });
  }

  _drawControls(state) {
    const [voiceRect, sendRect] = this.layout.primaryButtons;
    const [actionsRect, runtimeRect] = this.layout.secondaryButtons;
    this._button(voiceRect, state.microphoneActive ? "关闭语音对话" : "开启语音对话", {
      fill: state.microphoneActive ? COLORS.success : COLORS.accentSoft,
      color: state.microphoneActive ? 0xffffff : COLORS.text,
      action: { type: "toggle-microphone" },
    });
    this._button(sendRect, state.sending ? "正在思考……" : "发送消息", {
      fill: COLORS.accent,
      color: 0xffffff,
      disabled: Boolean(state.sending),
      action: { type: "send" },
    });
    this._button(actionsRect, "动作盘", {
      fill: COLORS.surfaceStrong,
      color: COLORS.text,
      action: { type: "open-panel", panel: "actions" },
    });
    this._button(runtimeRect, "运行后端", {
      fill: COLORS.surfaceStrong,
      color: COLORS.text,
      action: { type: "open-panel", panel: "runtime" },
    });
  }

  _drawPanel(state) {
    const panel = this.layout.panel;
    this._roundedRect(panel, 28, COLORS.surfaceStrong, 0.985, COLORS.border);
    this._hit(panel, { type: "noop" });
    this._text(this._panelTitle(state.activePanel), panel.x + 28, panel.y + 28, {
      size: 31,
      color: COLORS.text,
      weight: "600",
    });
    this._button({ x: panel.x + panel.width - 88, y: panel.y + 18, width: 60, height: 50 }, "×", {
      fill: COLORS.accentSoft,
      color: COLORS.text,
      size: 32,
      action: { type: "close-panel" },
    });

    const content = {
      x: panel.x + 28,
      y: panel.y + 94,
      width: panel.width - 56,
      height: panel.height - 300,
    };
    if (state.activePanel === "actions") this._drawActionsPanel(state, content);
    else if (state.activePanel === "runtime") this._drawRuntimePanel(state, content);
    else if (state.activePanel === "voices") this._drawVoicesPanel(state, content);
    else if (state.activePanel === "device") this._drawDevicePanel(state, content);
    else if (state.activePanel === "history") this._drawHistoryPanel(state, content);
    else if (state.activePanel === "logs") this._drawLogsPanel(state, content);

    this._drawPanelNavigation(panel, state.activePanel);
  }

  _drawActionsPanel(state, rect) {
    const page = paginate(state.actions || [], state.actionPage, 9);
    const gap = 12;
    const cellWidth = (rect.width - gap * 2) / 3;
    const cellHeight = 76;
    page.items.forEach((action, index) => {
      const column = index % 3;
      const row = Math.floor(index / 3);
      this._button({
        x: rect.x + column * (cellWidth + gap),
        y: rect.y + row * (cellHeight + gap),
        width: cellWidth,
        height: cellHeight,
      }, action.label, {
        fill: COLORS.accentSoft,
        color: COLORS.text,
        size: 22,
        action: { type: "trigger-action", name: action.name },
      });
    });
    const pagerY = rect.y + 3 * (cellHeight + gap) + 18;
    this._button({ x: rect.x, y: pagerY, width: 130, height: 54 }, "上一页", {
      fill: COLORS.surface,
      color: COLORS.text,
      disabled: page.page === 0,
      action: { type: "action-page", delta: -1 },
    });
    this._text(`${page.page + 1} / ${page.pageCount}`, rect.x + rect.width / 2, pagerY + 27, {
      size: 21,
      color: COLORS.muted,
      anchorX: 0.5,
      anchorY: 0.5,
    });
    this._button({ x: rect.x + rect.width - 130, y: pagerY, width: 130, height: 54 }, "下一页", {
      fill: COLORS.surface,
      color: COLORS.text,
      disabled: page.page >= page.pageCount - 1,
      action: { type: "action-page", delta: 1 },
    });
  }

  _drawRuntimePanel(state, rect) {
    const runtime = state.runtime || {};
    const rows = [
      ["控制服务", runtime.control],
      ["本地识别", runtime.asr],
      ["本地语音", runtime.tts],
      ["本地视觉", runtime.vision],
    ];
    rows.forEach(([label, value], index) => {
      const y = rect.y + index * 72;
      this._text(label, rect.x + 8, y + 26, { size: 23, color: COLORS.text, weight: "600" });
      this._text(String(value || "待检测"), rect.x + 190, y + 26, {
        size: 21,
        color: COLORS.muted,
        width: rect.width - 206,
        maxLines: 1,
      });
    });
    this._button({ x: rect.x, y: rect.y + 292, width: rect.width, height: 62 }, state.visionActive ? "关闭环境视觉" : "开启环境视觉", {
      fill: state.visionActive ? COLORS.success : COLORS.accent,
      color: 0xffffff,
      action: { type: "toggle-vision" },
    });
    this._button({ x: rect.x, y: rect.y + 370, width: rect.width, height: 62 }, "重新检测板端模型", {
      fill: COLORS.accentSoft,
      color: COLORS.text,
      action: { type: "refresh-runtime" },
    });
  }

  _drawVoicesPanel(state, rect) {
    const voices = (state.voices || []).slice(0, 5);
    if (!voices.length) {
      this._text("正在读取板端本地语音模型……", rect.x, rect.y + 24, { size: 23, color: COLORS.muted });
    }
    voices.forEach((voice, index) => {
      const selected = voice.id === state.selectedVoice;
      const y = rect.y + index * 82;
      this._button({ x: rect.x, y, width: rect.width, height: 68 }, `${selected ? "✓ " : ""}${voice.name}`, {
        fill: selected ? COLORS.accent : COLORS.surface,
        color: selected ? 0xffffff : COLORS.text,
        size: 22,
        action: { type: "select-voice", id: voice.id },
      });
    });
    this._button({ x: rect.x, y: rect.y + Math.max(voices.length * 82 + 12, 260), width: rect.width, height: 60 }, "试听当前语音", {
      fill: COLORS.accentSoft,
      color: COLORS.text,
      action: { type: "preview-voice" },
    });
  }

  _drawDevicePanel(state, rect) {
    const config = state.deviceConfig || {};
    this._text("连接方式", rect.x, rect.y + 16, { size: 22, color: COLORS.muted });
    this._button({ x: rect.x, y: rect.y + 52, width: (rect.width - 14) / 2, height: 62 }, "公网连接", {
      fill: config.mode !== "local" ? COLORS.accent : COLORS.surface,
      color: config.mode !== "local" ? 0xffffff : COLORS.text,
      action: { type: "set-connection-mode", mode: "public" },
    });
    this._button({ x: rect.x + (rect.width + 14) / 2, y: rect.y + 52, width: (rect.width - 14) / 2, height: 62 }, "局域网连接", {
      fill: config.mode === "local" ? COLORS.accent : COLORS.surface,
      color: config.mode === "local" ? 0xffffff : COLORS.text,
      action: { type: "set-connection-mode", mode: "local" },
    });
    const addressLabel = config.mode === "local"
      ? `${config.host || ""}:${config.controlPort || ""}`
      : config.publicUrl || "https://robot.veyralux.org";
    this._text("当前入口", rect.x, rect.y + 155, { size: 22, color: COLORS.muted });
    this._roundedRect({ x: rect.x, y: rect.y + 190, width: rect.width, height: 66 }, 18, COLORS.surface, 1, COLORS.border);
    this._text(addressLabel, rect.x + 18, rect.y + 223, {
      size: 21,
      color: COLORS.text,
      anchorY: 0.5,
      width: rect.width - 36,
      maxLines: 1,
    });
    if (config.mode === "local") {
      this._button({ x: rect.x, y: rect.y + 280, width: rect.width, height: 58 }, "编辑局域网地址", {
        fill: COLORS.accentSoft,
        color: COLORS.text,
        action: { type: "keyboard", field: "host" },
      });
    }
    this._button({ x: rect.x, y: rect.y + 360, width: rect.width, height: 62 }, "保存并重新连接", {
      fill: COLORS.accent,
      color: 0xffffff,
      action: { type: "save-device" },
    });
  }

  _drawHistoryPanel(state, rect) {
    const history = (state.history || []).slice(0, 4);
    if (!history.length) {
      this._text("还没有对话记录。", rect.x, rect.y + 24, { size: 23, color: COLORS.muted });
    }
    history.forEach((entry, index) => {
      const y = rect.y + index * 112;
      this._text(`你：${entry.user}`, rect.x, y + 8, {
        size: 20,
        color: COLORS.text,
        width: rect.width,
        maxLines: 1,
      });
      this._text(`兔兔：${entry.robot}`, rect.x, y + 42, {
        size: 20,
        color: COLORS.muted,
        width: rect.width,
        maxLines: 2,
        lineHeight: 29,
      });
    });
  }

  _drawLogsPanel(state, rect) {
    const logs = (state.logs || []).slice(0, 8);
    if (!logs.length) {
      this._text("暂无运行日志。", rect.x, rect.y + 24, { size: 23, color: COLORS.muted });
    }
    logs.forEach((entry, index) => {
      this._text(`${entry.time}  ${entry.message}`, rect.x, rect.y + index * 48 + 8, {
        size: 18,
        color: index === 0 ? COLORS.text : COLORS.muted,
        width: rect.width,
        maxLines: 1,
      });
    });
  }

  _drawPanelNavigation(panel, activePanel) {
    const gap = 10;
    const cellWidth = (panel.width - 56 - gap * 2) / 3;
    const cellHeight = 52;
    const startX = panel.x + 28;
    const startY = panel.y + panel.height - 154;
    PANEL_NAV.forEach(([id, label], index) => {
      const column = index % 3;
      const row = Math.floor(index / 3);
      this._button({
        x: startX + column * (cellWidth + gap),
        y: startY + row * (cellHeight + gap),
        width: cellWidth,
        height: cellHeight,
      }, label, {
        fill: activePanel === id ? COLORS.accent : COLORS.surface,
        color: activePanel === id ? 0xffffff : COLORS.text,
        size: 19,
        action: { type: "open-panel", panel: id },
      });
    });
  }

  _panelTitle(id) {
    return Object.fromEntries(PANEL_NAV)[id] || "控制面板";
  }

  _button(rect, label, options = {}) {
    const disabled = Boolean(options.disabled);
    this._roundedRect(rect, Math.min(20, rect.height / 2), options.fill ?? COLORS.surface, disabled ? 0.5 : 1, COLORS.border);
    this._text(label, rect.x + rect.width / 2, rect.y + rect.height / 2, {
      size: options.size || 24,
      color: options.color ?? COLORS.text,
      weight: "600",
      anchorX: 0.5,
      anchorY: 0.5,
      width: rect.width - 18,
      maxLines: 1,
    });
    if (!disabled && options.action) {
      this._hit(rect, options.action);
    }
  }

  _roundedRect(rect, radius, fill, alpha = 1, border = null) {
    const graphics = new this.PIXI.Graphics();
    if (border !== null) graphics.lineStyle(2, border, 0.8);
    graphics.beginFill(fill, alpha);
    graphics.drawRoundedRect(rect.x, rect.y, rect.width, rect.height, radius);
    graphics.endFill();
    this.root.addChild(graphics);
    return graphics;
  }

  _text(value, x, y, options = {}) {
    const style = {
      fontFamily: "sans-serif",
      fontSize: options.size || 22,
      fontWeight: options.weight || "400",
      fill: options.color ?? COLORS.text,
      align: options.align || "left",
      lineHeight: options.lineHeight || Math.round((options.size || 22) * 1.35),
      wordWrap: Boolean(options.width),
      wordWrapWidth: options.width || 0,
      breakWords: true,
    };
    let textValue = String(value ?? "");
    if (options.maxLines && options.width) {
      const approxChars = Math.max(1, Math.floor(options.width / ((options.size || 22) * 0.92)));
      const limit = approxChars * options.maxLines;
      if (textValue.length > limit) textValue = `${textValue.slice(0, Math.max(1, limit - 1))}…`;
    }
    const text = new this.PIXI.Text(textValue, style);
    text.x = x;
    text.y = y;
    text.anchor?.set?.(options.anchorX || 0, options.anchorY || 0);
    this.root.addChild(text);
    return text;
  }

  _hit(rect, action) {
    this.hitRegions.push({ rect: { ...rect }, action });
  }
}

module.exports = { COLORS, GameView, PANEL_NAV };
