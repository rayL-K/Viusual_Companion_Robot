import { emotionOnnxClient } from "./emotion-onnx-client.js";

/**
 * 浏览器端视觉感知：MediaPipe 负责人脸关键点，本机 FER+ 服务作为可选情绪增强。
 *
 * 检测 cameraPreviewEl 视频帧 → 输出 Live2D 参数与视觉上下文。
 */
const DETECT_INTERVAL_MS = 66; // ~15fps
const ONNX_EMOTION_INTERVAL_MS = 220;
let _onStatus = null;

/** @type {import('@mediapipe/tasks-vision').FaceLandmarker} */
let _landmarker = null;
let _landmarkerLoadPromise = null;

async function loadFaceLandmarker() {
  const { FilesetResolver, FaceLandmarker } = await import("./mediapipe/vision_bundle.js");
  const vision = await FilesetResolver.forVisionTasks("/mediapipe/wasm/");
  return FaceLandmarker.createFromOptions(vision, {
    baseOptions: {
      modelAssetPath: "/mediapipe/model/face_landmarker.task",
    },
    outputFaceBlendshapes: true,
    numFaces: 1,
  });
}

/**
 * 状态: "loading" / "detecting" / "tracking" / "error" / "stopped"
 */
export const perceptionClient = {
  _videoEl: null,
  _running: false,
  _timer: 0,
  _startTimer: 0,
  _generation: 0,
  _result: null,
  _status: "stopped",
  _lastEmotion: "",
  _onnxEmotion: null,
  _lastOnnxAt: 0,
  _reportedOnnxStatus: "",
  _latestParams: null,

  onStatus(fn) { _onStatus = fn; },
  get connected() { return this._running; },
  get hasFace() { return !!(this._result?.faceLandmarks?.length); },
  get latest() { return this._result; },
  get status() { return this._status; },
  getContext() {
    if (!this._running || !this._latestParams) {
      return null;
    }
    const params = this._latestParams;
    return {
      status: this._status,
      hasFace: this.hasFace,
      emotion: params.emotion,
      emotionSource: params.emotionSource,
      emotionConfidence: roundNumber(params.emotionConfidence, 3),
      fullScores: roundScoreMap(params.fullScores),
      headPose: {
        angleX: params.angleX,
        angleY: params.angleY,
        bodyAngleZ: params.bodyAngleZ,
      },
      mouth: {
        smile: roundNumber(params.mouthSmile, 3),
        open: roundNumber(params.mouthOpen, 3),
      },
      eyes: {
        open: roundNumber(params.eyeOpen, 3),
      },
    };
  },

  _setStatus(status, detail = "") {
    this._status = status;
    if (_onStatus) _onStatus(status, detail);
  },

  async start(videoEl) {
    if (this._running) this.stop();
    const generation = ++this._generation;
    this._videoEl = videoEl;

    // 第一次动态加载 vision 库 + 模型；并发启动复用同一个加载任务。
    if (!_landmarker) {
      this._setStatus("loading", "加载模型...");
      try {
        _landmarkerLoadPromise ||= loadFaceLandmarker();
        _landmarker = await _landmarkerLoadPromise;
      } catch (err) {
        console.warn("[Perception] 模型加载失败:", err);
        if (generation === this._generation) this._setStatus("error", err.message);
        return;
      } finally {
        _landmarkerLoadPromise = null;
      }
    }
    if (generation !== this._generation || this._videoEl !== videoEl) return;

    this._running = true;
    this._setStatus("detecting", "等待人脸...");
    // 启动延迟 500ms，等视频流稳定后再开始检测避免闪烁
    this._startTimer = setTimeout(() => {
      this._startTimer = 0;
      if (this._running && generation === this._generation) this._detectLoop();
    }, 500);
  },

  stop() {
    this._generation += 1;
    this._running = false;
    if (this._startTimer) { clearTimeout(this._startTimer); this._startTimer = 0; }
    if (this._timer) { clearTimeout(this._timer); this._timer = 0; }
    this._result = null;
    this._videoEl = null;
    this._lastEmotion = "";
    this._onnxEmotion = null;
    this._lastOnnxAt = 0;
    this._reportedOnnxStatus = "";
    this._latestParams = null;
    this._emoHistory = [];
    this._setStatus("stopped");
  },

  getLive2DParams() {
    const r = this._result;
    if (!r || !r.faceLandmarks?.length) return null;

    const pts = r.faceLandmarks[0].map(p => ({ x: p.x, y: p.y, z: p.z }));
    const bs = r.faceBlendshapes?.[0]?.categories || [];

    // 人脸框
    const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
    const x1 = Math.max(0, Math.min(...xs)), y1 = Math.max(0, Math.min(...ys));
    const x2 = Math.min(1, Math.max(...xs)), y2 = Math.min(1, Math.max(...ys));

    // 头部姿态：鼻尖相对人脸框偏移
    const nose = pts[1];
    const cx = (x1 + x2) / 2, cy = (y1 + y2) / 2;
    const nx = (nose.x - cx) / (x2 - x1 + 0.01);
    const ny = (nose.y - cy) / (y2 - y1 + 0.01);

    // roll: 双眼外角
    const eDx = pts[263].x - pts[33].x, eDy = pts[263].y - pts[33].y;
    const roll = Math.atan2(eDy, eDx) * (180 / Math.PI);

    // Blendshapes
    const bm = {};
    for (const b of bs) bm[b.categoryName] = b.score;

    const smile    = Math.max(bm.mouthSmileLeft || 0, bm.mouthSmileRight || 0);
    const browUp   = (bm.browInnerUp || 0) + (bm.browOuterUpLeft || 0) + (bm.browOuterUpRight || 0);
    const jawOpen  = bm.jawOpen || 0;
    const eyeBlink = ((bm.eyeBlinkLeft || 0) + (bm.eyeBlinkRight || 0)) / 2;

    // 时间平滑（最后 5 帧滑动平均）
    const SMOOTH_FRAMES = 5;
    if (!this._emoHistory) this._emoHistory = [];
    this._emoHistory.push({ smile, browUp, jawOpen, eyeBlink, bm: {...bm} });
    if (this._emoHistory.length > SMOOTH_FRAMES) this._emoHistory.shift();
    const avg = (key, getter) => {
      let sum = 0;
      for (const f of this._emoHistory) sum += getter(f);
      return sum / this._emoHistory.length;
    };
    const sSmile   = avg('smile', f => f.smile);
    const sBrowUp  = avg('browUp', f => f.browUp);
    const sJawOpen = avg('jawOpen', f => f.jawOpen);
    const sBlink   = avg('eyeBlink', f => f.eyeBlink);

    // 情绪推断 — 基于 52 组 Blendshapes 加权打分
    const emo = { happy: 0, sad: 0, surprise: 0, angry: 0, fear: 0, disgust: 0, neutral: 0 };
    const _ = k => {
      let sum = 0;
      for (const f of this._emoHistory) sum += f.bm[k] || 0;
      return sum / this._emoHistory.length;
    };
    const cSquint  = Math.max(_('cheekSquintLeft'), _('cheekSquintRight'));
    const bDown    = Math.max(_('browDownLeft'), _('browDownRight'));
    const mPress   = Math.max(_('mouthPressLeft'), _('mouthPressRight'));
    const mFrown   = Math.max(_('mouthFrownLeft'), _('mouthFrownRight'));
    const mStretch = Math.max(_('mouthStretchLeft'), _('mouthStretchRight'));
    const nWrinkle = Math.max(_('noseSneerLeft'), _('noseSneerRight'));
    const upperLip = Math.max(_('mouthUpperUpLeft'), _('mouthUpperUpRight'));
    const eSquint  = Math.max(_('eyeSquintLeft'), _('eyeSquintRight'));
    const eWide    = Math.max(_('eyeWideLeft'), _('eyeWideRight'));
    const mShrugUp = _('mouthShrugUpper');
    const cPuff    = _('cheekPuff');

    const w = (weight, ...scores) => weight * scores.reduce((a, b) => a + b, 0) / scores.length;
    emo.happy    = Math.min(1, w(1.0, sSmile, cSquint) - w(0.5, mFrown, bDown));
    emo.sad      = Math.min(1, w(1.0, bDown, mFrown) + w(0.3, mShrugUp) - w(0.7, sSmile));
    emo.surprise = Math.min(1, w(1.0, sBrowUp, sJawOpen) + w(0.4, eWide, mStretch) - w(0.3, sSmile, bDown));
    emo.angry    = Math.min(1, w(1.0, bDown, mPress, eSquint) - w(0.5, sSmile));
    emo.fear     = Math.min(1, w(1.0, sBrowUp, eWide) + w(0.5, sJawOpen, mShrugUp) - w(0.3, sSmile, bDown));
    emo.disgust  = Math.min(1, w(1.0, nWrinkle, upperLip) + w(0.4, cPuff));
    for (const k of Object.keys(emo)) emo[k] = Math.max(0, emo[k]);

    if (Math.max(...Object.values(emo)) < 0.25) { emo.neutral = 1; }
    if (emo.happy > 0.35) { emo.sad *= 0.2; emo.angry *= 0.2; emo.fear *= 0.1; emo.disgust *= 0.1; }
    if (emo.surprise > 0.4) { emo.sad *= 0.3; emo.angry *= 0.3; }
    const ruleEmotion = Object.entries(emo).reduce((a, b) => b[1] > a[1] ? b : a)[0];
    const emotionResult = this._onnxEmotion?.emotion
      ? this._onnxEmotion
      : { emotion: ruleEmotion, confidence: emo[ruleEmotion] || 0, fullScores: emo, source: "blendshape_rule" };
    const emotion = emotionResult.emotion;

    // 状态节流：只在情绪变化时更新状态栏避免闪烁
    const emotionStatusKey = `${emotionResult.source}:${emotion}`;
    if (emotionStatusKey !== this._lastEmotion) {
      this._lastEmotion = emotionStatusKey;
      this._setStatus("tracking", emotion);
    }

    const params = {
      angleX: Math.round(nx * -40),
      angleY: Math.round(ny * -30),
      bodyAngleZ: Math.round(roll),
      mouthSmile: Math.max(0, Math.min(1, sSmile)),
      mouthOpen: Math.max(0, Math.min(1, sJawOpen)),
      browRaise: Math.max(0, Math.min(1, sBrowUp / 3)),
      eyeOpen: Math.max(0, Math.min(1, 1 - sBlink)),
      emotion,
      emotionSource: emotionResult.source,
      emotionConfidence: emotionResult.confidence,
      fullScores: emotionResult.fullScores,
    };
    this._latestParams = params;
    return params;
  },

  async _detectLoop() {
    if (!this._running || !this._videoEl) return;
    const generation = this._generation;
    const video = this._videoEl;
    if (video.readyState >= 2 && video.videoWidth > 0) {
      try {
        this._result = _landmarker.detect(video);
        if (!this._result?.faceLandmarks?.length) {
          this._onnxEmotion = null;
          this._latestParams = null;
          if (this._lastEmotion !== "__no_face__") {
            this._lastEmotion = "__no_face__";
            this._setStatus("detecting", "无人脸");
          }
        } else {
          await this._updateOnnxEmotion(video, generation);
        }
      } catch (error) {
        if (generation === this._generation) this._setStatus("error", error.message || "视觉感知失败");
      }
    }
    if (!this._running || generation !== this._generation) return;
    this._timer = setTimeout(() => this._detectLoop(), DETECT_INTERVAL_MS);
  },

  async _updateOnnxEmotion(video, generation) {
    const now = performance.now();
    if (now - this._lastOnnxAt < ONNX_EMOTION_INTERVAL_MS) {
      return;
    }
    this._lastOnnxAt = now;
    const faceBox = faceBoxFromLandmarks(this._result?.faceLandmarks?.[0]);
    if (!faceBox) {
      return;
    }

    const result = await emotionOnnxClient.classify(video, faceBox);
    if (!this._running || generation !== this._generation) return;
    if (result) {
      this._onnxEmotion = result;
      return;
    }
    this._onnxEmotion = null;
    if (emotionOnnxClient.status && emotionOnnxClient.status !== this._reportedOnnxStatus) {
      this._reportedOnnxStatus = emotionOnnxClient.status;
      console.info("[Perception] ONNX 情绪模型状态:", emotionOnnxClient.status, emotionOnnxClient.error || "");
    }
  },
};

function faceBoxFromLandmarks(landmarks) {
  if (!landmarks?.length) {
    return null;
  }
  const xs = landmarks.map((point) => point.x);
  const ys = landmarks.map((point) => point.y);
  const x1 = clamp01(Math.min(...xs));
  const y1 = clamp01(Math.min(...ys));
  const x2 = clamp01(Math.max(...xs));
  const y2 = clamp01(Math.max(...ys));
  return {
    x: x1,
    y: y1,
    width: Math.max(0.01, x2 - x1),
    height: Math.max(0.01, y2 - y1),
  };
}

function clamp01(value) {
  return Math.min(1, Math.max(0, Number(value)));
}

function roundNumber(value, digits) {
  const factor = 10 ** digits;
  return Math.round(Number(value || 0) * factor) / factor;
}

function roundScoreMap(scores) {
  return Object.fromEntries(
    Object.entries(scores || {}).map(([key, value]) => [key, roundNumber(value, 3)]),
  );
}
