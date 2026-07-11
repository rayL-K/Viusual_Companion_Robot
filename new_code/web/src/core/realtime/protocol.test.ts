import { describe, expect, it } from "vitest";

import { BINARY_HEADER_BYTES, createBinaryFrame, createBinaryHeader, parseBinaryFrame, parseServerEvent } from "./protocol";

describe("realtime protocol", () => {
  it("builds a stable big-endian binary header", () => {
    const header = createBinaryHeader(1, 9n, 1000n);
    const view = new DataView(header);
    expect(header.byteLength).toBe(BINARY_HEADER_BYTES);
    expect(view.getUint8(4)).toBe(1);
    expect(view.getBigUint64(8, false)).toBe(9n);
  });

  it("parses payload after the fixed header", () => {
    const frame = parseBinaryFrame(
      createBinaryFrame(3, 11n, 2000n, new Uint8Array([1, 2, 3]).buffer),
    );
    expect(frame.kind).toBe(3);
    expect([...new Uint8Array(frame.payload)]).toEqual([1, 2, 3]);
  });

  it("rejects an incompatible JSON event", () => {
    expect(() => parseServerEvent('{"v":1,"type":"x"}')).toThrow();
  });
});
