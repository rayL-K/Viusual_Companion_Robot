const { createPIXI } = require("../libs/pixi.miniprogram");
const unsafeEval = require("../libs/unsafeEval");

// 模型说明将 Ctrl+Shift 映射为水印开关；这些默认值必须覆盖动作和表情。
const PROTECTED_MODEL_PARAMETERS = Object.freeze({
  Param44: 0,
  Param59: 0,
  Param60: 0,
  Param61: 0,
  Param62: 0,
  Param63: 0,
  Param64: 0,
  Param65: 0,
  Param78: 0,
  Param261: 1,
});
const PROTECTED_MODEL_PARAMETER_ENTRIES = Object.entries(PROTECTED_MODEL_PARAMETERS);

class AvatarController {
  constructor(options = {}) {
    this.onStatus = options.onStatus || (() => {});
    this.PIXI = null;
    this.canvas = null;
    this.renderer = null;
    this.stage = null;
    this.backgroundLayer = null;
    this.modelLayer = null;
    this.overlayLayer = null;
    this.stageWidth = 0;
    this.stageHeight = 0;
    this.modelBounds = null;
    this.model = null;
    this.frameId = 0;
    this.actionTimers = new Set();
    this.heldParameters = new Map();
    this.pointer = { x: 0, y: 0 };
    this.pointerTarget = { x: 0, y: 0 };
    this.mouthSyncActive = false;
    this.mouthPhase = 0;
    this.lastFrameAt = 0;
    this.running = false;
    this.measuredFps = 0;
    this.fpsFrames = 0;
    this.fpsStartedAt = 0;
    this.live2dRuntimeInstalled = false;
    this._boundRenderFrame = (timestamp) => this._renderFrame(timestamp);
  }

  async initialize(canvas, viewport, modelUrl) {
    this.setup(canvas, viewport);
    await this.loadModel(modelUrl);
    this.onStatus("Live2D 模型已加载。");
  }

  setup(canvas, viewport) {
    if (!canvas) {
      throw new Error("未获取到小程序 WebGL Canvas。");
    }
    this.canvas = canvas;
    const stageWidth = 750;
    const stageHeight = Math.max(900, Math.round(stageWidth * viewport.height / viewport.width));
    this.stageWidth = stageWidth;
    this.stageHeight = stageHeight;
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    this._installCanvasCompatibility(canvas);
    this._installAnimationFrame(canvas);
    if (typeof wx !== "undefined") wx.setPreferredFramesPerSecond?.(60);
    this.PIXI = createPIXI(canvas, stageWidth);
    unsafeEval(this.PIXI);
    const runtime = typeof GameGlobal !== "undefined" ? GameGlobal : globalThis;
    const bootstrapContext = runtime.__VISUAL_COMPANION_BOOTSTRAP__?.context || undefined;
    this.renderer = this.PIXI.autoDetectRenderer({
      width: stageWidth,
      height: stageHeight,
      backgroundAlpha: 0,
      premultipliedAlpha: true,
      preserveDrawingBuffer: false,
      antialias: false,
      powerPreference: "high-performance",
      view: canvas,
      context: bootstrapContext,
    });
    if (this.PIXI.Ticker?.shared) {
      this.PIXI.Ticker.shared.maxFPS = 60;
      this.PIXI.Ticker.shared.minFPS = 20;
    }
    this.stage = new this.PIXI.Container();
    this.backgroundLayer = new this.PIXI.Container();
    this.modelLayer = new this.PIXI.Container();
    this.overlayLayer = new this.PIXI.Container();
    this.stage.addChild(this.backgroundLayer);
    this.stage.addChild(this.modelLayer);
    this.stage.addChild(this.overlayLayer);
    this.resume();
    return this.getScene();
  }

