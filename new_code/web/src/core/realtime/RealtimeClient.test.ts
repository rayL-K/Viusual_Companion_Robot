import { afterEach, describe, expect, it, vi } from "vitest";

import { AudioSegmentQueue, type PlayableAudio } from "../audio/AudioSegmentQueue";
import type { PcmStreamFormat, PcmStreamPlayback } from "../audio/PcmStreamPlayer";
import { connectionPhase } from "../state/session";
import {
  BINARY_FLAG_START,
  BINARY_FLAG_STREAM,
  BINARY_KIND_AUDIO,
  BINARY_KIND_JPEG,
  BINARY_KIND_PCM16,
  createBinaryFrame,
  parseBinaryFrame,
  type ServerEvent,
} from "./protocol";
import { DEFAULT_REALTIME_BACKPRESSURE, type RealtimeBackpressureConfig } from "./backpressure";
import {
  RealtimeClient,
  realtimeUrl,
  type OutboundTransportStatus,
} from "./RealtimeClient";

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readyState = FakeWebSocket.CONNECTING;
  binaryType = "blob";
  bufferedAmount = 0;
  sent: unknown[] = [];
  private listeners = new Map<string, Array<(event: { data?: unknown; code?: number }) => void>>();

  constructor(readonly url: string) {
    FakeWebSocket.instances.push(this);
  }

  addEventListener(
    type: string,
    handler: (event: { data?: unknown; code?: number }) => void,
  ): void {
    const handlers = this.listeners.get(type) ?? [];
    handlers.push(handler);
    this.listeners.set(type, handlers);
  }

  send(data: unknown): void {
    this.sent.push(data);
  }

  close(code = 1000, _reason?: string): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.dispatch("close", { code });
  }

  serverClose(code = 1006): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.dispatch("close", { code });
  }

  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.dispatch("open");
  }

  message(data: unknown): void {
    this.dispatch("message", { data });
  }

  private dispatch(
    type: string,
    event: { data?: unknown; code?: number } = {},
  ): void {
    for (const handler of this.listeners.get(type) ?? []) handler(event);
  }
}

class FakePcmStream implements PcmStreamPlayback {
  prepareCalls = 0;
  unlockCalls = 0;
  beginFormats: PcmStreamFormat[] = [];
  enqueued: Array<{ pcm: ArrayBuffer; onStarted?: () => void }> = [];
  flushCalls = 0;
  completeCalls = 0;
  stopCalls = 0;
  disposeCalls = 0;
  acceptEnqueue = true;

  constructor(
    readonly supported = true,
    private prepared = true,
    private readonly unlocked = prepared,
  ) {}

  setPrepared(value: boolean): void {
    this.prepared = value;
  }

  prepare(): boolean {
    this.prepareCalls += 1;
    return this.prepared;
  }

  async unlock(): Promise<boolean> {
    this.unlockCalls += 1;
    return this.supported && this.unlocked;
  }

  async begin(format: PcmStreamFormat): Promise<void> {
    this.beginFormats.push(format);
  }

  enqueue(pcm: ArrayBuffer, onStarted?: () => void): boolean {
    if (!this.acceptEnqueue) return false;
    this.enqueued.push({ pcm, ...(onStarted ? { onStarted } : {}) });
    return true;
  }

  flush(): void {
    this.flushCalls += 1;
  }

  async complete(): Promise<void> {
    this.completeCalls += 1;
  }

  async whenIdle(): Promise<void> {}

  stop(): void {
    this.stopCalls += 1;
    this.enqueued = [];
  }

  dispose(): void {
    this.disposeCalls += 1;
    this.stop();
  }

  start(index: number): void {
    this.enqueued[index]?.onStarted?.();
  }
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  FakeWebSocket.instances = [];
});

