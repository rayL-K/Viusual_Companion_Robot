export const PROTOCOL_VERSION = 2;
export const BINARY_MAGIC = "VSR2";
export const BINARY_HEADER_BYTES = 24;
export const BINARY_KIND_PCM16 = 1;
export const BINARY_KIND_JPEG = 2;
export const BINARY_KIND_AUDIO = 3;

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
