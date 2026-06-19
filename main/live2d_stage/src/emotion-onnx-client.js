const EMOTION_BACKEND_URL = "http://127.0.0.1:8766/emotion";
const EMOTION_INPUT_SIZE = 64;
const EMOTION_LABELS = ["neutral", "happiness", "surprise", "sadness", "anger", "disgust", "fear", "contempt"];

let workCanvas = null;
let workContext = null;

export const emotionOnnxClient = {
  status: "idle",
  error: "",
  modelUrl: "backend:ferplus",
  sourceUrl: "https://github.com/onnx/models/tree/main/validated/vision/body_analysis/emotion_ferplus",
  inputName: "",
  outputName: "",

  async classify(videoEl, faceBox) {
    if (!videoEl || !faceBox) {
      return null;
    }

    const imageBase64 = this._captureFace(videoEl, faceBox);
    if (!imageBase64) {
      return null;
    }

    try {
      const resp = await fetch(EMOTION_BACKEND_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image: imageBase64 }),
      });
      if (!resp.ok) {
        this.status = "error";
        this.error = `后端返回 ${resp.status}`;
        return null;
      }
      const data = await resp.json();
      this.status = "ready";
      return {
        emotion: data.emotion,
        confidence: data.confidence,
        fullScores: data.full_scores,
        source: "ferplus",
      };
    } catch (err) {
      this.status = "error";
      this.error = err?.message || "后端情绪服务不可用";
      return null;
    }
  },

  _captureFace(videoEl, faceBox) {
    const canvas = ensureCanvas();
    const context = ensureContext(canvas);
    const videoWidth = Math.max(videoEl.videoWidth || videoEl.clientWidth || 1, 1);
    const videoHeight = Math.max(videoEl.videoHeight || videoEl.clientHeight || 1, 1);
    const crop = faceBoxToPixels(faceBox, videoWidth, videoHeight);

    context.clearRect(0, 0, EMOTION_INPUT_SIZE, EMOTION_INPUT_SIZE);
    context.drawImage(
      videoEl,
      crop.x, crop.y, crop.width, crop.height,
      0, 0, EMOTION_INPUT_SIZE, EMOTION_INPUT_SIZE,
    );

    return canvas.toDataURL("image/jpeg", 0.85).split(",")[1];
  },
};

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
  return { x, y, width: pixelSize, height: pixelSize };
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, Number(value)));
}