describe("RealtimeClient reply generations", () => {
  it("releases its PCM AudioContext when the client lifecycle ends", () => {
    const pcm = new FakePcmStream();
    const { client } = connectedClient(undefined, undefined, pcm);

    client.disconnect();

    expect(pcm.disposeCalls).toBe(1);
  });

  it("reveals a segment only after its matching audio starts", async () => {
    let startPlayback!: () => void;
    const playbackStarted = new Promise<void>((resolve) => { startPlayback = resolve; });
    const queue = new AudioSegmentQueue(() => playable(playbackStarted));
    const { client, socket } = connectedClient(queue);
    const received: ServerEvent[] = [];
    client.onEvent((event) => received.push(event));

    socket.message(serverEvent("reply.phase", 1, { phase: "speaking" }));
    socket.message(createBinaryFrame(BINARY_KIND_AUDIO, 7n, 1n, new ArrayBuffer(2)));
    socket.message(serverEvent("reply.segment.ready", 1, { audioSeq: 7, text: "你好" }));
    await flushTasks();
    expect(received.some((event) => event.type === "reply.segment.ready")).toBe(false);

    startPlayback();
    await flushTasks();
    expect(received.find((event) => event.type === "reply.segment.ready")?.payload.text).toBe("你好");
    client.disconnect();
  });

  it("interrupts queued audio when a newer server generation begins", async () => {
    let finishFirst!: () => void;
    const firstEnded = new Promise<void>((resolve) => { finishFirst = resolve; });
    const queue = new AudioSegmentQueue(() => playable(Promise.resolve(), firstEnded, finishFirst));
    const { client, socket } = connectedClient(queue);
    const received: ServerEvent[] = [];
    client.onEvent((event) => received.push(event));

    socket.message(serverEvent("reply.phase", 1, { phase: "speaking" }));
    socket.message(createBinaryFrame(BINARY_KIND_AUDIO, 8n, 1n, new ArrayBuffer(2)));
    socket.message(serverEvent("reply.segment.ready", 1, { audioSeq: 8, text: "旧回复" }));
    socket.message(serverEvent("reply.completed", 1, {}));
    await flushTasks();

    socket.message(serverEvent("reply.phase", 2, { phase: "thinking" }));
    finishFirst();
    await flushTasks();

    expect(received.some((event) => event.type === "reply.phase" && event.generation === 2)).toBe(true);
    expect(received.some((event) => event.type === "reply.completed" && event.generation === 1)).toBe(false);
    client.disconnect();
  });

  it("never emits stale avatar intent after a new local or server generation", async () => {
    const { client, socket } = connectedClient(new AudioSegmentQueue(() => playable(Promise.resolve())));
    const received: ServerEvent[] = [];
    client.onEvent((event) => received.push(event));

    socket.message(serverEvent("reply.phase", 2, { phase: "thinking" }));
    socket.message(serverEvent("avatar.intent", 2, avatarIntentPayload({ expression: "attentive" })));
    client.send("turn.user_text", { text: "打断旧回复" });
    socket.message(serverEvent("avatar.intent", 2, avatarIntentPayload({ expression: "concerned" })));
    socket.message(serverEvent("avatar.intent", 3, avatarIntentPayload({ expression: "warm" })));
    socket.message(serverEvent("avatar.intent", 2, avatarIntentPayload({ expression: "delighted" })));
    await flushTasks();

    const expressions = received
      .filter((event) => event.type === "avatar.intent")
      .map((event) => event.payload.expression);
    expect(expressions).toEqual(["attentive", "warm"]);
    client.disconnect();
  });

  it("accepts generation zero after session.ready starts a new server domain", async () => {
    const { client, socket } = connectedClient(new AudioSegmentQueue(() => playable(Promise.resolve())));
    const received: ServerEvent[] = [];
    client.onEvent((event) => received.push(event));

    socket.message(serverEvent("reply.phase", 8, { phase: "thinking" }));
    socket.message(serverEvent("session.ready", 0, { protocol: 2 }));
    socket.message(serverEvent("reply.phase", 0, { phase: "thinking" }));
    await flushTasks();

    expect(received.filter((event) => event.type === "reply.phase").map((event) => event.generation))
      .toEqual([8, 0]);
    client.disconnect();
  });
});

