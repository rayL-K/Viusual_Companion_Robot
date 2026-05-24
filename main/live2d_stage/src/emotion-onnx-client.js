const EMOTION_ONNX_MODEL_URL = "/mediapipe/model/emotion.onnx";
const EMOTION_MODEL_SOURCE_URL = "https://huggingface.co/dwest1507/emotion-detection-model";
const EMOTION_INPUT_SIZE = 224;
const EMOTION_INPUT_CHANNELS = 3;
const EMOTION_LABELS = ["angry", "disgust", "fear", "happy", "sad", "surprise", "neutral"];
const IMAGENET_MEAN = [0.485, 0.456, 0.406];
const IMAGENET_STD = [0.229, 0.224, 0.225];

let ortModulePromise = null;
let sessionPromise = null;
let workCanvas = null;
let workContext = null;

export const emotionOnnxClient = {
  status: "idle",
  error: "",
  modelUrl: EMOTION_ONNX_MODEL_URL,
  sourceUrl: EMOTION_MODEL_SOURCE_URL,
  inputName: "",
  outputName: "",
  _ort: null,

  async classify(videoEl, faceBox) {
    const session = await this._ensureSession();
    if (!session || !videoEl || !faceBox) {
      return null;
    }

    const tensor = this._buildInputTensor(videoEl, faceBox);
    const outputs = await session.run({ [this.inputName]: tensor });
    const output = outputs[this.outputName];
    if (!output?.data?.length) {
      this.status = "error";
      this.error = "ONNX 情绪模型没有返回有效输出。";
      return null;
    }

    const scores = scoresFromOutput(output.data);
    const [emotion, confidence] = bestEmotion(scores);
    return {
      emotion,
      confidence,
      fullScores: scores,
      source: "onnx",
    };
  },

  async _ensureSession() {
    if (this.status === "missing" || this.status === "error") {
      return null;
    }
    if (!sessionPromise) {
      sessionPromise = this._loadSession().catch((error) => {
        this.status = "error";
        this.error = error?.message || "ONNX 情绪模型加载失败。";
        return null;
      });
    }
    return sessionPromise;
  },

  async _loadSession() {
    this.status = "loading";
    const modelExists = await checkModelExists(this.modelUrl);
    if (!modelExists) {
      this.status = "missing";
      this.error = `${this.modelUrl} 不存在，继续使用 blendshape 规则情绪。`;
      return null;
    }

    const ort = await loadOrt();
    this._ort = ort;
    const session = await ort.InferenceSession.create(this.modelUrl, {
      executionProviders: ["wasm"],
    });
    this.inputName = session.inputNames[0];
    this.outputName = session.outputNames[0];
    this.status = "ready";
    this.error = "";
    return session;
  },

  _buildInputTensor(videoEl, faceBox) {
    const { data, dims } = buildFaceTensorData(videoEl, faceBox);
    return new this._ort.Tensor("float32", data, dims);
  },
};

async function checkModelExists(modelUrl) {
  try {
    const response = await fetch(modelUrl, { method: "HEAD", cache: "no-cache" });
    return response.ok;
  } catch (_) {
    return false;
  }
}

async function loadOrt() {
  if (!ortModulePromise) {
    ortModulePromise = import("onnxruntime-web").then((ort) => {
      const canUseThreads = window.crossOriginIsolated === true;
      ort.env.wasm.numThreads = canUseThreads
        ? Math.min(Math.max(navigator.hardwareConcurrency || 1, 1), 2)
        : 1;
      return ort;
    });
  }
  return ortModulePromise;
}

function buildFaceTensorData(videoEl, faceBox) {
  const canvas = ensureCanvas();
  const context = ensureContext(canvas);
  const videoWidth = Math.max(videoEl.videoWidth || videoEl.clientWidth || 1, 1);
  const videoHeight = Math.max(videoEl.videoHeight || videoEl.clientHeight || 1, 1);
  const crop = faceBoxToPixels(faceBox, videoWidth, videoHeight);

  context.clearRect(0, 0, EMOTION_INPUT_SIZE, EMOTION_INPUT_SIZE);
  context.drawImage(
    videoEl,
    crop.x,
    crop.y,
    crop.width,
    crop.height,
    0,
    0,
    EMOTION_INPUT_SIZE,
    EMOTION_INPUT_SIZE,
  );

  const rgba = context.getImageData(0, 0, EMOTION_INPUT_SIZE, EMOTION_INPUT_SIZE).data;
  const planeSize = EMOTION_INPUT_SIZE * EMOTION_INPUT_SIZE;
  const data = new Float32Array(EMOTION_INPUT_CHANNELS * planeSize);
  for (let pixelIndex = 0; pixelIndex < planeSize; pixelIndex += 1) {
    const rgbaOffset = pixelIndex * 4;
    for (let channel = 0; channel < EMOTION_INPUT_CHANNELS; channel += 1) {
      const value = rgba[rgbaOffset + channel] / 255;
      data[channel * planeSize + pixelIndex] = (value - IMAGENET_MEAN[channel]) / IMAGENET_STD[channel];
    }
  }

  return {
    data,
    dims: [1, EMOTION_INPUT_CHANNELS, EMOTION_INPUT_SIZE, EMOTION_INPUT_SIZE],
  };
}

function ensureCanvas() {
  if (!workCanvas) {
    workCanvas = document.createElement("canvas");
    workCanvas.width = EMOTION_INPUT_SIZE;
    workCanvas.height = EMOTION_INPUT_SIZE;
  }
  return workCanvas;
}

function ensureContext(canvas) {
  if (!workContext) {
    workContext = canvas.getContext("2d", { willReadFrequently: true });
  }
  return workContext;
}

function faceBoxToPixels(faceBox, videoWidth, videoHeight) {
  const padding = 0.18;
  const centerX = (faceBox.x + faceBox.width / 2) * videoWidth;
  const centerY = (faceBox.y + faceBox.height / 2) * videoHeight;
  const size = Math.max(faceBox.width * videoWidth, faceBox.height * videoHeight) * (1 + padding * 2);
  const x = clamp(centerX - size / 2, 0, videoWidth - 1);
  const y = clamp(centerY - size / 2, 0, videoHeight - 1);
  const maxWidth = videoWidth - x;
  const maxHeight = videoHeight - y;
  const pixelSize = Math.max(1, Math.min(size, maxWidth, maxHeight));
  return {
    x,
    y,
    width: pixelSize,
    height: pixelSize,
  };
}

function scoresFromOutput(outputData) {
  const raw = Array.from(outputData).slice(0, EMOTION_LABELS.length);
  const normalized = looksLikeProbabilities(raw) ? raw : softmax(raw);
  return Object.fromEntries(EMOTION_LABELS.map((label, index) => [label, normalized[index] || 0]));
}

function looksLikeProbabilities(values) {
  const sum = values.reduce((total, value) => total + Number(value || 0), 0);
  return values.every((value) => value >= 0 && value <= 1) && Math.abs(sum - 1) < 0.08;
}

function softmax(values) {
  const max = Math.max(...values);
  const exps = values.map((value) => Math.exp(value - max));
  const sum = exps.reduce((total, value) => total + value, 0) || 1;
  return exps.map((value) => value / sum);
}

function bestEmotion(scores) {
  return Object.entries(scores).reduce((best, item) => (item[1] > best[1] ? item : best), ["neutral", 0]);
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, Number(value)));
}