  async loadModel(modelUrl) {
    if (!this.PIXI || !this.modelLayer) {
      throw new Error("Live2D 渲染器尚未初始化。");
    }
    this.model?.destroy?.({ children: true, texture: false, baseTexture: false });
    this.model = null;
    this.onStatus("正在从 ELF2 加载 Live2D 模型……");
    this._installLive2dRuntime();
    this.model = await this.PIXI.live2d.Live2DModel.from(modelUrl, { autoInteract: false });
    this._fitModel(this.stageWidth, this.stageHeight);
    this.modelLayer.addChild(this.model);
    return this.model;
  }

  _installLive2dRuntime() {
    if (this.live2dRuntimeInstalled) return;
    // Cubism 运行时解析成本较高，必须等首帧 UI 已绘制后再加载，避免真机长期停在启动页。
    const live2dFramework = require("../libs/live2d.min");
    const Live2DCubismCore = require("../libs/live2dcubismcore.min");
    const installCubism4 = require("../libs/cubism4");
    const installPixiLive2d = require("../libs/pixi-live2d-display");
    installCubism4(this.PIXI, Live2DCubismCore);
    installPixiLive2d(this.PIXI, live2dFramework, Live2DCubismCore);
    this.live2dRuntimeInstalled = true;
  }

  getScene() {
    return {
      PIXI: this.PIXI,
      stage: this.stage,
      backgroundLayer: this.backgroundLayer,
      modelLayer: this.modelLayer,
      overlayLayer: this.overlayLayer,
      width: this.stageWidth,
      height: this.stageHeight,
    };
  }

  setModelBounds(bounds) {
    if (!bounds || !Number.isFinite(bounds.top) || !Number.isFinite(bounds.bottom) || bounds.bottom <= bounds.top) {
      this.modelBounds = null;
    } else {
      this.modelBounds = { top: bounds.top, bottom: bounds.bottom };
    }
    if (this.model) {
      this._fitModel(this.stageWidth, this.stageHeight);
    }
  }

  async applyPlan(plan, actionsByName) {
    this.clearScheduledActions();
    if (plan.actions.length) {
      plan.actions.forEach((control) => {
        const action = actionsByName.get(control.name);
        if (!action) {
          return;
        }
        const timer = setTimeout(() => {
          this.actionTimers.delete(timer);
          this.triggerAction(action, control.mode, control.durationMs);
        }, control.delayMs);
        this.actionTimers.add(timer);
      });
    } else if (plan.expression) {
      await this.applyExpression(plan.expression);
    }
    if (plan.motion) {
      await this.applyMotion(plan.motion);
    }
    this.applyParameters(plan.parameters);
  }

  async triggerAction(action, mode = "pulse", durationMs = 2600) {
    if (!this.model || !action) {
      return;
    }
    if (mode === "off") {
      this._releaseParameters(action.parameters);
      return;
    }
    if (action.expression) {
      await this.applyExpression(action.expression);
    }
    if (action.motion) {
      await this.applyMotion(action.motion);
    }
    this._holdParameters(action.parameters);
    if (mode === "pulse") {
      const timer = setTimeout(() => {
        this.actionTimers.delete(timer);
        this._releaseParameters(action.parameters);
      }, durationMs || action.durationMs || 2600);
      this.actionTimers.add(timer);
    }
  }

  async applyExpression(name) {
    if (name && typeof this.model?.expression === "function") {
      await this.model.expression(name);
    }
  }

  async applyMotion(name) {
    if (name && typeof this.model?.motion === "function") {
      await this.model.motion(name, 0);
    }
  }

  applyParameters(parameters = {}) {
    ["ParamMouthForm", "ParamMouthOpenY"].forEach((id) => {
      const value = Number(parameters[id]);
      if (Number.isFinite(value)) {
        this.heldParameters.set(id, value);
      }
    });
  }

  setPointer(clientX, clientY, bounds) {
    if (!bounds?.width || !bounds?.height) {
      return;
    }
    this.pointerTarget.x = Math.max(-1, Math.min(1, (clientX - bounds.left) / bounds.width * 2 - 1));
    this.pointerTarget.y = Math.max(-1, Math.min(1, (clientY - bounds.top) / bounds.height * 2 - 1));
  }

