const { ACTIONS } = require("../core/actions");
const { DeviceApiClient } = require("../core/api-client");
const { AudioController } = require("../core/audio-controller");
const { AvatarController } = require("../core/avatar-controller");
const { displayDeviceAddress, loadDeviceConfig, saveDeviceConfig } = require("../core/config");
const { errorMessage } = require("../core/error-message");
const { DEFAULT_SPEECH_RATE, normalizePlan } = require("../core/protocol");
const { PerceptionController } = require("../core/perception-controller");
const { GameView } = require("./view");

const HISTORY_KEY = "visual-companion.chat-history.v1";
const MODEL_PATH = "/live2d/Strawberry_Rabbit/Strawberry_Rabbit.mobile-1024-r2.model3.json";

function windowInfo() {
  return typeof wx.getWindowInfo === "function" ? wx.getWindowInfo() : wx.getSystemInfoSync();
}

function touchPoint(event) {
  const touch = event.changedTouches?.[0] || event.touches?.[0];
  if (!touch) return null;
  return {
    x: touch.clientX ?? touch.x ?? touch.pageX,
    y: touch.clientY ?? touch.y ?? touch.pageY,
  };
}

class CompanionGame {
  constructor(screenCanvas) {
    this.canvas = screenCanvas;
    this.window = windowInfo();
    this.deviceConfig = loadDeviceConfig();
    this.actionsByName = new Map(ACTIONS.map((action) => [action.name, action]));
    this.api = new DeviceApiClient(() => this.deviceConfig);
    this.state = {
      connected: false,
      deviceHost: displayDeviceAddress(this.deviceConfig),
      deviceConfig: { ...this.deviceConfig },
      inputText: "",
      replyText: "主人，你好呀！我是草莓兔兔，今天好开心见到你！",
      statusText: "正在连接 ELF2……",
      sending: false,
      microphoneActive: false,
      visionActive: false,
      visionContext: { enabled: false },
      activePanel: "",
      actionPage: 0,
      actions: ACTIONS,
      voices: [],
      selectedVoice: "",
      speechRatePercent: Math.round(DEFAULT_SPEECH_RATE * 100),
      runtime: { control: "待检测", asr: "待检测", tts: "待检测", vision: "待检测" },
      history: this._loadHistory(),
      logs: [],
    };
    this.keyboardMode = null;
    this.replyTimer = null;
    this.idleTimer = null;
    this.touchStart = null;
    this.transcriptionRunning = false;
    this.renderFrameId = 0;
    this.avatar = new AvatarController({ onStatus: (message) => this.setStatus(message) });
    const scene = this.avatar.setup(this.canvas, {
      width: this.window.windowWidth,
      height: this.window.windowHeight,
    });
    const stageScale = scene.height / this.window.windowHeight;
    const safeTop = (this.window.safeArea?.top || 0) * stageScale;
    const safeBottom = Math.max(0, this.window.windowHeight - (this.window.safeArea?.bottom || this.window.windowHeight)) * stageScale;
    this.view = new GameView(scene, { top: safeTop, bottom: safeBottom });
    this.avatar.setModelBounds(this.view.modelBounds());
    this.stageWidth = scene.width;
    this.stageHeight = scene.height;
    this.view.render(this.state);
    this.perception = new PerceptionController({
      api: this.api,
      onUpdate: (visionContext) => this.update({
        visionActive: visionContext.enabled === true,
        visionContext,
      }),
      onStatus: (message) => this.setStatus(message),
    });
    this._setupAudio();
    this._bindInput();
    this._bindLifecycle();
  }

  async start() {
    const connection = this.connectDevice();
    // 先让 Pixi UI 提交一帧，微信才会撤下启动页；随后再解析较重的 Cubism 运行时。
    await new Promise((resolve) => this.canvas.requestAnimationFrame(resolve));
    await Promise.allSettled([this._loadAvatar(), connection]);
  }

  update(patch) {
    Object.assign(this.state, patch);
    if (this.renderFrameId) return;
    this.renderFrameId = this.canvas.requestAnimationFrame(() => {
      this.renderFrameId = 0;
      this.view.render(this.state);
    });
  }

  setStatus(message) {
    this.update({ statusText: String(message || "") });
  }

