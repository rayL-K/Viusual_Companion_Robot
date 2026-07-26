import { connectionPhase, speechAudioRms } from "../state/session";
import { AudioSegmentQueue } from "../audio/AudioSegmentQueue";
import {
  BINARY_KIND_AUDIO,
  BINARY_KIND_JPEG,
  BINARY_KIND_PCM16,
  createBinaryFrame,
  parseAvatarIntentPayload,
  parseBinaryFrame,
  parseServerEvent,
  PROTOCOL_VERSION,
  type ServerEvent,
} from "./protocol";
import {
  assertBackpressureConfig,
  DEFAULT_REALTIME_BACKPRESSURE,
  framedBinaryBytes,
  pcmBacklogBytes,
  type RealtimeBackpressureConfig,
} from "./backpressure";

type EventHandler = (event: ServerEvent) => void;
type TransportStatusHandler = (status: OutboundTransportStatus) => void;

export type OutboundTransportStatus = Readonly<{
  congested: boolean;
  reason: "pcm-backlog";
  bufferedBytes: number;
  droppedPcmFrames: number;
  droppedVideoFrames: number;
}>;

type PendingVideoFrame = {
  payload: ArrayBuffer;
  flags: number;
  acceptedAtMs: number;
};

const INITIAL_RECONNECT_DELAY_MS = 500;
const MAX_RECONNECT_DELAY_MS = 8_000;
const HEARTBEAT_INTERVAL_MS = 25_000;

export class RealtimeClient {
  private socket: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectAttempt = 0;
  private reconnectEnabled = false;
  private handlers = new Set<EventHandler>();
  private transportStatusHandlers = new Set<TransportStatusHandler>();
  private audioBySequence = new Map<bigint, ArrayBuffer>();
  private activeGeneration = -1;
  private awaitingGeneration = true;
  private outboundBinarySequence = 0n;
  private drainTimer: ReturnType<typeof setTimeout> | null = null;
  private pendingVideo: PendingVideoFrame | null = null;
  private outboundCongested = false;
  private droppedPcmFrames = 0;
  private droppedVideoFrames = 0;
  private admissionRefreshNeeded = false;
  private readonly backpressure: RealtimeBackpressureConfig;

  constructor(
    private readonly url: string,
    private readonly audioQueue = new AudioSegmentQueue(undefined, (rms) => { speechAudioRms.value = rms; }),
    backpressure: RealtimeBackpressureConfig = DEFAULT_REALTIME_BACKPRESSURE,
    private readonly refreshAdmission?: () => Promise<void>,
  ) {
    this.backpressure = assertBackpressureConfig(backpressure);
  }

