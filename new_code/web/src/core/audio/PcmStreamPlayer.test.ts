import { afterEach, describe, expect, it, vi } from "vitest";

import {
  PCM_STREAM_MAX_BUFFER_MS,
  PCM_STREAM_TARGET_BUFFER_MS,
  PcmStreamPlayer,
  pcm16LeToFloat32,
  type PcmStreamFormat,
} from "./PcmStreamPlayer";

const FORMAT = {
  contentType: "audio/pcm",
  encoding: "pcm_s16le",
  sampleRateHz: 24_000,
  channels: 1,
  sampleWidthBytes: 2,
} as const satisfies PcmStreamFormat;

class FakeAudioBuffer {
  readonly duration: number;
  samples = new Float32Array();

  constructor(readonly length: number, readonly sampleRate: number) {
    this.duration = length / sampleRate;
  }

  copyToChannel(samples: Float32Array): void {
    this.samples = new Float32Array(samples);
  }
}

class FakeAudioSource {
  buffer: AudioBuffer | null = null;
  onended: (() => void) | null = null;
  startsAt: number[] = [];
  stopCalls = 0;
  disconnectCalls = 0;

  connect(): void {}

  start(when = 0): void {
    this.startsAt.push(when);
  }

  stop(): void {
    this.stopCalls += 1;
  }

  disconnect(): void {
    this.disconnectCalls += 1;
  }

  finish(): void {
    this.onended?.();
  }
}

class FakeAudioContext {
  static instances: FakeAudioContext[] = [];
  static initialState: AudioContextState = "running";

  currentTime = 0;
  state: AudioContextState;
  destination = {} as AudioDestinationNode;
  readonly buffers: FakeAudioBuffer[] = [];
  readonly sources: FakeAudioSource[] = [];
  closeCalls = 0;

  constructor(_options?: AudioContextOptions) {
    this.state = FakeAudioContext.initialState;
    FakeAudioContext.instances.push(this);
  }

  createBuffer(_channels: number, length: number, sampleRate: number): AudioBuffer {
    const buffer = new FakeAudioBuffer(length, sampleRate);
    this.buffers.push(buffer);
    return buffer as unknown as AudioBuffer;
  }

  createBufferSource(): AudioBufferSourceNode {
    const source = new FakeAudioSource();
    this.sources.push(source);
    return source as unknown as AudioBufferSourceNode;
  }

  async resume(): Promise<void> {
    this.state = "running";
  }

  async close(): Promise<void> {
    this.closeCalls += 1;
    this.state = "closed";
  }
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  FakeAudioContext.instances = [];
  FakeAudioContext.initialState = "running";
});

