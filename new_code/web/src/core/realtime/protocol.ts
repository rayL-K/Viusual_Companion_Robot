export const PROTOCOL_VERSION = 2;
export const BINARY_MAGIC = "VSR2";
export const BINARY_HEADER_BYTES = 24;

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

export function parseServerEvent(raw: string): ServerEvent {
  const value: unknown = JSON.parse(raw);
  if (!value || typeof value !== "object") throw new Error("实时事件必须是对象");
  const event = value as Partial<ServerEvent>;
  if (event.v !== PROTOCOL_VERSION || typeof event.type !== "string") {
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