describe("RealtimeClient reply-audio-stream-v1", () => {
  it("advertises the capability only when PCM playback can actually be prepared", () => {
    for (const [supported, prepared, advertised] of [
      [false, true, false],
      [true, false, false],
      [true, true, true],
    ] as const) {
      FakeWebSocket.instances = [];
      const pcm = new FakePcmStream(supported, prepared);
      const { client, socket } = connectedClient(undefined, undefined, pcm);
      const hello = controlEvents(socket)[0];
      const capabilities = (hello?.payload as { capabilities?: unknown[] }).capabilities ?? [];
      expect(capabilities.includes("reply-audio-stream-v1")).toBe(advertised);
      expect(pcm.prepareCalls).toBe(supported ? 1 : 0);
      client.disconnect();
    }
  });

  it("renegotiates streaming only after an explicit user-gesture unlock succeeds", async () => {
    const pcm = new FakePcmStream(true, false, true);
    const { client, socket } = connectedClient(undefined, undefined, pcm);
    expect((controlEvents(socket)[0]?.payload as { capabilities: string[] }).capabilities)
      .not.toContain("reply-audio-stream-v1");

    await expect(client.enableReplyAudioStream()).resolves.toBe(true);
    const hellos = controlEvents(socket).filter((event) => event.type === "session.hello");
    expect(pcm.unlockCalls).toBe(1);
    expect((hellos[1]?.payload as { capabilities: string[] }).capabilities)
      .toContain("reply-audio-stream-v1");
    client.disconnect();
  });

  it("advertises streaming when an initially suspended context later becomes running", async () => {
    const pcm = new FakePcmStream(true, false, true);
    const { client, socket } = connectedClient(undefined, undefined, pcm);
    pcm.setPrepared(true);

    await expect(client.enableReplyAudioStream()).resolves.toBe(true);

    const hellos = controlEvents(socket).filter((event) => event.type === "session.hello");
    expect(pcm.unlockCalls).toBe(0);
    expect((hellos[1]?.payload as { capabilities: string[] }).capabilities)
      .toContain("reply-audio-stream-v1");
    client.disconnect();
  });

  it("re-unlocks a suspended AudioContext even after streaming was advertised", async () => {
    const pcm = new FakePcmStream(true, true, true);
    const { client } = connectedClient(undefined, undefined, pcm);
    pcm.setPrepared(false);

    await expect(client.enableReplyAudioStream()).resolves.toBe(true);
    expect(pcm.unlockCalls).toBe(1);
    client.disconnect();
  });

  it("pairs binary-before-JSON chunks and keeps one continuous timeline across segments", async () => {
    const pcm = new FakePcmStream();
    const { client, socket } = connectedClient(undefined, undefined, pcm);
    const received: ServerEvent[] = [];
    client.onEvent((event) => received.push(event));
    negotiateStream(socket);
    socket.message(serverEvent("reply.phase", 1, { phase: "speaking" }));
    const stopBaseline = pcm.stopCalls;

    sendStreamPair(socket, 10, BINARY_FLAG_STREAM | BINARY_FLAG_START, streamStarted(0, 10));
    await flushTasks();
    expect(pcm.beginFormats).toEqual([PCM_FORMAT]);
    expect(received.some((event) => event.type === "reply.segment.started")).toBe(false);
    pcm.start(0);
    expect(received.find((event) => event.type === "reply.segment.started")?.payload.index).toBe(0);

    sendStreamPair(socket, 11, BINARY_FLAG_STREAM, streamChunk(0, 1, 11));
    socket.message(serverEvent("reply.segment.completed", 1, {
      index: 0,
      chunks: 2,
      audioBytes: 8,
    }));
    await flushTasks();
    expect(pcm.flushCalls).toBe(1);

    sendStreamPair(socket, 12, BINARY_FLAG_STREAM | BINARY_FLAG_START, streamStarted(1, 12));
    socket.message(serverEvent("reply.segment.completed", 1, {
      index: 1,
      chunks: 1,
      audioBytes: 4,
    }));
    socket.message(serverEvent("reply.completed", 1, {}));
    await flushTasks();

    expect(pcm.beginFormats).toHaveLength(1);
    expect(pcm.flushCalls).toBe(2);
    expect(pcm.completeCalls).toBe(1);
    expect(pcm.stopCalls).toBe(stopBaseline);
    expect(received.some((event) => event.type === "reply.completed")).toBe(true);
    client.disconnect();
  });

  it("rejects a chunk gap and renegotiates future replies onto the WAV path", async () => {
    const pcm = new FakePcmStream();
    const queue = new AudioSegmentQueue(() => playable(Promise.resolve()));
    const { client, socket } = connectedClient(queue, undefined, pcm);
    const received: ServerEvent[] = [];
    client.onEvent((event) => received.push(event));
    negotiateStream(socket);
    socket.message(serverEvent("reply.phase", 1, { phase: "speaking" }));
    sendStreamPair(socket, 20, BINARY_FLAG_STREAM | BINARY_FLAG_START, streamStarted(0, 20));
    await flushTasks();

    sendStreamPair(socket, 21, BINARY_FLAG_STREAM, streamChunk(0, 2, 21));
    await flushTasks();
    const hellos = controlEvents(socket).filter((event) => event.type === "session.hello");
    expect(hellos).toHaveLength(2);
    expect((hellos[1]?.payload as { capabilities: string[] }).capabilities)
      .not.toContain("reply-audio-stream-v1");
    expect(connectionPhase.value).toBe("online");
    await expect(client.enableReplyAudioStream()).resolves.toBe(false);

    socket.message(serverEvent("reply.completed", 1, {}));
    socket.message(serverEvent("session.hello.ack", 0, { capabilities: [] }));
    socket.message(serverEvent("reply.phase", 2, { phase: "speaking" }));
    socket.message(createBinaryFrame(BINARY_KIND_AUDIO, 22n, 1n, new ArrayBuffer(4)));
    socket.message(serverEvent("reply.segment.ready", 2, {
      audioSeq: 22,
      text: "WAV 回退仍可用",
      contentType: "audio/wav",
    }));
    await flushTasks();

    expect(received.some((event) => (
      event.type === "reply.segment.ready" && event.payload.text === "WAV 回退仍可用"
    ))).toBe(true);
    expect(received.some((event) => event.type === "reply.completed" && event.generation === 1))
      .toBe(false);
    client.disconnect();
  });

  it("binds every segment to one generation/turn and a contiguous segment index", async () => {
    const pcm = new FakePcmStream();
    const { client, socket } = connectedClient(undefined, undefined, pcm);
    negotiateStream(socket);
    socket.message(serverEvent("reply.phase", 1, { phase: "speaking" }));
    sendStreamPair(socket, 23, BINARY_FLAG_STREAM | BINARY_FLAG_START, streamStarted(0, 23));
    socket.message(serverEvent("reply.segment.completed", 1, {
      index: 0,
      chunks: 1,
      audioBytes: 4,
    }));
    await flushTasks();

    socket.message(createBinaryFrame(
      BINARY_KIND_AUDIO,
      24n,
      1n,
      new ArrayBuffer(4),
      BINARY_FLAG_STREAM | BINARY_FLAG_START,
    ));
    socket.message(serverEvent("reply.segment.started", 1, streamStarted(1, 24), "other-turn"));
    await flushTasks();
    expect(pcm.enqueued).toHaveLength(1);

    sendStreamPair(socket, 25, BINARY_FLAG_STREAM | BINARY_FLAG_START, streamStarted(2, 25));
    await flushTasks();
    expect(controlEvents(socket).filter((event) => event.type === "session.hello")).toHaveLength(2);
    client.disconnect();
  });

  it("bounds unmatched binary frames by audioSeq and fails closed when an evicted frame is cited", async () => {
    const pcm = new FakePcmStream();
    const { client, socket } = connectedClient(undefined, undefined, pcm);
    negotiateStream(socket);
    socket.message(serverEvent("reply.phase", 1, { phase: "speaking" }));
    for (let sequence = 1; sequence <= 9; sequence += 1) {
      socket.message(createBinaryFrame(
        BINARY_KIND_AUDIO,
        BigInt(sequence),
        1n,
        new ArrayBuffer(4),
        BINARY_FLAG_STREAM | BINARY_FLAG_START,
      ));
    }
    socket.message(serverEvent("reply.segment.started", 1, streamStarted(0, 1)));
    await flushTasks();

    expect(pcm.beginFormats).toHaveLength(0);
    expect(controlEvents(socket).filter((event) => event.type === "session.hello")).toHaveLength(2);
    client.disconnect();
  });

  it("drops stale chunks after cancel without poisoning the next negotiated mode", async () => {
    const pcm = new FakePcmStream();
    const { client, socket } = connectedClient(undefined, undefined, pcm);
    negotiateStream(socket);
    socket.message(serverEvent("reply.phase", 1, { phase: "speaking" }));
    sendStreamPair(socket, 30, BINARY_FLAG_STREAM | BINARY_FLAG_START, streamStarted(0, 30));
    await flushTasks();
    const stopsBeforeCancel = pcm.stopCalls;

    client.send("turn.cancel", {});
    expect(pcm.stopCalls).toBeGreaterThan(stopsBeforeCancel);
    expect(pcm.enqueued).toHaveLength(0);
    sendStreamPair(socket, 31, BINARY_FLAG_STREAM, streamChunk(0, 1, 31));
    await flushTasks();

    expect(controlEvents(socket).filter((event) => event.type === "session.hello")).toHaveLength(1);
    client.disconnect();
  });

  it("clears the current PCM timeline immediately on reply_failed", async () => {
    const pcm = new FakePcmStream();
    const { client, socket } = connectedClient(undefined, undefined, pcm);
    const received: ServerEvent[] = [];
    client.onEvent((event) => received.push(event));
    negotiateStream(socket);
    socket.message(serverEvent("reply.phase", 1, { phase: "speaking" }));
    sendStreamPair(socket, 35, BINARY_FLAG_STREAM | BINARY_FLAG_START, streamStarted(0, 35));
    await flushTasks();
    const activeStops = pcm.stopCalls;

    socket.message(serverEvent("error", 1, {
      code: "reply_failed",
      message: "upstream failed",
    }));
    expect(pcm.stopCalls).toBeGreaterThan(activeStops);
    expect(pcm.enqueued).toHaveLength(0);
    sendStreamPair(socket, 36, BINARY_FLAG_STREAM, streamChunk(0, 1, 36));
    socket.message(serverEvent("reply.completed", 1, {}));
    await flushTasks();

    expect(received.some((event) => event.type === "error")).toBe(true);
    expect(received.some((event) => event.type === "reply.completed")).toBe(false);
    expect(controlEvents(socket).filter((event) => event.type === "session.hello")).toHaveLength(1);
    client.disconnect();
  });

  it("stops and flushes PCM playback on a newer generation and on disconnect", async () => {
    const pcm = new FakePcmStream();
    const { client, socket } = connectedClient(undefined, undefined, pcm);
    negotiateStream(socket);
    socket.message(serverEvent("reply.phase", 1, { phase: "speaking" }));
    sendStreamPair(socket, 40, BINARY_FLAG_STREAM | BINARY_FLAG_START, streamStarted(0, 40));
    await flushTasks();
    const activeStops = pcm.stopCalls;

    socket.message(serverEvent("reply.phase", 2, { phase: "thinking" }));
    expect(pcm.stopCalls).toBeGreaterThan(activeStops);
    expect(pcm.enqueued).toHaveLength(0);
    const generationStops = pcm.stopCalls;
    socket.serverClose();
    expect(pcm.stopCalls).toBeGreaterThan(generationStops);
    client.disconnect();
  });
});

