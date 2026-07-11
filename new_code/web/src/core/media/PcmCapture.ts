export const PCM_SAMPLE_RATE = 16_000;
export const PCM_FRAME_SAMPLES = 320;
export const PCM_FRAME_DURATION_MS = PCM_FRAME_SAMPLES / PCM_SAMPLE_RATE * 1000;

export class PcmCapture {
  private context: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private node: AudioWorkletNode | null = null;
  private silentGain: GainNode | null = null;
  private enabled = true;

  async start(stream: MediaStream, onFrame: (frame: ArrayBuffer) => void): Promise<void> {
    this.stop();
    if (!stream.getAudioTracks().length) throw new Error("媒体流中没有麦克风音轨");
    const context = new AudioContext({ latencyHint: "interactive" });
    try {
      await context.audioWorklet.addModule("/audio-capture-worklet.js");
      const source = context.createMediaStreamSource(stream);
      const node = new AudioWorkletNode(context, "veyrasoul-pcm-capture", {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        outputChannelCount: [1],
        processorOptions: { targetRate: PCM_SAMPLE_RATE, frameSamples: PCM_FRAME_SAMPLES },
      });
      const silentGain = context.createGain();
      silentGain.gain.value = 0;
      node.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
        if (this.enabled) onFrame(event.data);
      };
      source.connect(node).connect(silentGain).connect(context.destination);
      await context.resume();
      this.context = context;
      this.source = source;
      this.node = node;
      this.silentGain = silentGain;
      this.enabled = true;
    } catch (error) {
      await context.close();
      throw error;
    }
  }

  setEnabled(enabled: boolean): void {
    this.enabled = enabled;
  }

  stop(): void {
    this.node?.disconnect();
    this.source?.disconnect();
    this.silentGain?.disconnect();
    if (this.context) void this.context.close();
    this.context = null;
    this.source = null;
    this.node = null;
    this.silentGain = null;
    this.enabled = true;
  }
}
