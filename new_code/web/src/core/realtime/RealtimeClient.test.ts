import { afterEach, describe, expect, it, vi } from "vitest";

import { AudioSegmentQueue, type PlayableAudio } from "../audio/AudioSegmentQueue";
import { connectionPhase } from "../state/session";
import { BINARY_KIND_AUDIO, createBinaryFrame, type ServerEvent } from "./protocol";
import { RealtimeClient, realtimeUrl } from "./RealtimeClient";

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readyState = FakeWebSocket.CONNECTING;
  binaryType = "blob";
  sent: unknown[] = [];
  private listeners = new Map<string, Array<(event: { data?: unknown }) => void>>();

  constructor(readonly url: string) {
    FakeWebSocket.instances.push(this);
  }

  addEventListener(type: string, handler: (event: { data?: unknown }) => void): void {
    const handlers = this.listeners.get(type) ?? [];
    handlers.push(handler);
    this.listeners.set(type, handlers);
  }

  send(data: unknown): void {
    this.sent.push(data);
  }

  close(_code?: number, _reason?: string): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.dispatch("close");
  }

  serverClose(): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.dispatch("close");
  }

  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.dispatch("open");
  }

  message(data: unknown): void {
    this.dispatch("message", data);
  }

  private dispatch(type: string, data?: unknown): void {
    for (const handler of this.listeners.get(type) ?? []) handler({ data });
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
});

describe("realtimeUrl", () => {
  it("selects secure WebSocket and includes the persistent session id", () => {
    expect(realtimeUrl(
      { protocol: "https:", host: "anima.veyralux.org" },
      "anon_12345678123412341234123456789abc",
    )).toBe(
      "wss://anima.veyralux.org/v2/realtime?session=anon_12345678123412341234123456789abc",
    );
  });

  it("encodes the session query value at the URL boundary", () => {
    expect(realtimeUrl({ protocol: "http:", host: "localhost:5174" }, "id:one/two"))
      .toBe("ws://localhost:5174/v2/realtime?session=id%3Aone%2Ftwo");
  });
});

function connectedClient(queue: AudioSegmentQueue): { client: RealtimeClient; socket: FakeWebSocket } {
  vi.stubGlobal("WebSocket", FakeWebSocket);
  const client = new RealtimeClient("ws://test/v2/realtime", queue);
  client.connect();
  const socket = FakeWebSocket.instances[0];
  if (!socket) throw new Error("测试 WebSocket 未创建");
  socket.open();
  return { client, socket };
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
