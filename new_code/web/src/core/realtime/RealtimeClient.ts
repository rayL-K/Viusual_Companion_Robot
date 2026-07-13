import { connectionPhase, speechAudioRms } from "../state/session";
import { AudioSegmentQueue } from "../audio/AudioSegmentQueue";
import {
  BINARY_KIND_AUDIO,
  createBinaryFrame,
  parseAvatarIntentPayload,
  parseBinaryFrame,
  parseServerEvent,
  PROTOCOL_VERSION,
  type ServerEvent,
} from "./protocol";
import { getOrCreateAnonymousSessionId } from "./sessionIdentity";

type EventHandler = (event: ServerEvent) => void;

const INITIAL_RECONNECT_DELAY_MS = 500;
const MAX_RECONNECT_DELAY_MS = 8_000;

export class RealtimeClient {
  private socket: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempt = 0;
  private reconnectEnabled = false;
  private handlers = new Set<EventHandler>();
  private audioBySequence = new Map<bigint, ArrayBuffer>();
  private activeGeneration = -1;
  private awaitingGeneration = true;
  private outboundBinarySequence = 0n;

  constructor(
    private readonly url: string,
    private readonly audioQueue = new AudioSegmentQueue(undefined, (rms) => { speechAudioRms.value = rms; }),
  ) {}

  connect(): void {
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) return;
    this.reconnectEnabled = true;
    this.clearReconnectTimer();
    this.openSocket();
  }

  disconnect(): void {
    this.reconnectEnabled = false;
    this.clearReconnectTimer();
    this.audioQueue.stop();
    this.audioBySequence.clear();
    const socket = this.socket;
    this.socket = null;
    socket?.close(1000, "page lifecycle ended");
    connectionPhase.value = "offline";
  }

  private openSocket(): void {
    if (!this.reconnectEnabled || (this.socket && this.socket.readyState <= WebSocket.OPEN)) return;
    connectionPhase.value = "connecting";
    let socket: WebSocket;
    try {
      socket = new WebSocket(this.url);
    } catch (error) {
      console.error("实时连接创建失败", error);
      connectionPhase.value = "error";
      this.scheduleReconnect();
      return;
    }
    socket.binaryType = "arraybuffer";
    this.socket = socket;
    socket.addEventListener("open", () => {
      if (this.socket !== socket || !this.reconnectEnabled) {
        socket.close(1000, "superseded connection");
        return;
      }
      this.reconnectAttempt = 0;
      this.clearReconnectTimer();
      connectionPhase.value = "online";
      this.send("session.hello", { capabilities: ["pcm16", "jpeg", "reply-segments"] });
    });
    socket.addEventListener("message", (message) => void this.handleMessage(socket, message));
    socket.addEventListener("close", () => {
      if (this.socket !== socket) return;
      this.socket = null;
      this.audioQueue.stop();
      this.audioBySequence.clear();
      connectionPhase.value = "offline";
      this.scheduleReconnect();
    });
    socket.addEventListener("error", () => {
      if (this.socket !== socket) return;
      connectionPhase.value = "error";
    });
  }

  private scheduleReconnect(): void {
    if (!this.reconnectEnabled || this.reconnectTimer !== null || this.socket) return;
    const exponent = Math.min(this.reconnectAttempt, 30);
    const delayMs = Math.min(INITIAL_RECONNECT_DELAY_MS * 2 ** exponent, MAX_RECONNECT_DELAY_MS);
    this.reconnectAttempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.openSocket();
    }, delayMs);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer === null) return;
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
  }

  onEvent(handler: EventHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  send(type: string, payload: Record<string, unknown>): boolean {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return false;
    if (type === "turn.user_text" || type === "turn.cancel") {
      this.audioQueue.stop();
      this.audioBySequence.clear();
      this.awaitingGeneration = true;
    }
    this.socket.send(JSON.stringify({ v: PROTOCOL_VERSION, type, sentAtMs: Date.now(), payload }));
    return true;
  }

  sendBinary(kind: number, payload: ArrayBuffer, flags = 0): boolean {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return false;
    this.outboundBinarySequence += 1n;
    this.socket.send(
      createBinaryFrame(kind, this.outboundBinarySequence, BigInt(Date.now()), payload, flags),
    );
    return true;
  }

  private async handleMessage(socket: WebSocket, message: MessageEvent): Promise<void> {
    if (this.socket !== socket) return;
    try {
      if (message.data instanceof ArrayBuffer) {
        const frame = parseBinaryFrame(message.data);
        if (frame.kind !== BINARY_KIND_AUDIO) return;
        this.audioBySequence.set(frame.sequence, frame.payload);
        if (this.audioBySequence.size > 16) {
          const oldest = this.audioBySequence.keys().next().value;
          if (oldest !== undefined) this.audioBySequence.delete(oldest);
        }
        return;
      }
      if (typeof message.data !== "string") return;
      const event = parseServerEvent(message.data);
      if (event.type === "session.ready") {
        this.resetGenerationDomain();
        this.emit(event);
        return;
      }
      if (event.type === "avatar.intent") {
        parseAvatarIntentPayload(event.payload);
        if (!this.acceptGeneration(event.generation)) return;
      } else if (event.type === "reply.phase") {
        if (!this.acceptGeneration(event.generation)) return;
      }
      if (event.type === "reply.segment.ready") {
        const audioSequence = parseAudioSequence(event.payload.audioSeq);
        if (this.awaitingGeneration || event.generation !== this.activeGeneration) {
          this.audioBySequence.delete(audioSequence);
          return;
        }
        const audio = this.audioBySequence.get(audioSequence);
        if (!audio) throw new Error("回复文字缺少对应音频");
        this.audioBySequence.delete(audioSequence);
        const contentType = String(event.payload.contentType || "audio/wav");
        void this.audioQueue
          .enqueue(audio, contentType, () => this.emit(event))
          .catch((error: unknown) => console.error("实时回复音频播放失败", error));
        return;
      }
      if (event.type === "reply.completed") {
        if (this.awaitingGeneration || event.generation !== this.activeGeneration) return;
        await this.audioQueue.whenIdle();
        if (this.awaitingGeneration || event.generation !== this.activeGeneration) return;
      }
      this.emit(event);
    } catch (error) {
      console.error("实时消息处理失败", error);
      connectionPhase.value = "error";
    }
  }

  private resetGenerationDomain(): void {
    this.audioQueue.stop();
    this.audioBySequence.clear();
    this.activeGeneration = -1;
    this.awaitingGeneration = true;
  }

  private acceptGeneration(generation: number): boolean {
    if (generation < this.activeGeneration) return false;
    if (this.awaitingGeneration && generation <= this.activeGeneration) return false;
    if (generation > this.activeGeneration) {
      this.audioQueue.stop();
      this.audioBySequence.clear();
      this.activeGeneration = generation;
    }
    this.awaitingGeneration = false;
    return true;
  }

  private emit(event: ServerEvent): void {
    for (const handler of this.handlers) handler(event);
  }
}

function parseAudioSequence(value: unknown): bigint {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    throw new Error("回复音频序号无效");
  }
  return BigInt(value);
}

export function realtimeUrl(
  locationLike: Pick<Location, "protocol" | "host"> = window.location,
  sessionId = getOrCreateAnonymousSessionId(),
): string {
  const protocol = locationLike.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${locationLike.host}/v2/realtime?session=${encodeURIComponent(sessionId)}`;
}
