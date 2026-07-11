export const PROTOCOL_VERSION = 2;
export const BINARY_MAGIC = "VSR2";
export const BINARY_HEADER_BYTES = 24;
export const BINARY_KIND_PCM16 = 1;
export const BINARY_KIND_JPEG = 2;
export const BINARY_KIND_AUDIO = 3;

export type AvatarPhase = "idle" | "listening" | "thinking" | "speaking";

export type AvatarAffect = {
  valence: number;
  arousal: number;
  dominance: number;
  affinity: number;
  trust: number;
};

export type AvatarIntentPayload = {
  phase: AvatarPhase;
  expression: string;
  motion: string;
  gazeStrength: number;
  bodyTension: number;
  smile: number;
  eyeOpen: number;
  speechRate: number;
  speechPitch: number;
  affect: AvatarAffect;
  segmentIndex?: number;
};

export type ServerEvent = {
  v: 2;
  type: string;
  sessionId: string;
  turnId: string;
  generation: number;
  seq: number;
  sentAtMs: number;
  payload: Record<string, unknown>;
};

export type BinaryFrame = {
  kind: number;
  flags: number;
  sequence: bigint;
  timestampMs: bigint;
  payload: ArrayBuffer;
};

export function parseServerEvent(raw: string): ServerEvent {
  const value: unknown = JSON.parse(raw);
  if (!value || typeof value !== "object") throw new Error("实时事件必须是对象");
  const event = value as Partial<ServerEvent>;
  if (
    event.v !== PROTOCOL_VERSION
    || typeof event.type !== "string"
    || typeof event.sessionId !== "string"
    || typeof event.turnId !== "string"
    || !Number.isSafeInteger(event.generation)
    || !Number.isSafeInteger(event.seq)
    || typeof event.sentAtMs !== "number"
    || !event.payload
    || typeof event.payload !== "object"
    || Array.isArray(event.payload)
  ) {
    throw new Error("实时事件协议版本或类型无效");
  }
  return event as ServerEvent;
}

export function parseAvatarIntentPayload(payload: Record<string, unknown>): AvatarIntentPayload {
  const affect = requireRecord(payload.affect, "avatar.intent affect");
  const phase = payload.phase;
  if (phase !== "idle" && phase !== "listening" && phase !== "thinking" && phase !== "speaking") {
    throw new Error("avatar.intent phase 无效");
  }

  const intent: AvatarIntentPayload = {
    phase,
    expression: requireName(payload.expression, "expression"),
    motion: requireName(payload.motion, "motion"),
    gazeStrength: requireRange(payload.gazeStrength, "gazeStrength", 0, 1),
    bodyTension: requireRange(payload.bodyTension, "bodyTension", 0, 1),
    smile: requireRange(payload.smile, "smile", 0, 1),
    eyeOpen: requireRange(payload.eyeOpen, "eyeOpen", 0, 1),
    speechRate: requireRange(payload.speechRate, "speechRate", 0.5, 2),
    speechPitch: requireRange(payload.speechPitch, "speechPitch", 0.5, 2),
    affect: {
      valence: requireRange(affect.valence, "affect.valence", -1, 1),
      arousal: requireRange(affect.arousal, "affect.arousal", 0, 1),
      dominance: requireRange(affect.dominance, "affect.dominance", -1, 1),
      affinity: requireRange(affect.affinity, "affect.affinity", -1, 1),
      trust: requireRange(affect.trust, "affect.trust", -1, 1),
    },
  };
  if (payload.segmentIndex !== undefined) {
    if (!Number.isSafeInteger(payload.segmentIndex) || Number(payload.segmentIndex) < 0) {
      throw new Error("avatar.intent segmentIndex 无效");
    }
    intent.segmentIndex = Number(payload.segmentIndex);
  }
  return intent;
}

export function createBinaryHeader(kind: number, sequence: bigint, timestampMs: bigint): ArrayBuffer {
  if (kind < 1 || kind > 255) throw new RangeError("binary kind must be 1..255");
  const buffer = new ArrayBuffer(BINARY_HEADER_BYTES);
  const bytes = new Uint8Array(buffer);
  bytes.set(new TextEncoder().encode(BINARY_MAGIC), 0);
  const view = new DataView(buffer);
  view.setUint8(4, kind);
  view.setUint8(5, 0);
  view.setUint16(6, BINARY_HEADER_BYTES, false);
  view.setBigUint64(8, sequence, false);
  view.setBigUint64(16, timestampMs, false);
  return buffer;
}

export function createBinaryFrame(
  kind: number,
  sequence: bigint,
  timestampMs: bigint,
  payload: ArrayBuffer,
  flags = 0,
): ArrayBuffer {
  if (!Number.isInteger(flags) || flags < 0 || flags > 255) {
    throw new RangeError("binary flags must be 0..255");
  }
  const header = new Uint8Array(createBinaryHeader(kind, sequence, timestampMs));
  header[5] = flags;
  const frame = new Uint8Array(BINARY_HEADER_BYTES + payload.byteLength);
  frame.set(header, 0);
  frame.set(new Uint8Array(payload), BINARY_HEADER_BYTES);
  return frame.buffer;
}

export function parseBinaryFrame(buffer: ArrayBuffer): BinaryFrame {
  if (buffer.byteLength < BINARY_HEADER_BYTES) throw new Error("二进制帧长度不足");
  const bytes = new Uint8Array(buffer, 0, 4);
  if (new TextDecoder().decode(bytes) !== BINARY_MAGIC) throw new Error("二进制帧 magic 无效");
  const view = new DataView(buffer);
  const headerBytes = view.getUint16(6, false);
  if (headerBytes !== BINARY_HEADER_BYTES) throw new Error("二进制帧头长度无效");
  return {
    kind: view.getUint8(4),
    flags: view.getUint8(5),
    sequence: view.getBigUint64(8, false),
    timestampMs: view.getBigUint64(16, false),
    payload: buffer.slice(headerBytes),
  };
}

function requireRecord(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} 必须是对象`);
  }
  return value as Record<string, unknown>;
}

function requireName(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim() || value.length > 64) {
    throw new Error(`avatar.intent ${label} 无效`);
  }
  return value;
}

function requireRange(value: unknown, label: string, minimum: number, maximum: number): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < minimum || value > maximum) {
    throw new Error(`avatar.intent ${label} 超出范围`);
  }
  return value;
}
