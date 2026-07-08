const { RealtimeVisionClient } = require("./realtime-vision-client");

const CAPTURE_INTERVAL_MS = 40;
const INITIAL_CAPTURE_DELAY_MS = 400;
const CONTEXT_MAX_AGE_MS = 15000;
const SPEAKER_CAPTURE_INTERVAL_MS = 125;
const SPEAKER_CONTEXT_MAX_AGE_MS = 10000;

class PerceptionController {
  constructor(options) {
    this.api = options.api;
    this.realtimeVision = new RealtimeVisionClient({ api: this.api, wxApi: options.wxApi });
    this.onUpdate = options.onUpdate || (() => {});
    this.onStatus = options.onStatus || (() => {});
    this.camera = null;
    this.timer = null;
    this.initialTimer = null;
    this.running = false;
    this.requestRunning = false;
    this.photoBusy = false;
    this.speakerTimer = null;
    this.speakerFrames = [];
    this.speakerStartedAt = 0;
    this.speakerCapturing = false;
    this.lastActiveSpeaker = null;
    this.failureCount = 0;
    this.lastTrackingStatusAt = 0;
    this.generation = 0;
    this.context = { enabled: false };
  }

  start() {
    if (this.running) return true;
    if (typeof wx.createCamera !== "function") {
      this.onStatus("当前微信基础库不支持小游戏摄像头，请升级微信。");
      return false;
    }

    const generation = ++this.generation;
    let creationFailed = false;
    this.context = { enabled: true, status: "starting" };
    this.lastActiveSpeaker = null;
    this.failureCount = 0;
    this.onUpdate(this.getContext());
    this.realtimeVision.connect().catch(() => {});
    try {
      this.camera = wx.createCamera({
        x: -2,
        y: -2,
        width: 1,
        height: 1,
        devicePosition: "front",
        flash: "off",
        size: "small",
        success: () => {
          if (generation === this.generation) this.onStatus("摄像头已开启，画面只在 ELF2 本地分析。");
        },
        fail: (error) => {
          creationFailed = true;
          this._stopWithError(error.errMsg || "摄像头创建失败", generation);
        },
      });
    } catch (error) {
      this.camera = null;
      this._stopWithError(error.message || "摄像头创建失败", generation);
      return false;
    }
    if (creationFailed || !this.camera || typeof this.camera.takePhoto !== "function") {
      this.camera = null;
      if (!creationFailed) this._stopWithError("微信没有返回可用的小游戏 Camera 对象", generation);
      return false;
    }

    this.running = true;
    this.camera.onAuthCancel?.(() => this._stopWithError("摄像头权限未授权", generation));
    this.camera.onStop?.(() => this._stopWithError("摄像头已被系统停止", generation));
    this.initialTimer = setTimeout(() => {
      this.initialTimer = null;
      this.capture();
    }, INITIAL_CAPTURE_DELAY_MS);
    return true;
  }

  stop() {
    this.generation += 1;
    this.running = false;
    this.requestRunning = false;
    this.photoBusy = false;
    this.finishSpeakerBurst();
    if (this.timer) clearTimeout(this.timer);
    if (this.initialTimer) clearTimeout(this.initialTimer);
    this.timer = null;
    this.initialTimer = null;
    this.camera?.destroy?.();
    this.realtimeVision.close();
    this.camera = null;
    this.context = { enabled: false };
    this.lastActiveSpeaker = null;
    this.failureCount = 0;
    this.onUpdate(this.getContext());
    this.onStatus("摄像头感知已关闭。");
  }

  getContext(now = Date.now()) {
    const context = { ...this.context };
    if (!context.enabled || !context.receivedAt) return context;
    if (now - context.receivedAt <= CONTEXT_MAX_AGE_MS) return context;
    return { ...context, status: "stale", stale: true };
  }

