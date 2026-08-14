import { connectionPhase, speechAudioRms } from "../state/session";
import { AudioSegmentQueue } from "../audio/AudioSegmentQueue";
import {
  PcmStreamPlayer,
  type PcmStreamFormat,
  type PcmStreamPlayback,
} from "../audio/PcmStreamPlayer";
import {
  BINARY_FLAG_START,
  BINARY_FLAG_STREAM,
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

type PendingAudioFrame = {
  flags: number;
  payload: ArrayBuffer;
};

type ActivePcmReply = {
  generation: number;
  turnId: string;
  format: PcmStreamFormat;
  nextSegmentIndex: number;
};

type ActivePcmSegment = {
  index: number;
  nextChunkIndex: number;
  chunks: number;
  audioBytes: number;
};

type StreamReplyIdentity = {
  generation: number;
  turnId: string;
};

const INITIAL_RECONNECT_DELAY_MS = 500;
const MAX_RECONNECT_DELAY_MS = 8_000;
const HEARTBEAT_INTERVAL_MS = 25_000;
const REPLY_AUDIO_STREAM_CAPABILITY = "reply-audio-stream-v1";
const BASE_CLIENT_CAPABILITIES = ["pcm16", "jpeg", "reply-segments"] as const;
const MAX_PENDING_AUDIO_FRAMES = 8;
const MAX_PENDING_AUDIO_BYTES = 1_048_576;
const PCM_BYTES_PER_SAMPLE = 2;
const PCM_SAMPLE_RATE_HZ = 24_000;
const PCM_MAX_CHUNK_BYTES = PCM_SAMPLE_RATE_HZ * PCM_BYTES_PER_SAMPLE / 5;
const MAX_STREAM_TEXT_CHARS = 8_192;

export class RealtimeClient {
  private socket: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectAttempt = 0;
  private reconnectEnabled = false;
  private handlers = new Set<EventHandler>();
  private transportStatusHandlers = new Set<TransportStatusHandler>();
  private audioBySequence = new Map<bigint, PendingAudioFrame>();
  private pendingAudioBytes = 0;
  private activeGeneration = -1;
  private activeTurnId = "";
  private awaitingGeneration = true;
  private streamAudioAdvertised = false;
  private streamAudioNegotiated = false;
  private streamAudioDisabledForConnection = false;
  private activePcmReply: ActivePcmReply | null = null;
  private activePcmSegment: ActivePcmSegment | null = null;
  private failedPcmReply: StreamReplyIdentity | null = null;
  private streamEventTail: Promise<void> = Promise.resolve();
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
    private readonly pcmStream: PcmStreamPlayback = new PcmStreamPlayer(
      (rms) => { speechAudioRms.value = rms; },
    ),
  ) {
    this.backpressure = assertBackpressureConfig(backpressure);
  }

  connect(): void {
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) return;
    this.reconnectEnabled = true;
    this.clearReconnectTimer();
    this.openSocket();
  }

  async enableReplyAudioStream(): Promise<boolean> {
    if (this.streamAudioDisabledForConnection) return false;
    if (!this.pcmStream.supported) return false;
    if (!this.pcmStream.prepare() && !await this.pcmStream.unlock()) {
      if (this.streamAudioAdvertised || this.streamAudioNegotiated) {
        this.streamAudioAdvertised = false;
        this.streamAudioNegotiated = false;
        this.send("session.hello", { capabilities: clientCapabilities(false) });
      }
      return false;
    }
    if (this.streamAudioDisabledForConnection) return false;
    if (this.streamAudioAdvertised) return true;
    this.streamAudioAdvertised = true;
    return this.send("session.hello", {
      capabilities: clientCapabilities(true),
    });
  }

  disconnect(): void {
    this.reconnectEnabled = false;
    this.clearReconnectTimer();
    this.clearHeartbeatTimer();
    this.resetReplyAudio();
    this.streamAudioAdvertised = false;
    this.streamAudioNegotiated = false;
    this.streamAudioDisabledForConnection = false;
    this.resetOutboundBackpressure();
    this.admissionRefreshNeeded = false;
    const socket = this.socket;
    this.socket = null;
    socket?.close(1000, "page lifecycle ended");
    this.pcmStream.dispose();
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
      this.streamAudioDisabledForConnection = false;
      this.streamAudioAdvertised = this.pcmStream.supported && this.pcmStream.prepare();
      this.send("session.hello", {
        capabilities: clientCapabilities(this.streamAudioAdvertised),
      });
      this.startHeartbeat(socket);
    });
    socket.addEventListener("message", (message) => void this.handleMessage(socket, message));
    socket.addEventListener("close", (event) => {
      if (this.socket !== socket) return;
      this.socket = null;
      this.clearHeartbeatTimer();
      this.resetReplyAudio();
      this.streamAudioAdvertised = false;
      this.streamAudioNegotiated = false;
      this.streamAudioDisabledForConnection = false;
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
      this.resetReplyAudio();
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
        this.storeAudioFrame(frame.sequence, {
          flags: frame.flags,
          payload: frame.payload,
        });
        return;
      }
      if (typeof message.data !== "string") return;
      const event = parseServerEvent(message.data);
      if (event.type === "session.hello.ack") {
        try {
          const capabilities = parseCapabilityList(event.payload.capabilities);
          this.streamAudioNegotiated = (
            this.streamAudioAdvertised
            && capabilities.includes(REPLY_AUDIO_STREAM_CAPABILITY)
          );
        } catch (error) {
          this.disablePcmStream(error);
        }
        if (!this.streamAudioNegotiated) this.pcmStream.stop();
        this.emit(event);
        return;
      }
      if (event.type === "session.ready") {
        this.resetGenerationDomain();
        this.emit(event);
        return;
      }
      if (
        event.type === "error"
        && event.payload.code === "reply_failed"
        && event.generation === this.activeGeneration
        && event.turnId === this.activeTurnId
      ) {
        this.abortCurrentReplyAudio(event);
      }
      if (
        event.type === "reply.segment.started"
        || event.type === "reply.segment.chunk"
        || event.type === "reply.segment.completed"
      ) {
        const run = this.streamEventTail
          .catch(() => undefined)
          .then(() => this.handlePcmStreamEvent(event));
        this.streamEventTail = run;
        await run;
        return;
      }
      if (event.type === "avatar.intent") {
        parseAvatarIntentPayload(event.payload);
        if (!this.acceptGeneration(event.generation, event.turnId)) return;
      } else if (event.type === "reply.phase") {
        if (!this.acceptGeneration(event.generation, event.turnId)) return;
      }
      if (event.type === "reply.segment.ready") {
        const audioSequence = parseAudioSequence(event.payload.audioSeq);
        if (
          this.awaitingGeneration
          || event.generation !== this.activeGeneration
          || event.turnId !== this.activeTurnId
        ) {
          this.takeAudioFrame(audioSequence);
          return;
        }
        const audio = this.takeAudioFrame(audioSequence);
        if (!audio || audio.flags !== 0) throw new Error("回复文字缺少对应 WAV 音频");
        const contentType = String(event.payload.contentType || "audio/wav");
        void this.audioQueue
          .enqueue(audio.payload, contentType, () => this.emit(event))
          .catch((error: unknown) => console.error("实时回复音频播放失败", error));
        return;
      }
      if (event.type === "reply.completed") {
        const run = this.streamEventTail
          .catch(() => undefined)
          .then(() => this.handleReplyCompleted(event));
        this.streamEventTail = run;
        await run;
        return;
      }
      this.emit(event);
    } catch (error) {
      console.error("实时消息处理失败", error);
      connectionPhase.value = "error";
    }
  }

  private async handlePcmStreamEvent(event: ServerEvent): Promise<void> {
    if (!this.streamAudioNegotiated) {
      const sequence = optionalAudioSequence(event.payload.audioSeq);
      if (sequence !== null) this.takeAudioFrame(sequence);
      return;
    }
    if (sameReply(this.failedPcmReply, event)) {
      const sequence = optionalAudioSequence(event.payload.audioSeq);
      if (sequence !== null) this.takeAudioFrame(sequence);
      return;
    }
    if (
      event.type !== "reply.segment.started"
      && (this.awaitingGeneration || event.generation !== this.activeGeneration)
    ) {
      const sequence = optionalAudioSequence(event.payload.audioSeq);
      if (sequence !== null) this.takeAudioFrame(sequence);
      return;
    }
    if (
      event.type === "reply.segment.started"
      && (
        event.generation < this.activeGeneration
        || (this.awaitingGeneration && event.generation <= this.activeGeneration)
      )
    ) {
      const sequence = optionalAudioSequence(event.payload.audioSeq);
      if (sequence !== null) this.takeAudioFrame(sequence);
      return;
    }
    try {
      assertStreamEventIdentity(event);
      if (event.type === "reply.segment.started") {
        const metadata = parsePcmStarted(event.payload);
        const frame = this.takeAudioFrame(metadata.audioSequence);
        if (!frame) throw new Error("流式回复首块缺少对应音频");
        if (frame.flags !== (BINARY_FLAG_STREAM | BINARY_FLAG_START)) {
          throw new Error("流式回复首块 flags 无效");
        }
        if (frame.payload.byteLength !== metadata.byteLength) {
          throw new Error("流式回复首块长度不匹配");
        }
        if (!this.acceptGeneration(event.generation, event.turnId)) return;
        if (this.activePcmSegment) throw new Error("上一个流式语句尚未收尾");
        if (!this.activePcmReply) {
          if (metadata.index !== 0) throw new Error("流式回复必须从第 0 个语句开始");
          const reply: ActivePcmReply = {
            generation: event.generation,
            turnId: event.turnId,
            format: metadata.format,
            nextSegmentIndex: 0,
          };
          this.activePcmReply = reply;
          await this.pcmStream.begin(metadata.format);
          if (this.activePcmReply !== reply) return;
        } else {
          assertPcmReply(this.activePcmReply, event, metadata.format);
        }
        if (metadata.index !== this.activePcmReply.nextSegmentIndex) {
          throw new Error("流式回复 segment index 不连续");
        }
        this.activePcmSegment = {
          index: metadata.index,
          nextChunkIndex: 1,
          chunks: 1,
          audioBytes: metadata.byteLength,
        };
        if (!this.pcmStream.enqueue(frame.payload, () => {
          if (
            !this.awaitingGeneration
            && event.generation === this.activeGeneration
            && this.activePcmReply?.turnId === event.turnId
          ) this.emit(event);
        })) {
          throw new Error("流式回复首块无法进入有界播放队列");
        }
        return;
      }

      if (event.type === "reply.segment.chunk") {
        const metadata = parsePcmChunk(event.payload);
        const frame = this.takeAudioFrame(metadata.audioSequence);
        if (!frame) throw new Error("流式回复分块缺少对应音频");
        if (frame.flags !== BINARY_FLAG_STREAM) throw new Error("流式回复分块 flags 无效");
        if (frame.payload.byteLength !== metadata.byteLength) {
          throw new Error("流式回复分块长度不匹配");
        }
        const segment = this.requirePcmSegment(event, metadata.index);
        if (metadata.chunkIndex !== segment.nextChunkIndex) {
          throw new Error("流式回复 chunkIndex 不连续");
        }
        if (!this.pcmStream.enqueue(frame.payload)) {
          throw new Error("流式回复分块超过有界播放队列");
        }
        segment.nextChunkIndex += 1;
        segment.chunks += 1;
        segment.audioBytes += metadata.byteLength;
        this.emit(event);
        return;
      }

      const metadata = parsePcmCompleted(event.payload);
      const segment = this.requirePcmSegment(event, metadata.index);
      if (metadata.chunks !== segment.chunks || metadata.audioBytes !== segment.audioBytes) {
        throw new Error("流式回复收尾统计不一致");
      }
      this.activePcmSegment = null;
      const reply = this.activePcmReply;
      if (!reply) throw new Error("流式回复语句缺少所属回复");
      reply.nextSegmentIndex += 1;
      this.pcmStream.flush();
      this.emit(event);
    } catch (error) {
      if (
        this.awaitingGeneration
        || sameReply(this.failedPcmReply, event)
        || event.generation !== this.activeGeneration
        || event.turnId !== this.activeTurnId
      ) return;
      this.failPcmSegment(event, error);
    }
  }

  private async handleReplyCompleted(event: ServerEvent): Promise<void> {
    if (
      this.awaitingGeneration
      || event.generation !== this.activeGeneration
      || event.turnId !== this.activeTurnId
    ) return;
    if (sameReply(this.failedPcmReply, event)) {
      this.failedPcmReply = null;
      return;
    }
    const reply = this.activePcmReply;
    if (reply) {
      if (reply.generation !== event.generation || reply.turnId !== event.turnId) return;
      if (this.activePcmSegment) {
        this.failPcmSegment(event, new Error("流式回复在语句完成前结束"));
        return;
      }
      await this.pcmStream.complete();
      if (
        this.awaitingGeneration
        || event.generation !== this.activeGeneration
        || this.activePcmReply !== reply
      ) return;
      this.activePcmReply = null;
    } else {
      await this.audioQueue.whenIdle();
      if (this.awaitingGeneration || event.generation !== this.activeGeneration) return;
    }
    this.emit(event);
  }

  private requirePcmSegment(event: ServerEvent, index: number): ActivePcmSegment {
    const reply = this.activePcmReply;
    const segment = this.activePcmSegment;
    if (
      !reply
      || !segment
      || reply.generation !== event.generation
      || reply.turnId !== event.turnId
      || segment.index !== index
    ) {
      throw new Error("流式回复分块不属于当前语句");
    }
    return segment;
  }

  private failPcmSegment(event: ServerEvent, error: unknown): void {
    this.failedPcmReply = { generation: event.generation, turnId: event.turnId };
    this.activePcmReply = null;
    this.activePcmSegment = null;
    this.clearPendingAudio();
    this.disablePcmStream(error);
  }

  private abortCurrentReplyAudio(event: ServerEvent): void {
    this.audioQueue.stop();
    this.pcmStream.stop();
    this.activePcmReply = null;
    this.activePcmSegment = null;
    this.failedPcmReply = { generation: event.generation, turnId: event.turnId };
    this.clearPendingAudio();
  }

  private disablePcmStream(error: unknown): void {
    console.error("流式回复音频已安全终止，后续回复回退到 WAV", error);
    this.pcmStream.stop();
    this.streamAudioAdvertised = false;
    this.streamAudioNegotiated = false;
    this.streamAudioDisabledForConnection = true;
    this.send("session.hello", { capabilities: clientCapabilities(false) });
  }

  private resetGenerationDomain(): void {
    this.resetReplyAudio();
    this.activeGeneration = -1;
    this.activeTurnId = "";
    this.awaitingGeneration = true;
  }

  private acceptGeneration(generation: number, turnId: string): boolean {
    if (generation < this.activeGeneration) return false;
    if (this.awaitingGeneration && generation <= this.activeGeneration) return false;
    if (generation > this.activeGeneration) {
      this.resetReplyAudio();
      this.activeGeneration = generation;
      this.activeTurnId = turnId;
    } else if (this.activeTurnId && turnId !== this.activeTurnId) {
      return false;
    } else if (!this.activeTurnId) {
      this.activeTurnId = turnId;
    }
    this.awaitingGeneration = false;
    return true;
  }

  private resetReplyAudio(): void {
    this.audioQueue.stop();
    this.pcmStream.stop();
    this.activePcmReply = null;
    this.activePcmSegment = null;
    this.failedPcmReply = null;
    this.clearPendingAudio();
  }

  private storeAudioFrame(sequence: bigint, frame: PendingAudioFrame): void {
    const previous = this.audioBySequence.get(sequence);
    if (previous) this.pendingAudioBytes -= previous.payload.byteLength;
    this.audioBySequence.set(sequence, frame);
    this.pendingAudioBytes += frame.payload.byteLength;
    while (
      this.audioBySequence.size > MAX_PENDING_AUDIO_FRAMES
      || this.pendingAudioBytes > MAX_PENDING_AUDIO_BYTES
    ) {
      const oldest = this.audioBySequence.keys().next().value;
      if (oldest === undefined) break;
      const removed = this.audioBySequence.get(oldest);
      this.audioBySequence.delete(oldest);
      if (removed) this.pendingAudioBytes -= removed.payload.byteLength;
    }
  }

  private takeAudioFrame(sequence: bigint): PendingAudioFrame | undefined {
    const frame = this.audioBySequence.get(sequence);
    if (!frame) return undefined;
    this.audioBySequence.delete(sequence);
    this.pendingAudioBytes -= frame.payload.byteLength;
    return frame;
  }

  private clearPendingAudio(): void {
    this.audioBySequence.clear();
    this.pendingAudioBytes = 0;
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

function optionalAudioSequence(value: unknown): bigint | null {
  return value === undefined ? null : parseAudioSequence(value);
}

function parseCapabilityList(value: unknown): string[] {
  if (!Array.isArray(value) || value.length > 32) {
    throw new Error("服务端能力列表无效");
  }
  const capabilities: string[] = [];
  const seen = new Set<string>();
  for (const capability of value) {
    if (typeof capability !== "string" || !capability || capability.length > 64) {
      throw new Error("服务端能力名称无效");
    }
    if (seen.has(capability)) throw new Error("服务端能力列表包含重复项");
    seen.add(capability);
    capabilities.push(capability);
  }
  return capabilities;
}

type PcmStartedMetadata = {
  index: number;
  audioSequence: bigint;
  byteLength: number;
  format: PcmStreamFormat;
};

type PcmChunkMetadata = {
  index: number;
  chunkIndex: number;
  audioSequence: bigint;
  byteLength: number;
};

type PcmCompletedMetadata = {
  index: number;
  chunks: number;
  audioBytes: number;
};

function parsePcmStarted(payload: Record<string, unknown>): PcmStartedMetadata {
  const index = requireNonNegativeInteger(payload.index, "segment index");
  if (requireNonNegativeInteger(payload.chunkIndex, "chunkIndex") !== 0) {
    throw new Error("流式回复首块 chunkIndex 必须为 0");
  }
  if (
    typeof payload.text !== "string"
    || !payload.text.trim()
    || payload.text.length > MAX_STREAM_TEXT_CHARS
  ) {
    throw new Error("流式回复文本无效");
  }
  if (
    payload.contentType !== "audio/pcm"
    || payload.encoding !== "pcm_s16le"
    || payload.sampleRateHz !== PCM_SAMPLE_RATE_HZ
    || payload.channels !== 1
    || payload.sampleWidthBytes !== PCM_BYTES_PER_SAMPLE
  ) {
    throw new Error("流式回复音频必须是 24kHz mono PCM S16LE");
  }
  return {
    index,
    audioSequence: parseAudioSequence(payload.audioSeq),
    byteLength: requirePcmByteLength(payload.byteLength),
    format: {
      contentType: "audio/pcm",
      encoding: "pcm_s16le",
      sampleRateHz: PCM_SAMPLE_RATE_HZ,
      channels: 1,
      sampleWidthBytes: PCM_BYTES_PER_SAMPLE,
    },
  };
}

function parsePcmChunk(payload: Record<string, unknown>): PcmChunkMetadata {
  const chunkIndex = requireNonNegativeInteger(payload.chunkIndex, "chunkIndex");
  if (chunkIndex === 0) throw new Error("流式回复后续块 chunkIndex 必须大于 0");
  return {
    index: requireNonNegativeInteger(payload.index, "segment index"),
    chunkIndex,
    audioSequence: parseAudioSequence(payload.audioSeq),
    byteLength: requirePcmByteLength(payload.byteLength),
  };
}

function parsePcmCompleted(payload: Record<string, unknown>): PcmCompletedMetadata {
  const chunks = requirePositiveInteger(payload.chunks, "chunks");
  const audioBytes = requirePositiveInteger(payload.audioBytes, "audioBytes");
  if (audioBytes % PCM_BYTES_PER_SAMPLE !== 0) {
    throw new Error("流式回复 audioBytes 未按 PCM 帧对齐");
  }
  return {
    index: requireNonNegativeInteger(payload.index, "segment index"),
    chunks,
    audioBytes,
  };
}

function requirePcmByteLength(value: unknown): number {
  const byteLength = requirePositiveInteger(value, "byteLength");
  if (byteLength % PCM_BYTES_PER_SAMPLE !== 0 || byteLength > PCM_MAX_CHUNK_BYTES) {
    throw new Error("流式回复 PCM 分块长度无效");
  }
  return byteLength;
}

function requireNonNegativeInteger(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    throw new Error(`流式回复 ${label} 无效`);
  }
  return value;
}