  connect(): void {
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) return;
    this.reconnectEnabled = true;
    this.clearReconnectTimer();
    this.openSocket();
  }

  disconnect(): void {
    this.reconnectEnabled = false;
    this.clearReconnectTimer();
    this.clearHeartbeatTimer();
    this.audioQueue.stop();
    this.audioBySequence.clear();
    this.resetOutboundBackpressure();
    this.admissionRefreshNeeded = false;
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
      this.resetOutboundBackpressure();
      connectionPhase.value = "online";
      this.send("session.hello", { capabilities: ["pcm16", "jpeg", "reply-segments"] });
      this.startHeartbeat(socket);
    });
    socket.addEventListener("message", (message) => void this.handleMessage(socket, message));
    socket.addEventListener("close", (event) => {
      if (this.socket !== socket) return;
      this.socket = null;
      this.clearHeartbeatTimer();
      this.audioQueue.stop();
      this.audioBySequence.clear();
      this.resetOutboundBackpressure();
      connectionPhase.value = "offline";
      if (event.code === 4401 && this.refreshAdmission) {
        this.admissionRefreshNeeded = true;
      }
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
      void this.resumeConnection();
    }, delayMs);
  }

  private async resumeConnection(): Promise<void> {
    if (!this.reconnectEnabled || this.socket) return;
    if (this.admissionRefreshNeeded && this.refreshAdmission) {
      connectionPhase.value = "connecting";
      try {
        await this.refreshAdmission();
      } catch (error) {
        console.error("连接校验刷新失败", error);
        connectionPhase.value = "error";
        this.scheduleReconnect();
        return;
      }
      if (!this.reconnectEnabled || this.socket) return;
      this.admissionRefreshNeeded = false;
    }
    this.openSocket();
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer === null) return;
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
  }

  private startHeartbeat(socket: WebSocket): void {
    this.clearHeartbeatTimer();
    this.heartbeatTimer = setInterval(() => {
      if (this.socket !== socket || socket.readyState !== WebSocket.OPEN) {
        this.clearHeartbeatTimer();
        return;
      }
      this.send("session.heartbeat", {});
    }, HEARTBEAT_INTERVAL_MS);
  }

  private clearHeartbeatTimer(): void {
    if (this.heartbeatTimer === null) return;
    clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = null;
  }

  onEvent(handler: EventHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  onTransportStatus(handler: TransportStatusHandler): () => void {
    this.transportStatusHandlers.add(handler);
    return () => this.transportStatusHandlers.delete(handler);
  }

  send(type: string, payload: Record<string, unknown>): boolean {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return false;
    if (type === "turn.user_text" || type === "turn.cancel") {
      this.audioQueue.stop();
      this.audioBySequence.clear();
      this.awaitingGeneration = true;
    }
    // Control events are always enqueued synchronously. A browser WebSocket has
    // only one ordered byte stream, so already-enqueued binary data cannot be
    // overtaken; the visual policy below keeps that queue from accumulating.
    this.socket.send(JSON.stringify({ v: PROTOCOL_VERSION, type, sentAtMs: Date.now(), payload }));
    if (this.pendingVideo) this.scheduleDrainCheck();
    return true;
  }

  sendBinary(kind: number, payload: ArrayBuffer, flags = 0): boolean {
    const socket = this.socket;
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    if (kind === BINARY_KIND_JPEG) {
      return this.acceptLatestVideo(socket, payload, flags);
    }
    if (kind === BINARY_KIND_PCM16) {
      return this.sendPcm(socket, payload, flags);
    }
    this.sendFramedBinary(socket, kind, payload, flags);
    return true;
  }

  private sendPcm(socket: WebSocket, payload: ArrayBuffer, flags: number): boolean {
    this.recoverIfDrained(socket);
    if (this.outboundCongested) {
      this.droppedPcmFrames += 1;
      this.scheduleDrainCheck();
      return false;
    }
    const hardLimitBytes = pcmBacklogBytes(
      this.backpressure,
      this.backpressure.pcmBacklogHardLimitMs,
    );
    if (socket.bufferedAmount + framedBinaryBytes(payload) > hardLimitBytes) {
      this.droppedPcmFrames += 1;
      this.enterCongestion(socket);
      return false;
    }
    this.sendFramedBinary(socket, BINARY_KIND_PCM16, payload, flags);
    return true;
  }

  private acceptLatestVideo(socket: WebSocket, payload: ArrayBuffer, flags: number): boolean {
    if (this.pendingVideo) this.droppedVideoFrames += 1;
    this.pendingVideo = { payload, flags, acceptedAtMs: Date.now() };
    this.flushPendingVideo(socket);
    if (this.pendingVideo) this.scheduleDrainCheck();
    return true;
  }

  private flushPendingVideo(socket: WebSocket): void {
    const pending = this.pendingVideo;
    if (!pending || this.outboundCongested) return;
    if (Date.now() - pending.acceptedAtMs > this.backpressure.videoPendingMaxAgeMs) {
      this.pendingVideo = null;
      this.droppedVideoFrames += 1;
      return;
    }
    if (socket.bufferedAmount > this.backpressure.videoSendMaxBufferedBytes) return;
    this.pendingVideo = null;
    this.sendFramedBinary(socket, BINARY_KIND_JPEG, pending.payload, pending.flags);
  }

  private sendFramedBinary(
    socket: WebSocket,
    kind: number,
    payload: ArrayBuffer,
    flags: number,
  ): void {
    this.outboundBinarySequence += 1n;
    socket.send(
      createBinaryFrame(kind, this.outboundBinarySequence, BigInt(Date.now()), payload, flags),
    );
  }

  private enterCongestion(socket: WebSocket): void {
    if (!this.outboundCongested) {
      this.outboundCongested = true;
      this.emitTransportStatus(socket, true);
    }
    this.scheduleDrainCheck();
  }

  private recoverIfDrained(socket: WebSocket): void {
    if (!this.outboundCongested) return;
    const recoveryBytes = pcmBacklogBytes(
      this.backpressure,
      this.backpressure.pcmBacklogRecoveryMs,
    );
    if (socket.bufferedAmount > recoveryBytes) return;
    this.outboundCongested = false;
    this.emitTransportStatus(socket, false);
    this.droppedPcmFrames = 0;
    this.droppedVideoFrames = 0;
  }

  private emitTransportStatus(socket: WebSocket, congested: boolean): void {
    const status: OutboundTransportStatus = {
      congested,
      reason: "pcm-backlog",
      bufferedBytes: socket.bufferedAmount,
      droppedPcmFrames: this.droppedPcmFrames,
      droppedVideoFrames: this.droppedVideoFrames,
    };
    for (const handler of this.transportStatusHandlers) handler(status);
  }

  private scheduleDrainCheck(): void {
    if (this.drainTimer !== null) return;
    this.drainTimer = setTimeout(() => {
      this.drainTimer = null;
      const socket = this.socket;
      if (!socket || socket.readyState !== WebSocket.OPEN) return;
      this.recoverIfDrained(socket);
      this.flushPendingVideo(socket);
      if (this.outboundCongested || this.pendingVideo) this.scheduleDrainCheck();
    }, this.backpressure.drainPollIntervalMs);
  }

  private resetOutboundBackpressure(): void {
    if (this.drainTimer !== null) clearTimeout(this.drainTimer);
    this.drainTimer = null;
    this.pendingVideo = null;
    this.outboundCongested = false;
    this.droppedPcmFrames = 0;
    this.droppedVideoFrames = 0;
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
): string {
  const protocol = locationLike.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${locationLike.host}/v2/realtime`;
}
