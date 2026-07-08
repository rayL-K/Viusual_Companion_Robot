import { apiUrl } from "./runtime-config.js";

const VISION_API_URL = apiUrl("/vision");
export const VISION_FRAME_GAP_MS = 40;
const START_DELAY_MS = 700;
const CONTEXT_MAX_AGE_MS = 15000;
const CAPTURE_MAX_WIDTH = 480;
const SPEAKER_CAPTURE_INTERVAL_MS = 125;
const SPEAKER_CONTEXT_MAX_AGE_MS = 10000;
let onStatus = null;

export function realtimeVisionUrl(locationLike = globalThis.location) {
  const httpUrl = apiUrl("/realtime", locationLike);
  if (httpUrl.startsWith("https://")) return `wss://${httpUrl.slice(8)}`;
  if (httpUrl.startsWith("http://")) return `ws://${httpUrl.slice(7)}`;
  return "ws://127.0.0.1:8765/realtime";
}

/** 复用一条长连接传输连续帧，避免移动网络为每帧重复建立 HTTP/TLS 链路。 */
export class RealtimeVisionClient {
  constructor(options = {}) {
    this.url = options.url || realtimeVisionUrl();
    this.timeoutMs = options.timeoutMs || 10000;
    this.WebSocketCtor = options.WebSocketCtor || globalThis.WebSocket;
    this.socket = null;
    this.connectPromise = null;
    this.pending = null;
  }

  get ready() {
    return this.socket?.readyState === this.WebSocketCtor?.OPEN;
  }

  connect() {
    if (this.ready) return Promise.resolve(true);
    if (this.connectPromise) return this.connectPromise;
    if (!this.WebSocketCtor) return Promise.reject(new Error("当前浏览器不支持视觉 WebSocket。"));

    this.connectPromise = new Promise((resolve, reject) => {
      const socket = new this.WebSocketCtor(this.url);
      this.socket = socket;
      let settled = false;
      const timer = globalThis.setTimeout(() => fail("视觉实时通道连接超时。"), this.timeoutMs);
      const fail = (message) => {
        if (settled) return;
        settled = true;
        globalThis.clearTimeout(timer);
        this.connectPromise = null;
        reject(new Error(message));
      };
      socket.addEventListener("open", () => {
        if (settled) return;
        settled = true;
        globalThis.clearTimeout(timer);
        this.connectPromise = null;
        resolve(true);
      }, { once: true });
      socket.addEventListener("error", () => fail("视觉实时通道连接失败。"), { once: true });
      socket.addEventListener("message", (event) => this._handleMessage(event));
      socket.addEventListener("close", () => {
        this.socket = null;
        this.connectPromise = null;
        this._rejectPending(new Error("视觉实时通道已断开。"));
        fail("视觉实时通道连接失败。");
      });
    });
    return this.connectPromise;
  }