describe("RealtimeClient reconnect lifecycle", () => {
  it("sends a heartbeat every 25 seconds only while the socket is open", async () => {
    vi.useFakeTimers();
    const { client, socket } = connectedClient();
    expect(controlEvents(socket).map((event) => event.type)).toEqual(["session.hello"]);

    await vi.advanceTimersByTimeAsync(24_999);
    expect(controlEvents(socket).map((event) => event.type)).toEqual(["session.hello"]);
    await vi.advanceTimersByTimeAsync(1);
    expect(controlEvents(socket).at(-1)).toEqual(expect.objectContaining({
      v: 2,
      type: "session.heartbeat",
      payload: {},
    }));

    socket.serverClose();
    const countAfterClose = socket.sent.length;
    await vi.advanceTimersByTimeAsync(24_999);
    expect(socket.sent).toHaveLength(countAfterClose);
    client.disconnect();
  });

  it("reconnects with exponential backoff and resets it after open", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeWebSocket);
    const client = new RealtimeClient("ws://test/v2/realtime");
    client.connect();
    const first = requireSocket(0);

    first.serverClose();
    await vi.advanceTimersByTimeAsync(499);
    expect(FakeWebSocket.instances).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    const second = requireSocket(1);

    second.serverClose();
    await vi.advanceTimersByTimeAsync(999);
    expect(FakeWebSocket.instances).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1);
    const third = requireSocket(2);
    third.open();
    third.serverClose();
    await vi.advanceTimersByTimeAsync(500);

    expect(FakeWebSocket.instances).toHaveLength(4);
    client.disconnect();
  });

  it("disconnect cancels pending retries and stale socket close events", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeWebSocket);
    const client = new RealtimeClient("ws://test/v2/realtime");
    client.connect();
    const first = requireSocket(0);
    first.serverClose();
    await vi.advanceTimersByTimeAsync(500);
    const second = requireSocket(1);
    second.open();

    first.serverClose();
    expect(connectionPhase.value).toBe("online");
    client.disconnect();
    await vi.advanceTimersByTimeAsync(30_000);

    expect(connectionPhase.value).toBe("offline");
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it("refreshes admission before reconnecting after a 4401 close", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeWebSocket);
    const refreshAdmission = vi.fn(async () => undefined);
    const client = new RealtimeClient(
      "ws://test/v2/realtime",
      undefined,
      undefined,
      refreshAdmission,
    );
    client.connect();
    const first = requireSocket(0);

    first.serverClose(4401);
    await vi.advanceTimersByTimeAsync(500);

    expect(refreshAdmission).toHaveBeenCalledTimes(1);
    expect(FakeWebSocket.instances).toHaveLength(2);
    client.disconnect();
  });
});