function requirePositiveInteger(value: unknown, label: string): number {
  const integer = requireNonNegativeInteger(value, label);
  if (integer === 0) throw new Error(`流式回复 ${label} 必须大于 0`);
  return integer;
}

function assertStreamEventIdentity(event: ServerEvent): void {
  if (event.generation < 0) throw new Error("流式回复 generation 无效");
  if (!event.turnId || event.turnId.length > 128) throw new Error("流式回复 turnId 无效");
}

function assertPcmReply(
  reply: ActivePcmReply,
  event: ServerEvent,
  format: PcmStreamFormat,
): void {
  if (reply.generation !== event.generation || reply.turnId !== event.turnId) {
    throw new Error("流式回复 generation 或 turnId 不一致");
  }
  if (
    reply.format.contentType !== format.contentType
    || reply.format.encoding !== format.encoding
    || reply.format.sampleRateHz !== format.sampleRateHz
    || reply.format.channels !== format.channels
    || reply.format.sampleWidthBytes !== format.sampleWidthBytes
  ) {
    throw new Error("流式回复中途改变了音频格式");
  }
}

function sameReply(identity: StreamReplyIdentity | null, event: ServerEvent): boolean {
  return Boolean(
    identity
    && identity.generation === event.generation
    && identity.turnId === event.turnId,
  );
}

function clientCapabilities(streamingAudio: boolean): string[] {
  const capabilities: string[] = [...BASE_CLIENT_CAPABILITIES];
  if (streamingAudio) capabilities.push(REPLY_AUDIO_STREAM_CAPABILITY);
  return capabilities;
}

export function realtimeUrl(
  locationLike: Pick<Location, "protocol" | "host"> = window.location,
  animaId?: string,
): string {
  const protocol = locationLike.protocol === "https:" ? "wss:" : "ws:";
  const base = `${protocol}//${locationLike.host}/v2/realtime`;
  if (!animaId) return base;
  if (!/^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$/.test(animaId)) {
    throw new Error("Anima ID 无效");
  }
  return `${base}?anima=${encodeURIComponent(animaId)}`;
}