  setMouthSync(active) {
    this.mouthSyncActive = Boolean(active);
    if (!active) {
      this.heldParameters.delete("ParamMouthOpenY");
      this._setParameter("ParamMouthOpenY", 0);
    }
  }

  dispatchTouch(event) {
    this.PIXI?.dispatchEvent?.(event);
  }

  clearScheduledActions() {
    this.actionTimers.forEach((timer) => clearTimeout(timer));
    this.actionTimers.clear();
  }

  pause() {
    this.running = false;
    if (this.frameId && this.canvas?.cancelAnimationFrame) {
      this.canvas.cancelAnimationFrame(this.frameId);
    }
    this.frameId = 0;
    this.lastFrameAt = 0;
  }

  resume() {
    if (this.running || !this.renderer || !this.stage || !this.canvas) return;
    this.running = true;
    this.lastFrameAt = 0;
    this.frameId = this.canvas.requestAnimationFrame(this._boundRenderFrame);
  }

  destroy() {
    this.clearScheduledActions();
    this.pause();
    this.model?.destroy?.({ children: true, texture: false, baseTexture: false });
    this.renderer?.destroy?.(true);
    this.model = null;
    this.renderer = null;
    this.stage = null;
    this.backgroundLayer = null;
    this.modelLayer = null;
    this.overlayLayer = null;
  }

  _fitModel(stageWidth, stageHeight) {
    this.model.anchor?.set?.(0.5, 0.5);
    const rawWidth = Math.max(1, this.model.width || stageWidth);
    const rawHeight = Math.max(1, this.model.height || stageHeight);
    const top = this.modelBounds?.top ?? stageHeight * 0.05;
    const bottom = this.modelBounds?.bottom ?? stageHeight * 0.95;
    const availableHeight = Math.max(1, bottom - top);
    const scale = Math.min(stageWidth * 0.92 / rawWidth, availableHeight / rawHeight);
    this.model.scale.set(scale);
    this.model.x = stageWidth * 0.5;
    this.model.y = top + availableHeight * 0.5;
  }

  _installAnimationFrame(canvas) {
    const runtime = typeof GameGlobal !== "undefined" ? GameGlobal : globalThis;
    const requestFrame = canvas.requestAnimationFrame
      || runtime.requestAnimationFrame
      || ((callback) => setTimeout(() => callback(Date.now()), 16));
    const cancelFrame = canvas.cancelAnimationFrame
      || runtime.cancelAnimationFrame
      || clearTimeout;
    if (!canvas.requestAnimationFrame) {
      Object.defineProperty(canvas, "requestAnimationFrame", {
        configurable: true,
        value: requestFrame.bind?.(runtime) || requestFrame,
      });
    }
    if (!canvas.cancelAnimationFrame) {
      Object.defineProperty(canvas, "cancelAnimationFrame", {
        configurable: true,
        value: cancelFrame.bind?.(runtime) || cancelFrame,
      });
    }
  }

  _installCanvasCompatibility(canvas) {
    try {
      Object.defineProperty(canvas, "parentElement", {
        configurable: true,
        value: true,
        writable: true,
      });
    } catch (_error) {
      // 旧版小程序 Canvas 原本即可写入；小游戏 Canvas 需要上述自有属性遮蔽只读 getter。
    }
    if (!canvas.createImage && typeof wx.createImage === "function") {
      Object.defineProperty(canvas, "createImage", {
        configurable: true,
        value: wx.createImage.bind(wx),
      });
    }
    if (typeof wx.createOffscreenCanvas !== "function" && typeof wx.createCanvas === "function") {
      wx.createOffscreenCanvas = ({ width = 1, height = 1 } = {}) => {
        const offscreen = wx.createCanvas();
        offscreen.width = width;
        offscreen.height = height;
        return offscreen;
      };
    }
  }

