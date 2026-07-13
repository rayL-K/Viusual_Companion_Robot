import type { MediaErrorDetails } from "./MediaError";
import { mediaError, normalizeMediaError } from "./MediaError";

export const PCM_SAMPLE_RATE = 16_000;
export const PCM_FRAME_SAMPLES = 320;
export const PCM_FRAME_DURATION_MS = PCM_FRAME_SAMPLES / PCM_SAMPLE_RATE * 1000;

export type ActivePcmCaptureMode = "audio-worklet" | "script-processor";

export type PcmCaptureResult = {
  mode: ActivePcmCaptureMode;
  degradedReason?: MediaErrorDetails;
};

export type PcmCaptureEnvironment = {
  createContext: () => AudioContext;
  createWorkletNode: (context: AudioContext) => AudioWorkletNode;
  workletModuleUrl: string;
};

const BROWSER_ENVIRONMENT: PcmCaptureEnvironment = {
  createContext: () => new AudioContext({ latencyHint: "interactive" }),
  createWorkletNode: (context) => new AudioWorkletNode(context, "veyrasoul-pcm-capture", {
    numberOfInputs: 1,
    numberOfOutputs: 1,
    outputChannelCount: [1],
    processorOptions: { targetRate: PCM_SAMPLE_RATE, frameSamples: PCM_FRAME_SAMPLES },
  }),
  workletModuleUrl: "/audio-capture-worklet.js",
};

export class PcmCapture {
  private context: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private workletNode: AudioWorkletNode | null = null;
  private scriptNode: ScriptProcessorNode | null = null;
  private silentGain: GainNode | null = null;
  private enabled = true;
  private closing: Promise<void> = Promise.resolve();

  constructor(private readonly environment: PcmCaptureEnvironment = BROWSER_ENVIRONMENT) {}

  async start(stream: MediaStream, onFrame: (frame: ArrayBuffer) => void): Promise<PcmCaptureResult> {
    this.stop();
    await this.closing;
    if (!stream.getAudioTracks().length) {
      throw mediaError("device-not-found", "pcm-capture", "媒体流中没有麦克风音轨", true);
    }
    let context: AudioContext;
    try {
      context = this.environment.createContext();
    } catch (error) {
      throw mediaError(
        "audio-context-unavailable",
        "pcm-capture",
        "当前浏览器无法创建实时音频处理环境",
        false,
        error instanceof Error ? error.name : undefined,
        error,
      );
    }
    this.context = context;
    try {
      this.source = context.createMediaStreamSource(stream);
      this.silentGain = context.createGain();
      this.silentGain.gain.value = 0;
      const result = await this.connectCaptureGraph(context, onFrame);
      await context.resume();
      if (context.state !== "running") {
        throw mediaError(
          "audio-context-suspended",
          "pcm-capture",
          "浏览器尚未允许麦克风音频处理，请点击页面后重试",
          true,
        );
      }
      this.enabled = true;
      return result;
    } catch (error) {
      this.stop();
      await this.closing;
      throw normalizeMediaError(error, "pcm-capture");
    }
  }

  setEnabled(enabled: boolean): void {
    this.enabled = enabled;
  }

  stop(): void {
    if (this.workletNode) this.workletNode.port.onmessage = null;
    if (this.scriptNode) this.scriptNode.onaudioprocess = null;
    disconnect(this.workletNode);
    disconnect(this.scriptNode);
    disconnect(this.source);
    disconnect(this.silentGain);
    const context = this.context;
    this.context = null;
    this.source = null;
    this.workletNode = null;
    this.scriptNode = null;
    this.silentGain = null;
    this.enabled = true;
    if (context && context.state !== "closed") {
      this.closing = context.close().catch(() => undefined);
    }
  }

  async whenStopped(): Promise<void> {
    await this.closing;
  }

  private async connectCaptureGraph(
    context: AudioContext,
    onFrame: (frame: ArrayBuffer) => void,
  ): Promise<PcmCaptureResult> {
    let workletFailure: MediaErrorDetails | undefined;
    if (context.audioWorklet && typeof this.environment.createWorkletNode === "function") {
      try {
        await context.audioWorklet.addModule(this.environment.workletModuleUrl);
        const node = this.environment.createWorkletNode(context);
        node.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
          if (this.enabled) onFrame(event.data);
        };
        this.workletNode = node;
        this.source?.connect(node).connect(this.silentGain!).connect(context.destination);
        return { mode: "audio-worklet" };
      } catch (error) {
        if (this.workletNode) this.workletNode.port.onmessage = null;
        disconnect(this.workletNode);
        disconnect(this.source);
        disconnect(this.silentGain);
        this.workletNode = null;
        workletFailure = mediaError(
          "audio-worklet-unavailable",
          "pcm-capture",
          "AudioWorklet 加载失败，已使用兼容采集模式",
          true,
          error instanceof Error ? error.name : undefined,
          error,
        ).details;
      }
    }

    if (typeof context.createScriptProcessor !== "function") {
      throw mediaError(
        "pcm-capture-unavailable",
        "pcm-capture",
        "当前浏览器既不支持 AudioWorklet，也没有可用的 PCM 兼容采集接口",
        false,
      );
    }
    const framer = new Pcm16Framer(context.sampleRate, (frame) => {
      if (this.enabled) onFrame(frame);
    });
    const node = context.createScriptProcessor(1024, 1, 1);
    node.onaudioprocess = (event) => {
      const input = event.inputBuffer.getChannelData(0);
      framer.push(input);
      event.outputBuffer.getChannelData(0).fill(0);
    };
    this.scriptNode = node;
    this.source?.connect(node).connect(this.silentGain!).connect(context.destination);
    return {
      mode: "script-processor",
      degradedReason: workletFailure ?? mediaError(
        "audio-worklet-unavailable",
        "pcm-capture",
        "当前浏览器不支持 AudioWorklet，已使用兼容采集模式",
        true,
      ).details,
    };
  }
}

export class Pcm16Framer {
  private phase = 0;
  private sum = 0;
  private count = 0;
  private frame = new Int16Array(PCM_FRAME_SAMPLES);
  private frameIndex = 0;

  constructor(
    private readonly sourceRate: number,
    private readonly onFrame: (frame: ArrayBuffer) => void,
  ) {
    if (!Number.isFinite(sourceRate) || sourceRate < PCM_SAMPLE_RATE) {
      throw new Error(`不支持的麦克风采样率：${sourceRate}`);
    }
  }

  push(samples: Float32Array): void {
    for (const sample of samples) {
      this.sum += sample;
      this.count += 1;
      this.phase += PCM_SAMPLE_RATE;
      if (this.phase < this.sourceRate) continue;
      this.phase -= this.sourceRate;
      const average = Math.max(-1, Math.min(1, this.sum / this.count));
      this.frame[this.frameIndex] = average < 0 ? average * 32768 : average * 32767;
      this.frameIndex += 1;
      this.sum = 0;
      this.count = 0;
      if (this.frameIndex < this.frame.length) continue;
      this.onFrame(this.frame.buffer);
      this.frame = new Int16Array(PCM_FRAME_SAMPLES);
      this.frameIndex = 0;
    }
  }
}

function disconnect(node: AudioNode | null): void {
  if (!node) return;
  try {
    node.disconnect();
  } catch {
    // 部分浏览器会在尚未连接的节点上抛 InvalidAccessError；节点引用仍会被释放。
  }
}
