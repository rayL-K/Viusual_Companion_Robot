import { describe, expect, it } from "vitest";

import {
  BINARY_HEADER_BYTES,
  createBinaryFrame,
  createBinaryHeader,
  parseAvatarIntentPayload,
  parseBinaryFrame,
  parseServerEvent,
} from "./protocol";

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

  it("parses a bounded avatar intent with an optional segment index", () => {
    const intent = parseAvatarIntentPayload(avatarIntentPayload({ segmentIndex: 2 }));
    expect(intent.phase).toBe("speaking");
    expect(intent.segmentIndex).toBe(2);
    expect(intent.affect.trust).toBe(0.8);
  });

  it("rejects malformed continuous avatar signals", () => {
    expect(() => parseAvatarIntentPayload(avatarIntentPayload({ eyeOpen: 1.2 }))).toThrow("eyeOpen");
    expect(() => parseAvatarIntentPayload(avatarIntentPayload({ segmentIndex: -1 }))).toThrow("segmentIndex");
  });
});

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