describe("PcmStreamPlayer", () => {
  it("decodes signed little-endian PCM without changing channel semantics", () => {
    const bytes = new Uint8Array([
      0x00, 0x80,
      0x00, 0x00,
      0xff, 0x7f,
    ]);
    expect([...pcm16LeToFloat32(bytes.buffer)]).toEqual([-1, 0, 1]);
    expect(() => pcm16LeToFloat32(new ArrayBuffer(3))).toThrow("偶数");
  });

  it("accepts only 24kHz mono PCM S16LE", async () => {
    installAudioContext();
    const player = new PcmStreamPlayer();
    await expect(player.begin({ ...FORMAT, sampleRateHz: 16_000 })).rejects.toThrow("24kHz");
    await expect(player.begin(FORMAT)).resolves.toBeUndefined();
    player.stop();
  });

  it("does not claim support from a merely suspended context and unlocks it explicitly", async () => {
    FakeAudioContext.initialState = "suspended";
    installAudioContext();
    const player = new PcmStreamPlayer();

    expect(player.prepare()).toBe(false);
    await expect(player.unlock()).resolves.toBe(true);
    expect(player.prepare()).toBe(true);
    await expect(player.begin(FORMAT)).resolves.toBeUndefined();
    player.stop();
  });

  it("starts at the 120ms target and fails closed beyond 200ms queued audio", async () => {
    installAudioContext();
    const player = new PcmStreamPlayer();
    await player.begin(FORMAT);
    const context = requireContext();
    const fortyMs = new ArrayBuffer(24_000 * 2 * 40 / 1_000);

    expect(PCM_STREAM_TARGET_BUFFER_MS).toBe(120);
    expect(PCM_STREAM_MAX_BUFFER_MS).toBe(200);
    expect(player.enqueue(fortyMs)).toBe(true);
    expect(player.enqueue(fortyMs)).toBe(true);
    expect(context.sources).toHaveLength(0);
    expect(player.enqueue(fortyMs)).toBe(true);
    expect(context.sources).toHaveLength(3);
    expect(player.enqueue(fortyMs)).toBe(true);
    expect(player.enqueue(fortyMs)).toBe(true);
    expect(player.enqueue(fortyMs)).toBe(false);
    expect(context.sources.every((source) => source.stopCalls === 1)).toBe(true);
  });

  it("flushes short segments onto one continuous timeline without cutting the previous tail", async () => {
    vi.useFakeTimers();
    installAudioContext();
    const levels: number[] = [];
    const player = new PcmStreamPlayer((rms) => levels.push(rms));
    await player.begin(FORMAT);
    const context = requireContext();
    const fortyMs = pcmChunk(40, 8_000);
    const firstStarted = vi.fn();

    expect(player.enqueue(fortyMs, firstStarted)).toBe(true);
    player.flush();
    expect(context.sources).toHaveLength(1);
    expect(player.enqueue(fortyMs)).toBe(true);
    player.flush();
    expect(context.sources).toHaveLength(2);
    expect(context.sources[0]?.startsAt[0]).toBeCloseTo(0.008, 5);
    expect(context.sources[1]?.startsAt[0]).toBeCloseTo(0.048, 5);
    expect(context.sources.every((source) => source.stopCalls === 0)).toBe(true);

    await vi.advanceTimersByTimeAsync(8);
    expect(firstStarted).toHaveBeenCalledOnce();
    expect(levels.some((level) => level > 0)).toBe(true);

    let completed = false;
    const completion = player.complete().then(() => { completed = true; });
    await Promise.resolve();
    expect(completed).toBe(false);
    context.sources[0]?.finish();
    await Promise.resolve();
    expect(completed).toBe(false);
    context.sources[1]?.finish();
    await completion;
    expect(completed).toBe(true);
  });

  it("stop invalidates scheduled sources and resolves idle waiters", async () => {
    installAudioContext();
    const player = new PcmStreamPlayer();
    await player.begin(FORMAT);
    player.enqueue(pcmChunk(120, 1_000));
    const context = requireContext();
    expect(context.sources.length).toBeGreaterThan(0);

    player.stop();
    await expect(player.whenIdle()).resolves.toBeUndefined();
    expect(context.sources.every((source) => source.stopCalls === 1)).toBe(true);
  });

  it("disposes the AudioContext and can create a fresh context afterwards", async () => {
    installAudioContext();
    const player = new PcmStreamPlayer();
    await player.begin(FORMAT);
    const first = requireContext();

    player.dispose();
    await Promise.resolve();

    expect(first.closeCalls).toBe(1);
    expect(first.state).toBe("closed");
    expect(player.prepare()).toBe(true);
    expect(FakeAudioContext.instances).toHaveLength(2);
  });
});

function installAudioContext(): void {
  vi.stubGlobal("AudioContext", FakeAudioContext as unknown as typeof AudioContext);
}

function requireContext(): FakeAudioContext {
  const context = FakeAudioContext.instances[0];
  if (!context) throw new Error("Fake AudioContext 未创建");
  return context;
}

function pcmChunk(milliseconds: number, amplitude: number): ArrayBuffer {
  const samples = 24_000 * milliseconds / 1_000;
  const bytes = new ArrayBuffer(samples * 2);
  const view = new DataView(bytes);
  for (let index = 0; index < samples; index += 1) {
    view.setInt16(index * 2, amplitude, true);
  }
  return bytes;
}
