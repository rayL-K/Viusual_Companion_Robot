export const PCM_STREAM_TARGET_BUFFER_MS = 120;
export const PCM_STREAM_MAX_BUFFER_MS = 200;

const START_LEAD_SECONDS = 0.008;
const LIMIT_EPSILON_SECONDS = 0.004;

export type PcmStreamFormat = Readonly<{
  contentType: "audio/pcm";
  encoding: "pcm_s16le";
  sampleRateHz: number;
  channels: 1;
  sampleWidthBytes: 2;
}>;

export type PcmStreamPlayback = {
  readonly supported: boolean;
  prepare: () => boolean;
  unlock: () => Promise<boolean>;
  begin: (format: PcmStreamFormat) => Promise<void>;
  enqueue: (pcm: ArrayBuffer, onStarted?: () => void) => boolean;
  flush: () => void;
  complete: () => Promise<void>;
  whenIdle: () => Promise<void>;
  stop: () => void;
  dispose: () => void;
};

type PendingChunk = {
  buffer: AudioBuffer;
  rms: number;
  onStarted?: () => void;
};

type AudioScope = typeof globalThis & {
  webkitAudioContext?: typeof AudioContext;
};

export class PcmStreamPlayer implements PcmStreamPlayback {
  readonly supported = hasPcmStreamPlaybackSupport();
  private context: AudioContext | null = null;
  private format: PcmStreamFormat | null = null;
  private pending: PendingChunk[] = [];
  private pendingSeconds = 0;
  private playbackStartsAt = 0;
  private scheduledUntil = 0;
  private schedulingStarted = false;
  private completed = false;
  private sources = new Set<AudioBufferSourceNode>();
  private timers = new Set<ReturnType<typeof setTimeout>>();
  private idle: Promise<void> = Promise.resolve();
  private resolveIdle: (() => void) | null = null;

  constructor(private readonly onLevel: (rms: number) => void = () => undefined) {}

  prepare(): boolean {
    if (!this.supported) return false;
    if (this.context && this.context.state !== "closed") {
      return this.context.state === "running";
    }
    return this.createContext()?.state === "running";
  }

  async unlock(): Promise<boolean> {
    if (!this.supported) return false;
    const context = (
      this.context && this.context.state !== "closed"
        ? this.context
        : this.createContext()
    );
    if (!context) return false;
    if (context.state === "running") return true;
    try {
      await context.resume();
      return (context.state as AudioContextState) === "running";
    } catch (error) {
      console.warn("低延迟 PCM 播放未获用户手势授权，将保留 WAV 回放路径", error);
      return false;
    }
  }

  private createContext(): AudioContext | null {
    const scope = globalThis as AudioScope;
    const Context = scope.AudioContext ?? scope.webkitAudioContext;
    if (!Context) return null;
    try {
      this.context = new Context({ latencyHint: "interactive" });
      return this.context;
    } catch (error) {
      console.warn("低延迟 PCM 播放初始化失败，将保留 WAV 回放路径", error);
      this.context = null;
      return null;
    }
  }

  async begin(format: PcmStreamFormat): Promise<void> {
    validateFormat(format);
    if (!this.prepare() || !this.context) {
      throw new Error("当前浏览器无法启用低延迟 PCM 播放");
    }
    this.stop();
    this.format = format;
    this.idle = new Promise<void>((resolve) => { this.resolveIdle = resolve; });
    if (this.context.state !== "running") throw new Error("回复音频上下文尚未由用户手势解锁");
  }

  enqueue(pcm: ArrayBuffer, onStarted?: () => void): boolean {
    const context = this.context;
    const format = this.format;
    if (!context || !format || this.completed || pcm.byteLength === 0) return false;
    if (pcm.byteLength % 2 !== 0) return this.failClosed("PCM S16LE 音频长度不是偶数");
    const samples = pcm16LeToFloat32(pcm);
    const buffer = context.createBuffer(1, samples.length, format.sampleRateHz);
    buffer.copyToChannel(samples, 0);
    const chunk = { buffer, rms: rmsOf(samples), onStarted };

    if (!this.schedulingStarted) {
      if (!this.withinLimit(this.pendingSeconds + buffer.duration)) {
        return this.failClosed("流式回复预缓冲超过 200ms");
      }
      this.pending.push(chunk);
      this.pendingSeconds += buffer.duration;
      if (this.pendingSeconds * 1_000 >= PCM_STREAM_TARGET_BUFFER_MS) {
        this.flushPending();
      }
      return true;
    }
    if (!this.withinLimit(this.aheadSeconds() + buffer.duration)) {
      return this.failClosed("流式回复播放队列超过 200ms");
    }
    this.schedule(chunk);
    return true;
  }

  /**
   * Start a short completed segment without completing the reply timeline.
   * Later segments keep using `scheduledUntil`, so their arrival can never
   * stop or replace the tail that is already playing.
   */
  flush(): void {
    if (!this.context || !this.format || this.completed) return;
    this.flushPending();
  }