describe("RealtimeClient outbound backpressure", () => {
  it("keeps control sends immediate and retains only the latest delayed video frame", async () => {
    vi.useFakeTimers();
    const config = testBackpressure();
    const { client, socket } = connectedClient(undefined, config);
    socket.bufferedAmount = 8_000;

    expect(client.sendBinary(BINARY_KIND_JPEG, Uint8Array.of(1).buffer)).toBe(true);
    expect(client.sendBinary(BINARY_KIND_JPEG, Uint8Array.of(2).buffer)).toBe(true);
    expect(binaryFrames(socket)).toHaveLength(0);

    expect(client.send("turn.cancel", {})).toBe(true);
    expect(JSON.parse(String(socket.sent.at(-1))).type).toBe("turn.cancel");

    socket.bufferedAmount = 0;
    await vi.advanceTimersByTimeAsync(config.drainPollIntervalMs);
    const frames = binaryFrames(socket);
    expect(frames).toHaveLength(1);
    expect(frames[0]?.kind).toBe(BINARY_KIND_JPEG);
    expect([...new Uint8Array(frames[0]!.payload)]).toEqual([2]);
    client.disconnect();
  });

  it("caps PCM backlog and emits one congestion transition per episode", async () => {
    vi.useFakeTimers();
    const config = testBackpressure();
    const { client, socket } = connectedClient(undefined, config);
    const statuses: OutboundTransportStatus[] = [];
    client.onTransportStatus((status) => statuses.push(status));
    socket.bufferedAmount = 5_000;
    const pcm = new ArrayBuffer(640);

    expect(client.sendBinary(BINARY_KIND_PCM16, pcm)).toBe(false);
    expect(client.sendBinary(BINARY_KIND_PCM16, pcm)).toBe(false);
    expect(client.sendBinary(BINARY_KIND_PCM16, pcm)).toBe(false);
    expect(statuses).toEqual([expect.objectContaining({
      congested: true,
      reason: "pcm-backlog",
      droppedPcmFrames: 1,
    })]);
    expect(client.send("turn.cancel", {})).toBe(true);
    expect(JSON.parse(String(socket.sent.at(-1))).type).toBe("turn.cancel");

    socket.bufferedAmount = 0;
    await vi.advanceTimersByTimeAsync(config.drainPollIntervalMs);
    expect(statuses).toHaveLength(2);
    expect(statuses[1]).toEqual(expect.objectContaining({
      congested: false,
      droppedPcmFrames: 3,
    }));
    expect(client.sendBinary(BINARY_KIND_PCM16, pcm)).toBe(true);
    expect(binaryFrames(socket).at(-1)?.kind).toBe(BINARY_KIND_PCM16);
    client.disconnect();
  });

  it("drops pending media and clears congestion across reconnects", async () => {
    vi.useFakeTimers();
    const config = testBackpressure();
    const { client, socket } = connectedClient(undefined, config);
    const statuses: OutboundTransportStatus[] = [];
    client.onTransportStatus((status) => statuses.push(status));
    socket.bufferedAmount = 8_000;
    client.sendBinary(BINARY_KIND_JPEG, Uint8Array.of(7).buffer);
    client.sendBinary(BINARY_KIND_PCM16, new ArrayBuffer(640));
    socket.serverClose();

    await vi.advanceTimersByTimeAsync(500);
    const replacement = requireSocket(1);
    replacement.open();
    await vi.advanceTimersByTimeAsync(config.videoPendingMaxAgeMs + 100);
    expect(binaryFrames(replacement)).toHaveLength(0);

    replacement.bufferedAmount = 8_000;
    client.sendBinary(BINARY_KIND_PCM16, new ArrayBuffer(640));
    expect(statuses.filter((status) => status.congested)).toHaveLength(2);
    client.disconnect();
  });
});