  capture() {
    if (!this.running || !this.camera) return;
    if (this.speakerCapturing || this.requestRunning || this.photoBusy) {
      this._scheduleCapture(this.speakerCapturing ? 100 : CAPTURE_INTERVAL_MS);
      return;
    }
    const generation = this.generation;
    this.requestRunning = true;
    this.photoBusy = true;
    this._takePhotoBase64()
      .then((data) => this._requestVision(data))
      .then((result) => {
        if (!this._isCurrent(generation)) return;
        const receivedAt = Date.now();
        this.context = normalizeVisionResult(result, receivedAt);
        if (
          this.lastActiveSpeaker
          && receivedAt - this.lastActiveSpeaker.receivedAt <= SPEAKER_CONTEXT_MAX_AGE_MS
        ) {
          this.context.activeSpeaker = this.lastActiveSpeaker;
        }
        this.onUpdate(this.getContext());
        this.failureCount = 0;
        if (receivedAt - this.lastTrackingStatusAt >= 500) {
          this.lastTrackingStatusAt = receivedAt;
          this.onStatus(`ELF2 连续视觉：${this.context.semanticCaption || this.context.sceneCaption}`);
        }
      })
      .catch((error) => {
        this.failureCount += 1;
        this._finishWithError(error.errMsg || error.message || "摄像头拍照失败", generation);
      })
      .finally(() => {
        if (generation === this.generation) {
          this.requestRunning = false;
          this.photoBusy = false;
          const delay = this.failureCount
            ? Math.min(5000, 400 * (2 ** Math.min(this.failureCount - 1, 4)))
            : CAPTURE_INTERVAL_MS;
          this._scheduleCapture(delay);
        }
      });
  }

  startSpeakerBurst() {
    if (!this.running || !this.camera) return false;
    this.finishSpeakerBurst();
    this.speakerFrames = [];
    this.speakerStartedAt = Date.now();
    this.speakerCapturing = true;
    this._captureSpeakerFrame();
    return true;
  }

  finishSpeakerBurst() {
    this.speakerCapturing = false;
    if (this.speakerTimer) clearTimeout(this.speakerTimer);
    this.speakerTimer = null;
    const frames = this.speakerFrames.slice();
    this.speakerFrames = [];
    return frames;
  }

  applyActiveSpeaker(result) {
    if (!result || result.ok !== true) return;
    const activeSpeaker = {
      status: String(result.status || "unknown"),
      reason: String(result.reason || ""),
      confidence: Number(result.speaker?.confidence || 0),
      name: String(result.speaker?.name || ""),
      profileId: String(result.speaker?.profile_id || ""),
      receivedAt: Date.now(),
    };
    this.lastActiveSpeaker = activeSpeaker;
    this.context = {
      ...this.context,
      activeSpeaker,
    };
    this.onUpdate(this.getContext());
  }

  _captureSpeakerFrame() {
    if (!this.speakerCapturing || !this._isCurrent(this.generation)) return;
    if (this.photoBusy) {
      this._scheduleSpeakerFrame(80);
      return;
    }
    const generation = this.generation;
    this.photoBusy = true;
    this._takePhotoBase64()
      .then((image) => {
        if (!this.speakerCapturing || !this._isCurrent(generation)) return;
        this.speakerFrames.push({ image, timestamp_ms: Date.now() - this.speakerStartedAt });
        if (this.speakerFrames.length > 16) this.speakerFrames.shift();
      })
      .catch((error) => this.onStatus(`说话人画面采集失败：${error.errMsg || error.message || "未知错误"}`))
      .finally(() => {
        if (generation === this.generation) this.photoBusy = false;
        this._scheduleSpeakerFrame(SPEAKER_CAPTURE_INTERVAL_MS);
      });
  }

  _scheduleSpeakerFrame(delay) {
    if (!this.speakerCapturing) return;
    this.speakerTimer = setTimeout(() => {
      this.speakerTimer = null;
      this._captureSpeakerFrame();
    }, delay);
  }

