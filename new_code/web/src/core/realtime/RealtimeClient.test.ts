import { afterEach, describe, expect, it, vi } from "vitest";

import { AudioSegmentQueue, type PlayableAudio } from "../audio/AudioSegmentQueue";
import { BINARY_KIND_AUDIO, createBinaryFrame, type ServerEvent } from "./protocol";
import { RealtimeClient } from "./RealtimeClient";

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

  close(): void {
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