  _holdParameters(parameters = {}) {
    Object.entries(parameters).forEach(([id, rawValue]) => {
      const value = Number(rawValue);
      if (Number.isFinite(value)) {
        this.heldParameters.set(id, value);
      }
    });
  }

  _releaseParameters(parameters = {}) {
    Object.keys(parameters).forEach((id) => {
      this.heldParameters.delete(id);
      this._setParameter(id, PROTECTED_MODEL_PARAMETERS[id] ?? 0);
    });
  }

  _applyProtectedModelParameters() {
    PROTECTED_MODEL_PARAMETER_ENTRIES.forEach(([id, value]) => {
      this._setParameter(id, value);
    });
  }

  _setParameter(id, value) {
    const coreModel = this.model?.internalModel?.coreModel;
    if (coreModel && typeof coreModel.setParameterValueById === "function") {
      coreModel.setParameterValueById(id, value);
    }
  }

  _renderFrame(timestamp = Date.now()) {
    if (!this.running || !this.renderer || !this.stage || !this.canvas) {
      return;
    }
    const deltaMs = this.lastFrameAt
      ? Math.max(1, Math.min(50, timestamp - this.lastFrameAt))
      : 1000 / 60;
    this.lastFrameAt = timestamp;
    const pointerSmoothing = 1 - Math.exp(-deltaMs / 84);
    this.pointer.x += (this.pointerTarget.x - this.pointer.x) * pointerSmoothing;
    this.pointer.y += (this.pointerTarget.y - this.pointer.y) * pointerSmoothing;
    const seconds = timestamp / 1000;
    const naturalX = Math.sin(seconds * 0.73) * 3.8 + Math.sin(seconds * 1.31) * 1.2;
    const naturalY = Math.sin(seconds * 0.89 + 0.7) * 2.7;
    this._setParameter("ParamAngleX", naturalX + this.pointer.x * 12);
    this._setParameter("ParamAngleY", naturalY - this.pointer.y * 9);
    this._setParameter("ParamAngleZ", Math.sin(seconds * 0.51 + 1.4) * 1.8);
    this._setParameter("ParamBodyAngleX", Math.sin(seconds * 0.43) * 2.2 + this.pointer.x * 4);
    this._setParameter("ParamBreath", Math.sin(seconds * 2.05) * 0.5 + 0.5);
    const eyeOpen = this._blinkValue(seconds);
    this._setParameter("ParamEyeLOpen", eyeOpen);
    this._setParameter("ParamEyeROpen", eyeOpen);
    this.heldParameters.forEach((value, id) => this._setParameter(id, value));
    if (this.mouthSyncActive) {
      this.mouthPhase += deltaMs * 0.0192;
      const mouthWave = Math.abs(Math.sin(this.mouthPhase) + Math.sin(this.mouthPhase * 0.47) * 0.28);
      this._setParameter("ParamMouthOpenY", Math.min(0.95, 0.16 + mouthWave * 0.66));
      this._setParameter("ParamMouthForm", Math.sin(this.mouthPhase * 0.31) * 0.22);
    }
    this._applyProtectedModelParameters();
    this.renderer.render(this.stage);
    this._sampleFps(timestamp);
    this.frameId = this.canvas.requestAnimationFrame(this._boundRenderFrame);
  }

  _blinkValue(seconds) {
    const cycle = seconds % 4.7;
    if (cycle >= 0.18) return 1;
    return Math.max(0.08, Math.abs(cycle - 0.09) / 0.09);
  }

  _sampleFps(timestamp) {
    if (!this.fpsStartedAt) this.fpsStartedAt = timestamp;
    this.fpsFrames += 1;
    const elapsed = timestamp - this.fpsStartedAt;
    if (elapsed < 2000) return;
    this.measuredFps = this.fpsFrames * 1000 / elapsed;
    this.fpsFrames = 0;
    this.fpsStartedAt = timestamp;
  }
}

module.exports = { AvatarController };