  _scheduleCapture(delay) {
    if (!this.running) return;
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.timer = null;
      this.capture();
    }, delay);
  }

  _takePhotoBase64() {
    if (!this.camera) return Promise.reject(new Error("摄像头未启动"));
    return Promise.resolve(this.camera.takePhoto("low"))
      .then(({ tempImagePath }) => new Promise((resolve, reject) => {
        wx.getFileSystemManager().readFile({
          filePath: tempImagePath,
          encoding: "base64",
          success: ({ data }) => resolve(data),
          fail: (error) => reject(error),
        });
      }));
  }

  _requestVision(image) {
    if (this.realtimeVision.ready) {
      return this.realtimeVision.analyze(image).catch(() => {
        this.realtimeVision.close();
        return this.api.vision(image);
      });
    }
    this.realtimeVision.connect().catch(() => {});
    return this.api.vision(image);
  }

  _finishWithError(message, generation = this.generation) {
    if (generation !== this.generation) return;
    this.requestRunning = false;
    this.photoBusy = false;
    this.context = { ...this.context, enabled: this.running, status: "error", error: String(message || "视觉感知失败") };
    this.onUpdate(this.getContext());
    this.onStatus(`本地视觉失败：${this.context.error}`);
  }

  _stopWithError(message, generation) {
    if (generation !== this.generation) return;
    this.running = false;
    this.requestRunning = false;
    this.photoBusy = false;
    this.finishSpeakerBurst();
    if (this.timer) clearTimeout(this.timer);
    if (this.initialTimer) clearTimeout(this.initialTimer);
    this.timer = null;
    this.initialTimer = null;
    this.camera?.destroy?.();
    this.realtimeVision.close();
    this.camera = null;
    this.context = { enabled: false, status: "error", error: String(message || "视觉感知失败") };
    this.onUpdate(this.getContext());
    this.onStatus(`本地视觉失败：${this.context.error}`);
  }

  _isCurrent(generation) {
    return this.running && generation === this.generation;
  }
}

function normalizeVisionResult(result, receivedAt) {
  if (!result || result.ok !== true || result.backend !== "elf2-local-yolo-pose-yunet-sface-ferplus") {
    throw new Error("ELF2 没有返回有效的本地视觉结果");
  }
  return {
    enabled: true,
    status: "running",
    backend: result.backend,
    timestamp: String(result.timestamp || ""),
    receivedAt,
    sceneCaption: String(result.scene_caption || ""),
    semanticCaption: String(result.semantic_caption || ""),
    semanticStatus: String(result.semantic_status || ""),
    personActivity: String(result.person_activity || ""),
    personCount: Number(result.person_count || 0),
    objectsDetected: Array.isArray(result.objects_detected) ? result.objects_detected.slice(0, 12) : [],
    hasFace: result.has_face === true,
    emotion: String(result.emotion || "neutral"),
    emotionSource: "ferplus-onnx",
    emotionConfidence: Number(result.confidence || 0),
    fullScores: result.full_scores || {},
    personActions: Array.isArray(result.person_actions) ? result.person_actions.slice(0, 8).map(String) : [],
    bodyState: String(result.body_state || "unknown"),
    focusPerson: normalizeFocusPerson(result.focus_face),
    activeSpeaker: normalizeActiveSpeaker(result.active_speaker),
    latencyMs: Number(result.latency_ms || 0),
  };
}

function normalizeFocusPerson(value) {
  if (!value || typeof value !== "object") return null;
  return {
    profileId: String(value.profile_id || ""),
    name: String(value.name || ""),
    identitySimilarity: Number(value.identity_similarity || 0),
  };
}

function normalizeActiveSpeaker(value) {
  if (!value || typeof value !== "object") return { status: "unknown", reason: "" };
  return { status: String(value.status || "unknown"), reason: String(value.reason || "") };
}

module.exports = {
  CAPTURE_INTERVAL_MS,
  CONTEXT_MAX_AGE_MS,
  PerceptionController,
  normalizeVisionResult,
};