describe("realtimeUrl", () => {
  it("selects secure WebSocket without client-controlled identity parameters", () => {
    expect(realtimeUrl({ protocol: "https:", host: "anima.veyralux.org" }))
      .toBe("wss://anima.veyralux.org/v2/realtime");
  });

  it("uses plain WebSocket for a local HTTP origin", () => {
    expect(realtimeUrl({ protocol: "http:", host: "localhost:5174" }))
      .toBe("ws://localhost:5174/v2/realtime");
  });

  it("carries only the selected Anima identity", () => {
    const url = realtimeUrl(
      { protocol: "https:", host: "anima.veyralux.org" },
      "strawberry_rabbit",
    );
    expect(url).toBe(
      "wss://anima.veyralux.org/v2/realtime?anima=strawberry_rabbit",
    );
    expect(url).not.toMatch(/user|token|session=/);
  });
});

function connectedClient(
  queue = new AudioSegmentQueue(() => playable(Promise.resolve())),
  backpressure: RealtimeBackpressureConfig = DEFAULT_REALTIME_BACKPRESSURE,
  pcmStream?: PcmStreamPlayback,
): { client: RealtimeClient; socket: FakeWebSocket } {
  vi.stubGlobal("WebSocket", FakeWebSocket);
  const client = new RealtimeClient(
    "ws://test/v2/realtime",
    queue,
    backpressure,
    undefined,
    pcmStream,
  );
  client.connect();
  const socket = FakeWebSocket.instances[0];
  if (!socket) throw new Error("测试 WebSocket 未创建");
  socket.open();
  return { client, socket };
}

