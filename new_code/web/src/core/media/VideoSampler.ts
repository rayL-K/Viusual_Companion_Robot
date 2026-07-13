import type { MediaErrorDetails } from "./MediaError";
import { mediaError } from "./MediaError";

type FrameHandler = (jpeg: ArrayBuffer) => boolean | void;
type SamplingErrorHandler = (error: MediaErrorDetails) => void;

export type VideoSamplerStatus = {
  active: boolean;
  encoder: "offscreen-canvas" | "html-canvas" | "unavailable";
  error?: MediaErrorDetails;
};

export class VideoSampler {
  private timer = 0;
  private generation = 0;
  private busy = false;
  private fallbackCanvas: HTMLCanvasElement | null = null;

  constructor(
    private readonly intervalMs = 500,
    private readonly maxWidth = 384,
    private readonly quality = 0.56,
  ) {}

  start(
    video: HTMLVideoElement,
    onFrame: FrameHandler,
    onError: SamplingErrorHandler = () => undefined,
  ): VideoSamplerStatus {
    this.stop();
    const encoder = preferredEncoder();
    if (encoder === "unavailable") {
      const error = mediaError(
        "frame-encoding-unavailable",
        "video-sampling",
        "当前浏览器无法编码视觉关键帧，本地摄像头预览仍可正常使用",
        false,
      ).details;
      onError(error);
      return { active: false, encoder, error };
    }

    const generation = this.generation;
    const capture = async () => {
      if (generation !== this.generation) return;
      if (!this.busy && video.readyState >= 2) {
        this.busy = true;
        try {
          await waitForIdle(250);
          const blob = await this.capture(video);
          if (generation === this.generation) {
            const accepted = onFrame(await blob.arrayBuffer());
            if (accepted === false) {
              onError(mediaError(
                "frame-upload-unavailable",
                "video-sampling",
                "视觉链路暂未连接，本地摄像头预览仍保持流畅",
                true,
              ).details);
            }
          }
        } catch (cause) {
          onError(mediaError(
            "frame-encoding-failed",
            "video-sampling",
            "视觉关键帧编码失败，本地摄像头预览不受影响",
            true,
            cause instanceof Error ? cause.name : undefined,
            cause,
          ).details);
        } finally {
          this.busy = false;
        }
      }
      if (generation === this.generation) this.timer = window.setTimeout(capture, this.intervalMs);
    };
    this.timer = window.setTimeout(capture, this.intervalMs);
    return { active: true, encoder };
  }

  stop(): void {
    this.generation += 1;
    if (this.timer) window.clearTimeout(this.timer);
    this.timer = 0;
    if (this.fallbackCanvas) {
      this.fallbackCanvas.width = 0;
      this.fallbackCanvas.height = 0;
      this.fallbackCanvas = null;
    }
  }

  private async capture(video: HTMLVideoElement): Promise<Blob> {
    if (video.videoWidth < 1 || video.videoHeight < 1) {
      throw new Error("摄像头画面尺寸尚未就绪");
    }
    const scale = Math.min(1, this.maxWidth / video.videoWidth);
    const width = Math.max(1, Math.round(video.videoWidth * scale));
    const height = Math.max(1, Math.round(video.videoHeight * scale));
    if (supportsOffscreenEncoder()) {
      try {
        return await captureOffscreen(video, width, height, this.quality);
      } catch (error) {
        if (!supportsHtmlCanvasEncoder()) throw error;
      }
    }
    if (!supportsHtmlCanvasEncoder()) throw new Error("浏览器没有可用的画面编码接口");
    this.fallbackCanvas ||= document.createElement("canvas");
    const canvas = this.fallbackCanvas;
    if (canvas.width !== width) canvas.width = width;
    if (canvas.height !== height) canvas.height = height;
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) throw new Error("无法创建视觉采样画布");
    context.drawImage(video, 0, 0, width, height);
    return await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob(
        (blob) => blob ? resolve(blob) : reject(new Error("视觉关键帧编码失败")),
        "image/jpeg",
        this.quality,
      );
    });
  }
}

function preferredEncoder(): VideoSamplerStatus["encoder"] {
  if (supportsOffscreenEncoder()) return "offscreen-canvas";
  if (supportsHtmlCanvasEncoder()) return "html-canvas";
  return "unavailable";
}

function supportsOffscreenEncoder(): boolean {
  return typeof OffscreenCanvas === "function"
    && typeof OffscreenCanvas.prototype.convertToBlob === "function"
    && typeof createImageBitmap === "function";
}

function supportsHtmlCanvasEncoder(): boolean {
  return typeof document !== "undefined"
    && typeof HTMLCanvasElement === "function"
    && typeof HTMLCanvasElement.prototype.toBlob === "function";
}

async function captureOffscreen(
  video: HTMLVideoElement,
  width: number,
  height: number,
  quality: number,
): Promise<Blob> {
  const bitmap = await createImageBitmap(video);
  try {
    const canvas = new OffscreenCanvas(width, height);
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) throw new Error("无法创建离屏视觉采样画布");
    context.drawImage(bitmap, 0, 0, width, height);
    return await canvas.convertToBlob({ type: "image/jpeg", quality });
  } finally {
    bitmap.close();
  }
}

function waitForIdle(timeoutMs: number): Promise<void> {
  const idle = (window as typeof window & {
    requestIdleCallback?: (callback: () => void, options: { timeout: number }) => number;
  }).requestIdleCallback;
  if (!idle) return new Promise((resolve) => window.setTimeout(resolve, 0));
  return new Promise((resolve) => idle(() => resolve(), { timeout: timeoutMs }));
}
