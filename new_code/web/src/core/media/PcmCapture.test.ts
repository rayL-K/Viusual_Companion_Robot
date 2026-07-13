import { describe, expect, it } from "vitest";

import {
  Pcm16Framer,
  PcmCapture,
  PCM_FRAME_DURATION_MS,
  PCM_FRAME_SAMPLES,
  PCM_SAMPLE_RATE,
} from "./PcmCapture";

describe("PCM capture contract", () => {
  it("emits exact 20 ms frames for streaming ASR", () => {
    expect(PCM_SAMPLE_RATE).toBe(16_000);
    expect(PCM_FRAME_SAMPLES).toBe(320);
    expect(PCM_FRAME_DURATION_MS).toBe(20);
  });

  it("resamples 48 kHz input into exact PCM16 frames", () => {
    const frames: ArrayBuffer[] = [];
    const framer = new Pcm16Framer(48_000, (frame) => frames.push(frame));
    framer.push(new Float32Array(960).fill(0.5));
    expect(frames).toHaveLength(1);
    const samples = new Int16Array(frames[0]!);
    expect(samples).toHaveLength(PCM_FRAME_SAMPLES);
    expect(samples[0]).toBeCloseTo(16_384, -1);
  });

  it("uses and reports the safe PCM compatibility path when AudioWorklet is absent", async () => {
    const graph = fakeAudioGraph();
    const capture = new PcmCapture({
      createContext: () => graph.context,
      createWorkletNode: () => { throw new Error("should not create worklet"); },
      workletModuleUrl: "/unused.js",
    });
    const frames: ArrayBuffer[] = [];
    const stream = { getAudioTracks: () => [{}] } as unknown as MediaStream;
    const result = await capture.start(stream, (frame) => frames.push(frame));
    expect(result.mode).toBe("script-processor");
    expect(result.degradedReason?.code).toBe("audio-worklet-unavailable");

    capture.setEnabled(false);
    graph.process(new Float32Array(960).fill(0.25));
    expect(frames).toHaveLength(0);
    capture.setEnabled(true);
    graph.process(new Float32Array(960).fill(0.25));
    expect(frames).toHaveLength(1);
    capture.stop();
    await capture.whenStopped();
    expect(graph.closed).toBe(true);
  });
});

function fakeAudioGraph(): {
  context: AudioContext;
  process: (samples: Float32Array) => void;
  readonly closed: boolean;
} {
  let handler: ((event: AudioProcessingEvent) => void) | null = null;
  let closed = false;
  let state: AudioContextState = "suspended";
  const node = {
    connect: (next: AudioNode) => next,
    disconnect: () => undefined,
  };
  const script = {
    ...node,
    get onaudioprocess() { return handler; },
    set onaudioprocess(value) { handler = value; },
  };
  const context = {
    sampleRate: 48_000,
    get state() { return state; },
    destination: node,
    createMediaStreamSource: () => node,
    createGain: () => ({ ...node, gain: { value: 1 } }),
    createScriptProcessor: () => script,
    resume: async () => { state = "running"; },
    close: async () => { state = "closed"; closed = true; },
  } as unknown as AudioContext;
  return {
    context,
    process: (samples) => handler?.({
      inputBuffer: { getChannelData: () => samples },
      outputBuffer: { getChannelData: () => new Float32Array(samples.length) },
    } as unknown as AudioProcessingEvent),
    get closed() { return closed; },
  };
}