function binaryFrames(socket: FakeWebSocket) {
  return socket.sent
    .filter((value): value is ArrayBuffer => value instanceof ArrayBuffer)
    .map((value) => parseBinaryFrame(value));
}

function controlEvents(socket: FakeWebSocket): Array<Record<string, unknown>> {
  return socket.sent
    .filter((value): value is string => typeof value === "string")
    .map((value) => JSON.parse(value) as Record<string, unknown>);
}

function testBackpressure(): RealtimeBackpressureConfig {
  return {
    ...DEFAULT_REALTIME_BACKPRESSURE,
    drainPollIntervalMs: 10,
  };
}

function requireSocket(index: number): FakeWebSocket {
  const socket = FakeWebSocket.instances[index];
  if (!socket) throw new Error(`测试 WebSocket ${index} 未创建`);
  return socket;
}

function serverEvent(
  type: string,
  generation: number,
  payload: Record<string, unknown>,
  turnId = `t${generation}`,
): string {
  return JSON.stringify({
    v: 2,
    type,
    sessionId: "s1",
    turnId,
    generation,
    seq: generation,
    sentAtMs: Date.now(),
    payload,
  });
}

const PCM_FORMAT = {
  contentType: "audio/pcm",
  encoding: "pcm_s16le",
  sampleRateHz: 24_000,
  channels: 1,
  sampleWidthBytes: 2,
} as const satisfies PcmStreamFormat;