  analyze(image) {
    if (!this.ready || this.pending) {
      return Promise.reject(new Error("视觉实时通道尚未就绪。"));
    }
    const id = `vision-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    return new Promise((resolve, reject) => {
      const timer = globalThis.setTimeout(() => {
        this._rejectPending(new Error("视觉实时结果返回超时。"));
      }, this.timeoutMs);
      this.pending = { id, resolve, reject, timer };
      this.socket.send(JSON.stringify({ id, type: "vision", image }));
    });
  }

  close() {
    this._rejectPending(new Error("视觉实时通道已关闭。"));
    this.socket?.close();
    this.socket = null;
    this.connectPromise = null;
  }

  _handleMessage(event) {
    let payload;
    try {
      payload = JSON.parse(String(event.data || ""));
    } catch {
      return;
    }
    if (!this.pending || payload.id !== this.pending.id || payload.type !== "vision") return;
    if (payload.ok === false) {
      this._rejectPending(new Error(payload.error || "视觉实时分析失败。"));
      return;
    }
    const pending = this.pending;
    this.pending = null;
    globalThis.clearTimeout(pending.timer);
    pending.resolve(payload.data || payload);
  }

  _rejectPending(error) {
    const pending = this.pending;
    this.pending = null;
    if (!pending) return;
    globalThis.clearTimeout(pending.timer);
    pending.reject(error);
  }
}

/** 浏览器只采集压缩帧；场景与情绪推理全部由 ELF2 完成。 */
export const perceptionClient = {
  _videoEl: null,
  _running: false,
  _timer: 0,
  _generation: 0,
  _context: { enabled: false },
  _canvas: null,
  _speakerCanvas: null,
  _speakerTimer: 0,
  _speakerFrames: [],
  _speakerStartedAt: 0,
  _speakerCapturing: false,
  _speakerCaptureBusy: false,
  _lastActiveSpeaker: null,
  _live2dParams: null,
  _failureCount: 0,
  _lastTrackingStatusAt: 0,
  _realtimeVision: new RealtimeVisionClient(),

  onStatus(callback) { onStatus = callback; },
  get connected() { return this._running; },
  get hasFace() { return this._context.hasFace === true; },
  get latest() { return this._context; },
  get status() { return this._context.status || "stopped"; },

  getContext(now = Date.now()) {
    const context = { ...this._context };
    if (!context.enabled || !context.receivedAt) return context;
    if (now - context.receivedAt <= CONTEXT_MAX_AGE_MS) return context;
    return { ...context, status: "stale", stale: true };
  },

  getLive2DParams() {
    const context = this._context;
    if (
      !context.enabled
      || !context.receivedAt
      || Date.now() - context.receivedAt > CONTEXT_MAX_AGE_MS
      || !context.hasFace
    ) return null;
    return this._live2dParams;
  },

  start(videoEl) {
    this.stop();
    const generation = ++this._generation;
    this._videoEl = videoEl;
    this._running = true;
    this._context = { enabled: true, status: "starting" };
    this._lastActiveSpeaker = null;
    this._live2dParams = null;
    this._failureCount = 0;
    this._setStatus("starting", "等待摄像头画面稳定...");
    void this._realtimeVision.connect().catch(() => {});
    this._timer = window.setTimeout(() => this._captureLoop(generation), START_DELAY_MS);
  },

  stop() {
    this._generation += 1;
    this._running = false;
    if (this._timer) window.clearTimeout(this._timer);
    this.finishSpeakerBurst();
    this._timer = 0;
    this._videoEl = null;
    this._context = { enabled: false, status: "stopped" };
    this._lastActiveSpeaker = null;
    this._live2dParams = null;
    this._realtimeVision.close();
    this._setStatus("stopped");
  },

  startSpeakerBurst() {
    if (!this._running || !this._videoEl) return false;
    this.finishSpeakerBurst();
    this._speakerFrames = [];
    this._speakerStartedAt = Date.now();
    this._speakerCapturing = true;
    void this._captureSpeakerFrame();
    return true;
  },

  finishSpeakerBurst() {
    this._speakerCapturing = false;
    if (this._speakerTimer) window.clearTimeout(this._speakerTimer);
    this._speakerTimer = 0;
    const frames = this._speakerFrames.slice();
    this._speakerFrames = [];
    return frames;
  },

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
    this._lastActiveSpeaker = activeSpeaker;
    this._context = {
      ...this._context,
      activeSpeaker,
    };
  },

  async _captureLoop(generation) {
    this._timer = 0;
    if (!this._isCurrent(generation)) return;
    if (this._speakerCapturing) {
      this._scheduleNext(generation, 100);
      return;
    }
    const video = this._videoEl;
    if (!video || video.readyState < 2 || video.videoWidth <= 0) {
      this._setStatus("starting", "正在等待摄像头画面...");
      this._scheduleNext(generation, 500);
      return;
    }

    try {
      if (!this._context.receivedAt) {
        this._setStatus("analyzing", "ELF2 正在分析当前画面...");
      }
      const image = await this._captureJpegBase64(video, CAPTURE_MAX_WIDTH, 0.62, "_canvas");
      const result = await this._requestVision(image);
      if (!this._isCurrent(generation)) return;
      const receivedAt = Date.now();
      this._context = normalizeVisionResult(result, receivedAt);
      this._live2dParams = live2dParamsFromContext(this._context);
      this._failureCount = 0;
      if (
        this._lastActiveSpeaker
        && receivedAt - this._lastActiveSpeaker.receivedAt <= SPEAKER_CONTEXT_MAX_AGE_MS
      ) {
        this._context.activeSpeaker = this._lastActiveSpeaker;
      }
      if (receivedAt - this._lastTrackingStatusAt >= 500) {
        this._lastTrackingStatusAt = receivedAt;
        onStatus?.("tracking", this._context.sceneCaption || "板端视觉已更新");
      }
    } catch (error) {
      if (!this._isCurrent(generation)) return;
      this._context = {
        ...this._context,
        enabled: true,
        status: "error",
        error: error.message || "本地视觉请求失败",
      };
      this._failureCount += 1;
      this._setStatus("error", this._context.error);
    }
    const retryDelay = this._failureCount
      ? Math.min(5000, 400 * (2 ** Math.min(this._failureCount - 1, 4)))
      : VISION_FRAME_GAP_MS;
    this._scheduleNext(generation, retryDelay);
  },

  async _requestVision(image) {
    if (this._realtimeVision.ready) {
      try {
        return await this._realtimeVision.analyze(image);
      } catch {
        this._realtimeVision.close();
      }
    }
    void this._realtimeVision.connect().catch(() => {});
    const response = await fetch(VISION_API_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image }),
      });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || `视觉服务返回 HTTP ${response.status}`);
    return result;
  },

  async _captureJpegBase64(video, maxWidth, quality, canvasProperty) {
    const scale = Math.min(1, maxWidth / video.videoWidth);
    const width = Math.max(1, Math.round(video.videoWidth * scale));
    const height = Math.max(1, Math.round(video.videoHeight * scale));
    this[canvasProperty] ||= document.createElement("canvas");
    const canvas = this[canvasProperty];
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) throw new Error("浏览器无法创建摄像头帧画布");
    context.drawImage(video, 0, 0, width, height);
    const blob = await new Promise((resolve, reject) => {
      canvas.toBlob(
        (value) => value ? resolve(value) : reject(new Error("摄像头帧 JPEG 编码失败")),
        "image/jpeg",
        quality,
      );
    });
    return blobToBase64(blob);
  },

  async _captureSpeakerFrame() {
    if (!this._speakerCapturing || this._speakerCaptureBusy) return;
    const video = this._videoEl;
    if (!video || video.readyState < 2 || video.videoWidth <= 0) {
      this._scheduleSpeakerFrame(100);
      return;
    }
    this._speakerCaptureBusy = true;
    try {
      const image = await this._captureJpegBase64(video, 160, 0.45, "_speakerCanvas");
      if (!this._speakerCapturing) return;
      this._speakerFrames.push({ image, timestamp_ms: Date.now() - this._speakerStartedAt });
      if (this._speakerFrames.length > 16) this._speakerFrames.shift();
    } finally {
      this._speakerCaptureBusy = false;
      this._scheduleSpeakerFrame(SPEAKER_CAPTURE_INTERVAL_MS);
    }
  },

  _scheduleSpeakerFrame(delay) {
    if (!this._speakerCapturing) return;
    this._speakerTimer = window.setTimeout(() => {
      this._speakerTimer = 0;
      void this._captureSpeakerFrame();
    }, delay);
  },

  _scheduleNext(generation, delay) {
    if (!this._isCurrent(generation)) return;
    this._timer = window.setTimeout(() => this._captureLoop(generation), delay);
  },

  _isCurrent(generation) {
    return this._running && generation === this._generation;
  },

  _setStatus(status, detail = "") {
    this._context = { ...this._context, status };
    onStatus?.(status, detail);
  },
};

export function normalizeVisionResult(result, receivedAt) {
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

function live2dParamsFromContext(context) {
  if (!context.hasFace) return null;
  const confidence = clamp01(context.emotionConfidence);
  return {
    angleX: 0,
    angleY: 0,
    bodyAngleZ: 0,
    mouthSmile: context.emotion === "happy" ? confidence : 0,
    mouthOpen: 0,
    browRaise: context.emotion === "surprise" ? confidence : 0,
    eyeOpen: context.emotion === "sad" ? 0.72 : 1,
    emotion: context.emotion,
    emotionSource: "ferplus-onnx",
    emotionConfidence: confidence,
    fullScores: context.fullScores || {},
  };
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || "").split(",", 2)[1] || "");
    reader.onerror = () => reject(new Error("摄像头帧读取失败"));
    reader.readAsDataURL(blob);
  });
}

function clamp01(value) {
  return Math.min(1, Math.max(0, Number(value) || 0));
}