  complete(): Promise<void> {
    if (!this.context || !this.format) return this.idle;
    this.completed = true;
    if (!this.schedulingStarted) this.flushPending();
    this.finishIfDrained();
    return this.idle;
  }

  whenIdle(): Promise<void> {
    return this.idle;
  }

  stop(): void {
    for (const timer of this.timers) clearTimeout(timer);
    this.timers.clear();
    for (const source of this.sources) {
      source.onended = null;
      try {
        source.stop();
      } catch {
        // A source that already ended is harmless during generation invalidation.
      }
      source.disconnect();
    }
    this.sources.clear();
    this.pending = [];
    this.pendingSeconds = 0;
    this.playbackStartsAt = 0;
    this.scheduledUntil = 0;
    this.schedulingStarted = false;
    this.completed = false;
    this.format = null;
    this.onLevel(0);
    this.resolveIdle?.();
    this.resolveIdle = null;
    this.idle = Promise.resolve();
  }

  dispose(): void {
    this.stop();
    const context = this.context;
    this.context = null;
    if (!context || context.state === "closed") return;
    void context.close().catch((error: unknown) => {
      console.warn("低延迟 PCM 播放资源释放失败", error);
    });
  }

  private flushPending(): void {
    if (!this.context || this.pending.length === 0) {
      this.finishIfDrained();
      return;
    }
    this.schedulingStarted = true;
    this.playbackStartsAt = Math.max(
      this.scheduledUntil,
      this.context.currentTime + START_LEAD_SECONDS,
    );
    this.scheduledUntil = this.playbackStartsAt;
    const chunks = this.pending;
    this.pending = [];
    this.pendingSeconds = 0;
    for (const chunk of chunks) this.schedule(chunk);
  }

  private schedule(chunk: PendingChunk): void {
    const context = this.context;
    if (!context) return;
    const source = context.createBufferSource();
    source.buffer = chunk.buffer;
    source.connect(context.destination);
    const startsAt = Math.max(this.scheduledUntil, context.currentTime + START_LEAD_SECONDS);
    if (this.sources.size === 0 && this.scheduledUntil <= context.currentTime) {
      this.playbackStartsAt = startsAt;
    }
    this.scheduledUntil = startsAt + chunk.buffer.duration;
    this.sources.add(source);
    const startDelayMs = Math.max(0, (startsAt - context.currentTime) * 1_000);
    const timer = setTimeout(() => {
      this.timers.delete(timer);
      if (!this.sources.has(source)) return;
      this.onLevel(chunk.rms);
      chunk.onStarted?.();
    }, startDelayMs);
    this.timers.add(timer);
    source.onended = () => {
      this.sources.delete(source);
      source.disconnect();
      if (this.sources.size === 0) this.onLevel(0);
      this.finishIfDrained();
    };
    source.start(startsAt);
  }

  private aheadSeconds(): number {
    if (!this.context) return 0;
    const playoutCursor = Math.max(this.context.currentTime, this.playbackStartsAt);
    return Math.max(0, this.scheduledUntil - playoutCursor);
  }

  private withinLimit(seconds: number): boolean {
    return seconds <= PCM_STREAM_MAX_BUFFER_MS / 1_000 + LIMIT_EPSILON_SECONDS;
  }

  private failClosed(message: string): false {
    console.error(message);
    this.stop();
    return false;
  }

  private finishIfDrained(): void {
    if (!this.completed || this.sources.size > 0 || this.pending.length > 0) return;
    this.format = null;
    this.onLevel(0);
    this.resolveIdle?.();
    this.resolveIdle = null;
  }
}

function hasPcmStreamPlaybackSupport(): boolean {
  const scope = globalThis as AudioScope;
  const Context = scope.AudioContext ?? scope.webkitAudioContext;
  return Boolean(
    Context
    && typeof Context.prototype.createBuffer === "function"
    && typeof Context.prototype.createBufferSource === "function",
  );
}

export function pcm16LeToFloat32(pcm: ArrayBuffer): Float32Array<ArrayBuffer> {
  if (pcm.byteLength % 2 !== 0) throw new Error("PCM S16LE 音频长度必须为偶数");
  const input = new DataView(pcm);
  const output = new Float32Array(pcm.byteLength / 2);
  for (let index = 0; index < output.length; index += 1) {
    const sample = input.getInt16(index * 2, true);
    output[index] = sample < 0 ? sample / 32_768 : sample / 32_767;
  }
  return output;
}

function validateFormat(format: PcmStreamFormat): void {
  if (
    format.contentType !== "audio/pcm"
    || format.encoding !== "pcm_s16le"
    || format.channels !== 1
    || format.sampleWidthBytes !== 2
    || !Number.isSafeInteger(format.sampleRateHz)
    || format.sampleRateHz !== 24_000
  ) {
    throw new Error("流式回复音频必须是 24kHz mono PCM S16LE");
  }
}

function rmsOf(samples: Float32Array): number {
  if (samples.length === 0) return 0;
  let energy = 0;
  for (const sample of samples) energy += sample * sample;
  return Math.min(1, Math.sqrt(energy / samples.length));
}