function negotiateStream(socket: FakeWebSocket): void {
  socket.message(serverEvent("session.hello.ack", 0, {
    capabilities: ["reply-audio-stream-v1"],
  }));
}

function streamStarted(index: number, audioSeq: number): Record<string, unknown> {
  return {
    index,
    chunkIndex: 0,
    audioSeq,
    byteLength: 4,
    text: `第 ${index} 段`,
    ...PCM_FORMAT,
  };
}

function streamChunk(index: number, chunkIndex: number, audioSeq: number): Record<string, unknown> {
  return { index, chunkIndex, audioSeq, byteLength: 4 };
}

function sendStreamPair(
  socket: FakeWebSocket,
  audioSeq: number,
  flags: number,
  payload: Record<string, unknown>,
): void {
  socket.message(createBinaryFrame(
    BINARY_KIND_AUDIO,
    BigInt(audioSeq),
    1n,
    new ArrayBuffer(4),
    flags,
  ));
  socket.message(serverEvent(
    flags & BINARY_FLAG_START ? "reply.segment.started" : "reply.segment.chunk",
    1,
    payload,
  ));
}

function playable(
  started: Promise<void>,
  ended: Promise<void> = Promise.resolve(),
  stop: () => void = () => undefined,
): PlayableAudio {
  return {
    play: () => started,
    stop,
    waitForEnd: () => ended,
    dispose: () => undefined,
  };
}

async function flushTasks(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

function avatarIntentPayload(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    phase: "speaking",
    expression: "warm",
    motion: "talk",
    gazeStrength: 0.8,
    bodyTension: 0.5,
    smile: 0.7,
    eyeOpen: 0.85,
    speechRate: 1.1,
    speechPitch: 1.05,
    affect: { valence: 0.5, arousal: 0.6, dominance: 0.1, affinity: 0.8, trust: 0.8 },
    ...overrides,
  };
}