  log(message) {
    const now = new Date();
    const time = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}:${String(now.getSeconds()).padStart(2, "0")}`;
    const normalizedMessage = String(message);
    console.info(`[CompanionGame] ${normalizedMessage}`);
    const logs = [{ id: `${Date.now()}-${Math.random()}`, time, message: normalizedMessage }, ...this.state.logs].slice(0, 80);
    this.update({ logs });
  }

  async connectDevice() {
    this.setStatus(`正在连接 ${displayDeviceAddress(this.deviceConfig)}……`);
    try {
      const health = await this.api.health();
      if (!health?.ok) throw new Error(health?.error || "ELF2 控制服务未就绪");
      this.update({ connected: true, deviceHost: displayDeviceAddress(this.deviceConfig) });
      this.setStatus(`ELF2 控制服务已连接（${health.version || "unknown"}）。`);
      this.log("ELF2 控制服务连接成功");
      await Promise.all([
        this.loadVoices().catch((error) => this.log(`语音列表加载失败：${error.message}`)),
        this.refreshRuntime().catch((error) => this.log(`运行状态加载失败：${error.message}`)),
      ]);
    } catch (error) {
      this.update({ connected: false });
      const detail = errorMessage(error, "公网请求失败");
      this.setStatus(`ELF2 连接失败：${detail}`);
      this.log(`ELF2 连接失败：${detail}`);
    }
  }

  async submitText(text, source = "text") {
    const cleanText = String(text || "").trim();
    if (!cleanText || this.state.sending) return;
    this.audio?.stopPlayback();
    this.update({ inputText: "", sending: true, statusText: "ELF2 正在思考……" });
    this.log(`${source === "speech" ? "语音" : "文本"}输入：${cleanText.slice(0, 80)}`);
    try {
      const vision = this.perception.getContext();
      const rawPlan = await this.api.chat(cleanText, this.state.speechRatePercent / 100, vision);
      const plan = normalizePlan(rawPlan, ACTIONS);
      this._streamReply(plan.text);
      await this.avatar.applyPlan(plan, this.actionsByName);
      this._addHistory(cleanText, plan.text);
      if (this.audio) {
        await this.audio.playSpeech({ text: plan.text, rate: plan.speech.rate, voice: this.state.selectedVoice });
      }
      this.log(`控制计划：${plan.expression || "无表情"} / ${plan.motion || "无动作"}`);
    } catch (error) {
      this.setStatus(`对话失败：${error.message}`);
      this.log(`对话失败：${error.message}`);
    } finally {
      this.update({ sending: false });
    }
  }

  async handleAudioSegment(pcm, speakerFrames = [], realtimeResult = null) {
    if (this.transcriptionRunning) {
      realtimeResult?.catch?.(() => {});
      this.log("语音片段已丢弃：识别任务仍在运行");
      return;
    }
    this.transcriptionRunning = true;
    this.setStatus("正在 ELF2 上使用本地 SenseVoice 识别……");
    try {
      const speakerPromise = speakerFrames.length >= 4
        ? this.api.activeSpeaker(pcm, speakerFrames).catch((error) => {
          this.log(`主动说话人判断失败：${error.message}`);
          return null;
        })
        : Promise.resolve(null);
      const transcriptionPromise = realtimeResult
        ? Promise.resolve(realtimeResult).catch((error) => {
          this.log(`实时语音识别失败，改用整段识别：${error.message}`);
          return this.api.transcribe(pcm);
        })
        : this.api.transcribe(pcm);
      const [result, speakerResult] = await Promise.all([transcriptionPromise, speakerPromise]);
      this.perception.applyActiveSpeaker(speakerResult);
      const text = String(result.text || "").trim();
      if (!text) {
        this.setStatus(result.speech_detected ? "检测到语音，但未识别出文字。" : "未检测到有效语音。");
        return;
      }
      await this.submitText(text, "speech");
    } catch (error) {
      this.setStatus(`语音识别失败：${error.message}`);
      this.log(`语音识别失败：${error.message}`);
    } finally {
      this.transcriptionRunning = false;
    }
  }

  async loadVoices() {
    const config = await this.api.voices();
    const voices = Object.entries(config.models || {}).map(([id, voice]) => ({
      id,
      name: voice.display_name || id,
      description: voice.description || voice.backend || "",
    }));
    const selectedVoice = voices.some((voice) => voice.id === config.active) ? config.active : voices[0]?.id || "";
    this.update({ voices, selectedVoice });
  }

  async selectVoice(id) {
    const previousVoice = this.state.selectedVoice;
    this.update({ selectedVoice: id });
    try {
      const result = await this.api.request("/tts-runtime", {
        method: "POST",
        data: { voice: id },
        header: { "Content-Type": "application/json" },
        timeout: 120000,
      });
      if (!result.ok) throw new Error(result.error || "语音模型激活失败");
      this.setStatus(`${result.backend || "本地语音"} 已就绪。`);
    } catch (error) {
      this.update({ selectedVoice: previousVoice });
      this.setStatus(`语音切换失败：${error.message}`);
    }
  }

  async refreshRuntime() {
    this.update({ runtime: { control: "检测中", asr: "检测中", tts: "检测中", vision: "检测中" } });
    const check = async (path) => {
      try {
        const result = await this.api.request(path, { timeout: 15000 });
        return result.ok === false ? result.error || "未就绪" : result.backend || result.service || "已就绪";
      } catch (error) {
        return `不可用：${error.message}`;
      }
    };
    const [control, asr, tts, vision] = await Promise.all([
      check("/health"),
      check("/asr-health"),
      check(`/tts-health?voice=${encodeURIComponent(this.state.selectedVoice)}`),
      this.api.visionHealth().then(
        (result) => result.backend || "已就绪",
        (error) => `不可用：${error.message}`,
      ),
    ]);
    this.update({ runtime: { control, asr, tts, vision } });
  }

  async dispatch(action) {
    if (!action || action.type === "noop") return;
    if (action.type === "keyboard") this._openKeyboard(action.field);
    else if (action.type === "send") {
      if (this.state.inputText.trim()) await this.submitText(this.state.inputText);
      else this._openKeyboard("chat");
    } else if (action.type === "toggle-microphone") this._toggleMicrophone();
    else if (action.type === "toggle-vision") this._toggleVision();
    else if (action.type === "open-panel") this.update({ activePanel: action.panel });
    else if (action.type === "close-panel") this.update({ activePanel: "" });
    else if (action.type === "trigger-action") this._triggerAction(action.name);
    else if (action.type === "action-page") this._changeActionPage(action.delta);
    else if (action.type === "refresh-runtime") await this.refreshRuntime();
    else if (action.type === "select-voice") await this.selectVoice(action.id);
    else if (action.type === "preview-voice") await this._previewVoice();
    else if (action.type === "set-connection-mode") this._setConnectionMode(action.mode);
    else if (action.type === "save-device") await this._saveDevice();
  }

  _setupAudio() {
    if (typeof wx.getRecorderManager !== "function") {
      this.audio = null;
      this.log("当前微信版本不支持录音管理器，可使用文字对话");
      return;
    }
    try {
      this.audio = new AudioController({
        api: this.api,
        onSegment: (pcm, realtimeResult) => this.handleAudioSegment(
          pcm,
          this.perception.finishSpeakerBurst(),
          realtimeResult,
        ),
        onSpeechStart: () => this.perception.startSpeakerBurst(),
        onStatus: (message) => this.setStatus(message),
        onPlayback: (active) => this.avatar.setMouthSync(active),
        onListening: (active) => this.update({ microphoneActive: active }),
      });
    } catch (error) {
      this.audio = null;
      this.log(`语音功能初始化失败：${error.message}`);
    }
  }

  async _loadAvatar() {
    this.log("Live2D 模型开始加载");
    try {
      // 先用项目自己的请求层验证 URL；Pixi 的加载错误在部分真机只会给出 undefined。
      await this.api.request(MODEL_PATH, { timeout: 20000 });
      await this.avatar.loadModel(this.api.assetUrl(MODEL_PATH));
      this.setStatus("Live2D 模型已加载。");
      this.log("Live2D 模型加载完成");
      this._scheduleIdleAction();
    } catch (error) {
      const detail = errorMessage(error, "模型资源请求或 Cubism 解析失败");
      this.setStatus(`Live2D 加载失败：${detail}`);
      this.log(`Live2D 加载失败：${detail}`);
    }
  }

  _bindInput() {
    wx.onTouchStart?.((event) => {
      this.touchStart = touchPoint(event);
      this.avatar.dispatchTouch(event);
    });
    wx.onTouchMove?.((event) => {
      this.avatar.dispatchTouch(event);
      const point = touchPoint(event);
      if (point) this.avatar.setPointer(point.x, point.y, { left: 0, top: 0, width: this.window.windowWidth, height: this.window.windowHeight });
    });
    wx.onTouchEnd?.((event) => {
      this.avatar.dispatchTouch(event);
      const point = touchPoint(event);
      if (!point || !this.touchStart) return;
      const distance = Math.hypot(point.x - this.touchStart.x, point.y - this.touchStart.y);
      this.touchStart = null;
      if (distance > 18) return;
      const stageX = point.x / this.window.windowWidth * this.stageWidth;
      const stageY = point.y / this.window.windowHeight * this.stageHeight;
      this.dispatch(this.view.hitTest(stageX, stageY)).catch((error) => this.log(error.message));
    });
    wx.onKeyboardInput?.(({ value }) => {
      if (this.keyboardMode === "chat") this.update({ inputText: value });
      else if (this.keyboardMode === "host") this._updateDeviceDraft({ host: value });
    });
    wx.onKeyboardConfirm?.(({ value }) => {
      const mode = this.keyboardMode;
      this.keyboardMode = null;
      wx.hideKeyboard?.();
      if (mode === "chat") this.submitText(value).catch((error) => this.log(error.message));
      else if (mode === "host") this._updateDeviceDraft({ host: value });
    });
    wx.onKeyboardComplete?.(() => {
      this.keyboardMode = null;
    });
  }

  _bindLifecycle() {
    wx.onHide?.(() => {
      this.audio?.stopPlayback();
      if (this.perception.running) this.perception.stop();
      this.avatar.pause();
    });
    wx.onShow?.(() => {
      this.avatar.resume();
      if (this.audio?.listening) this.update({ microphoneActive: true });
    });
  }

  _openKeyboard(field) {
    if (typeof wx.showKeyboard !== "function") {
      this.setStatus("当前微信版本不支持小游戏键盘输入。");
      return;
    }
    this.keyboardMode = field;
    const defaultValue = field === "host" ? this.state.deviceConfig.host : this.state.inputText;
    wx.showKeyboard({
      defaultValue: String(defaultValue || ""),
      maxLength: field === "chat" ? 2000 : 253,
      multiple: field === "chat",
      confirmType: field === "chat" ? "send" : "done",
      fail: (error) => {
        this.keyboardMode = null;
        this.setStatus(`无法打开键盘：${error.errMsg || "未知错误"}`);
      },
    });
  }

  _toggleMicrophone() {
    if (!this.audio) {
      this.setStatus("当前微信版本不支持录音，请使用文字输入。");
      return;
    }
    if (this.audio.desiredListening) this.audio.stop();
    else this.audio.start();
  }

  _toggleVision() {
    if (this.perception.running) this.perception.stop();
    else this.perception.start();
  }

  _triggerAction(name) {
    const action = this.actionsByName.get(name);
    if (!action) return;
    this.avatar.triggerAction(action, "pulse", action.durationMs).catch((error) => this.log(error.message));
    this.log(`手动动作：${action.label}`);
  }

  _changeActionPage(delta) {
    const pageCount = Math.max(1, Math.ceil(ACTIONS.length / 9));
    const actionPage = Math.max(0, Math.min(pageCount - 1, this.state.actionPage + delta));
    this.update({ actionPage });
  }

  async _previewVoice() {
    if (!this.audio) {
      this.setStatus("当前微信版本不支持语音播放。");
      return;
    }
    try {
      await this.audio.playSpeech({
        text: "你好，我是草莓兔兔，这是当前板端本地语音模型的试听。",
        rate: this.state.speechRatePercent / 100,
        voice: this.state.selectedVoice,
      });
    } catch (error) {
      this.setStatus(`语音试听失败：${error.message}`);
    }
  }

  _setConnectionMode(mode) {
    this._updateDeviceDraft({ mode: mode === "local" ? "local" : "public" });
  }

  _updateDeviceDraft(patch) {
    this.update({ deviceConfig: { ...this.state.deviceConfig, ...patch } });
  }

  async _saveDevice() {
    try {
      this.deviceConfig = saveDeviceConfig(this.state.deviceConfig);
      this.update({
        deviceConfig: { ...this.deviceConfig },
        deviceHost: displayDeviceAddress(this.deviceConfig),
        activePanel: "",
      });
      await Promise.allSettled([this._loadAvatar(), this.connectDevice()]);
    } catch (error) {
      this.setStatus(error.message);
    }
  }

  _streamReply(text) {
    clearTimeout(this.replyTimer);
    let length = 0;
    const advance = () => {
      length = Math.min(text.length, length + 3);
      this.update({ replyText: text.slice(0, length) });
      if (length < text.length) this.replyTimer = setTimeout(advance, 48);
    };
    advance();
  }

  _addHistory(user, robot) {
    const history = [{ id: Date.now(), user, robot }, ...this.state.history].slice(0, 50);
    wx.setStorageSync(HISTORY_KEY, history);
    this.update({ history });
  }

  _loadHistory() {
    const history = wx.getStorageSync(HISTORY_KEY);
    return Array.isArray(history) ? history.slice(0, 50) : [];
  }

  _scheduleIdleAction() {
    clearTimeout(this.idleTimer);
    this.idleTimer = setTimeout(() => {
      const idleNames = ["blush", "heart", "question", "flowers", "star_eyes", "sweat", "twin_tail"];
      const action = this.actionsByName.get(idleNames[Math.floor(Math.random() * idleNames.length)]);
      this.avatar.triggerAction(action, "pulse", action.durationMs).catch(() => {});
      this._scheduleIdleAction();
    }, 8000 + Math.random() * 7000);
  }
}

module.exports = { CompanionGame, MODEL_PATH, touchPoint, windowInfo };
