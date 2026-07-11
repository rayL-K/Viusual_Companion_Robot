import { describe, expect, it } from "vitest";

import type { AvatarIntentPayload } from "../realtime/protocol";
import { reduceAvatarIntent, type AvatarIntentState } from "./session";

const current: AvatarIntentState = {
  sessionId: "s1",
  generation: 4,
  seq: 20,
  ...intent({ phase: "thinking", expression: "attentive", motion: "listen" }),
};

describe("avatar intent state", () => {
  it("rejects an intent from an older generation", () => {
    const result = reduceAvatarIntent(current, {
      sessionId: "s1",
      generation: 3,
      seq: 99,
      payload: intent({ expression: "concerned", motion: "comfort" }),
    });
    expect(result).toBe(current);
  });

  it("rejects out-of-order intent events within the active generation", () => {
    const result = reduceAvatarIntent(current, {
      sessionId: "s1",
      generation: 4,
      seq: 19,
      payload: intent({ expression: "delighted", motion: "excited" }),
    });
    expect(result).toBe(current);
  });

  it("accepts the next ordered segment intent", () => {
    const result = reduceAvatarIntent(current, {
      sessionId: "s1",
      generation: 4,
      seq: 21,
      payload: intent({ phase: "speaking", segmentIndex: 1 }),
    });
    expect(result).not.toBe(current);
    expect(result.phase).toBe("speaking");
    expect(result.segmentIndex).toBe(1);
  });

  it("starts a fresh generation domain when the server session changes", () => {
    const result = reduceAvatarIntent(current, {
      sessionId: "s2",
      generation: 0,
      seq: 1,
      payload: intent({ phase: "listening", expression: "attentive" }),
    });
    expect(result.sessionId).toBe("s2");
    expect(result.generation).toBe(0);
    expect(result.phase).toBe("listening");
  });
});

function intent(overrides: Partial<AvatarIntentPayload> = {}): AvatarIntentPayload {
  return {
    phase: "idle",
    expression: "soft",
    motion: "idle",
    gazeStrength: 0.7,
    bodyTension: 0.3,
    smile: 0.5,
    eyeOpen: 0.8,
    speechRate: 1,
    speechPitch: 1,
    affect: { valence: 0, arousal: 0.2, dominance: 0, affinity: 0.4, trust: 0.4 },
    ...overrides,
  };
}
