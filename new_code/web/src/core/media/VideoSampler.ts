type FrameHandler = (jpeg: ArrayBuffer) => void;

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

  start(video: HTMLVideoElement, onFrame: FrameHandler): void {
    this.stop();
    const generation = this.generation;
    const capture = async () => {
      if (generation !== this.generation) return;
      if (!this.busy && video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
        this.busy = true;
        try {
          await waitForIdle(250);
          const blob = await this.capture(video);
          if (generation === this.generation) onFrame(await blob.arrayBuffer());
        } catch (error) {
          // 关键帧编码失败不应拖垮本地 60 FPS 预览；下一周期会自动重试。
          console.warn("视觉关键帧采样失败，将在下一周期重试", error);
        } finally {
          this.busy = false;
        }
      }
      if (generation === this.generation) this.timer = window.setTimeout(capture, this.intervalMs);
    };
    this.timer = window.setTimeout(capture, this.intervalMs);
  }

  stop(): void {
    this.generation += 1;
    if (this.timer) window.clearTimeout(this.timer);
    this.timer = 0;
  }

  private async capture(video: HTMLVideoElement): Promise<Blob> {
    const scale = Math.min(1, this.maxWidth / video.videoWidth);
    const width = Math.max(1, Math.round(video.videoWidth * scale));
    const height = Math.max(1, Math.round(video.videoHeight * scale));
    if (typeof OffscreenCanvas !== "undefined" && typeof createImageBitmap === "function") {
      const bitmap = await createImageBitmap(video);
      try {
        const canvas = new OffscreenCanvas(width, height);
        const context = canvas.getContext("2d", { alpha: false });
        if (!context) throw new Error("无法创建离屏视觉采样画布");
        context.drawImage(bitmap, 0, 0, width, height);
        return await canvas.convertToBlob({ type: "image/jpeg", quality: this.quality });
      } finally {
        bitmap.close();
      }
    }
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

function waitForIdle(timeoutMs: number): Promise<void> {
  const idle = (window as typeof window & {
    requestIdleCallback?: (callback: () => void, options: { timeout: number }) => number;
  }).requestIdleCallback;
  if (!idle) return new Promise((resolve) => window.setTimeout(resolve, 0));
  return new Promise((resolve) => idle(() => resolve(), { timeout: timeoutMs }));
}
