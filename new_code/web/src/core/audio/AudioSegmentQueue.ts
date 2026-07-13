import { envelopeValueAt, wavRmsEnvelope } from "./WavRmsEnvelope";

export type PlayableAudio = {
  play: () => Promise<void>;
  stop: () => void;
  waitForEnd: () => Promise<void>;
  dispose: () => void;
};

export type AudioFactory = (
  data: ArrayBuffer,
  contentType: string,
  onLevel: (rms: number) => void,
) => PlayableAudio;

export type AudioPlaybackErrorCode =
  | "playback-blocked"
  | "unsupported-audio-format"
  | "audio-resource-unavailable"
  | "audio-playback-failed";

export class AudioPlaybackError extends Error {
  constructor(
    readonly code: AudioPlaybackErrorCode,
    message: string,
    override readonly cause?: unknown,
  ) {
    super(message);
    this.name = "AudioPlaybackError";
  }
}

export class AudioSegmentQueue {
  private tail: Promise<void> = Promise.resolve();
  private generation = 0;
  private current: PlayableAudio | null = null;

  constructor(
    private readonly createAudio: AudioFactory = browserAudioFactory,
    private readonly onLevel: (rms: number) => void = () => undefined,
  ) {}

  enqueue(
    data: ArrayBuffer,
    contentType: string,
    onStarted: () => void,
  ): Promise<void> {
    const generation = this.generation;
    const run = this.tail.catch(() => undefined).then(async () => {
      if (generation !== this.generation) return;
      const audio = this.createAudio(data, contentType, this.onLevel);
      this.current = audio;
      try {
        await audio.play();
        if (generation !== this.generation) return;
        onStarted();
        await audio.waitForEnd();
      } finally {
        if (this.current === audio) this.current = null;
        audio.dispose();
      }
    });
    this.tail = run;
    return run;
  }

  whenIdle(): Promise<void> {
    return this.tail.catch(() => undefined);
  }

  stop(): void {
    this.generation += 1;
    this.current?.stop();
    this.onLevel(0);
    this.current = null;
    this.tail = Promise.resolve();
  }
}

function browserAudioFactory(
  data: ArrayBuffer,
  contentType: string,
  onLevel: (rms: number) => void,
): PlayableAudio {
  if (typeof Audio !== "function" || typeof URL === "undefined" || typeof URL.createObjectURL !== "function") {
    throw new AudioPlaybackError(
      "audio-resource-unavailable",
      "当前浏览器无法创建回复音频播放器",
    );
  }
  const url = URL.createObjectURL(new Blob([data], { type: contentType }));
  let audio: HTMLAudioElement;
  try {
    audio = new Audio(url);
  } catch (error) {
    URL.revokeObjectURL(url);
    throw new AudioPlaybackError(
      "audio-resource-unavailable",
      "当前浏览器无法创建回复音频播放器",
      error,
    );
  }
  audio.preload = "auto";
  const mediaType = contentType.split(";", 1)[0]?.trim() ?? "";
  if (mediaType && audio.canPlayType(mediaType) === "") {
    URL.revokeObjectURL(url);
    throw new AudioPlaybackError(
      "unsupported-audio-format",
      `当前浏览器不支持回复音频格式：${mediaType}`,
    );
  }
  let markStarted!: () => void;
  let failStart!: (error: Error) => void;
  let finish!: () => void;
  let fail!: (error: Error) => void;
  let hasStarted = false;
  let disposed = false;
  let levelFrame = 0;
  const envelope = wavRmsEnvelope(data);
  const stopLevel = () => {
    cancelAnimationFrame(levelFrame);
    levelFrame = 0;
    onLevel(0);
  };
  const updateLevel = () => {
    onLevel(envelope ? envelopeValueAt(envelope, audio.currentTime) : 0);
    if (!audio.ended && !audio.paused) levelFrame = requestAnimationFrame(updateLevel);
  };
  const started = new Promise<void>((resolve, reject) => { markStarted = resolve; failStart = reject; });
  const ended = new Promise<void>((resolve, reject) => { finish = resolve; fail = reject; });
  const handlePlaying = () => {
    hasStarted = true;
    markStarted();
    stopLevel();
    levelFrame = requestAnimationFrame(updateLevel);
  };
  const handleEnded = () => { stopLevel(); finish(); };
  const handleError = () => {
    const unsupported = audio.error?.code === 4;
    const error = new AudioPlaybackError(
      unsupported ? "unsupported-audio-format" : "audio-playback-failed",
      unsupported ? "当前浏览器无法解码回复音频" : "回复音频播放失败",
      audio.error,
    );
    stopLevel();
    failStart(error);
    if (hasStarted) fail(error); else finish();
  };
  audio.addEventListener("playing", handlePlaying, { once: true });
  audio.addEventListener("ended", handleEnded, { once: true });
  audio.addEventListener("error", handleError, { once: true });
  return {
    play: async () => {
      try {
        await audio.play();
      } catch (error) {
        if (typeof DOMException !== "undefined"
          && error instanceof DOMException
          && error.name === "NotAllowedError") {
          throw new AudioPlaybackError(
            "playback-blocked",
            "浏览器阻止了语音播放，请点击页面后重试",
            error,
          );
        }
        throw new AudioPlaybackError("audio-playback-failed", "回复音频无法开始播放", error);
      }
      await started;
    },
    stop: () => { audio.pause(); stopLevel(); markStarted(); finish(); },
    waitForEnd: () => ended,
    dispose: () => {
      if (disposed) return;
      disposed = true;
      stopLevel();
      audio.pause();
      audio.removeEventListener("playing", handlePlaying);
      audio.removeEventListener("ended", handleEnded);
      audio.removeEventListener("error", handleError);
      audio.removeAttribute("src");
      audio.load();
      URL.revokeObjectURL(url);
    },
  };
}
