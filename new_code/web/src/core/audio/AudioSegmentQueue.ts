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
  const url = URL.createObjectURL(new Blob([data], { type: contentType }));
  const audio = new Audio(url);
  audio.preload = "auto";
  let markStarted!: () => void;
  let failStart!: (error: Error) => void;
  let finish!: () => void;
  let fail!: (error: Error) => void;
  let hasStarted = false;
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
  audio.addEventListener("playing", () => {
    hasStarted = true;
    markStarted();
    stopLevel();
    levelFrame = requestAnimationFrame(updateLevel);
  }, { once: true });
  audio.addEventListener("ended", () => { stopLevel(); finish(); }, { once: true });
  audio.addEventListener("error", () => {
    const error = new Error("音频播放失败");
    stopLevel();
    failStart(error);
    if (hasStarted) fail(error); else finish();
  }, { once: true });
  return {
    play: async () => {
      await audio.play();
      await started;
    },
    stop: () => { audio.pause(); stopLevel(); markStarted(); finish(); },
    waitForEnd: () => ended,
    dispose: () => { stopLevel(); URL.revokeObjectURL(url); },
  };
}
