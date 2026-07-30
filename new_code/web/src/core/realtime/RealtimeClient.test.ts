import { afterEach, describe, expect, it, vi } from "vitest";

import { AudioSegmentQueue, type PlayableAudio } from "../audio/AudioSegmentQueue";
import { connectionPhase } from "../state/session";
import {
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

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  FakeWebSocket.instances = [];
});

describe("RealtimeClient reply generations", () => {
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
): { client: RealtimeClient; socket: FakeWebSocket } {
  vi.stubGlobal("WebSocket", FakeWebSocket);
  const client = new RealtimeClient("ws://test/v2/realtime", queue, backpressure);
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

function serverEvent(type: string, generation: number, payload: Record<string, unknown>): string {
  return JSON.stringify({
    v: 2,
    type,
    sessionId: "s1",
    turnId: `t${generation}`,
    generation,
    seq: generation,
    sentAtMs: Date.now(),
    payload,
  });
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
