import { describe, expect, it } from "vitest";

import type { AvatarRenderIntent } from "../SignalMixer";
import { InteractionDirector } from "./InteractionDirector";
import type { AnimaInteractionEvent, AvatarReflexFrame } from "./types";

const BASE_INTENT: AvatarRenderIntent = {
  phase: "idle",
  expression: "soft",
  motion: "idle",
  gazeStrength: 0.7,
  bodyTension: 0.3,
  smile: 0.5,
  eyeOpen: 0.8,
  speechRate: 1,
  speechPitch: 1,
  affect: { valence: 0, arousal: 0.3, dominance: 0, affinity: 0, trust: 0 },
};

const ZERO_REFLEX: AvatarReflexFrame = {
  headXOffset: 0,
  headYOffset: 0,
  bodyXOffset: 0,
  smileOffset: 0,
  eyeOpenOffset: 0,
};

describe("InteractionDirector", () => {
  it("approaches sensitive contact at high trust and withdraws at low trust", () => {
    const event = interactionEvent({ area: "ear.right", gesture: "stroke", intensity: 1 });
    const highTrust = new InteractionDirector();
    highTrust.accept(event, {
      ...BASE_INTENT,
      affect: { ...BASE_INTENT.affect, affinity: 0.9, trust: 0.9 },
    });
    const approach = highTrust.sample(event.occurredAtMs);

    const lowTrust = new InteractionDirector();
    lowTrust.accept(event, {
      ...BASE_INTENT,
      affect: { ...BASE_INTENT.affect, affinity: -0.9, trust: -0.9 },
    });
    const withdraw = lowTrust.sample(event.occurredAtMs);

    expect(approach.headXOffset).toBeGreaterThan(0);
    expect(approach.bodyXOffset).toBeGreaterThan(0);
    expect(approach.smileOffset).toBeGreaterThan(0);
    expect(approach.eyeOpenOffset).toBeLessThan(0);
    expect(withdraw.headXOffset).toBeLessThan(0);
    expect(withdraw.bodyXOffset).toBeLessThan(0);
    expect(withdraw.smileOffset).toBeLessThan(0);
    expect(withdraw.eyeOpenOffset).toBeGreaterThan(0);
  });

  it("attenuates local reflexes while the Anima is speaking", () => {
    const event = interactionEvent({ area: "hand.right", gesture: "tap", intensity: 0.8 });
    const idle = new InteractionDirector();
    idle.accept(event, BASE_INTENT);
    const idleFrame = idle.sample(event.occurredAtMs);

    const speaking = new InteractionDirector();
    speaking.accept(event, { ...BASE_INTENT, phase: "speaking" });
    const speakingFrame = speaking.sample(event.occurredAtMs);

    expect(Math.abs(speakingFrame.headXOffset)).toBeLessThan(Math.abs(idleFrame.headXOffset));
    expect(Math.abs(speakingFrame.bodyXOffset)).toBeLessThan(Math.abs(idleFrame.bodyXOffset));
    expect(Math.abs(speakingFrame.smileOffset)).toBeLessThan(Math.abs(idleFrame.smileOffset));
  });

  it("expires naturally, shortens on release, and reset clears immediately", () => {
    const director = new InteractionDirector();
    const tap = interactionEvent({ gesture: "tap", occurredAtMs: 1_000 });
    director.accept(tap, BASE_INTENT);
    expect(director.sample(1_200)).not.toEqual(ZERO_REFLEX);
    expect(director.sample(1_560)).toEqual(ZERO_REFLEX);

    const press = interactionEvent({ gesture: "press", occurredAtMs: 2_000 });
    director.accept(press, BASE_INTENT);
    director.accept(interactionEvent({ gesture: "release", occurredAtMs: 2_100 }), BASE_INTENT);
    expect(director.sample(2_200)).not.toEqual(ZERO_REFLEX);
    expect(director.sample(2_280)).toEqual(ZERO_REFLEX);

    director.accept(interactionEvent({ gesture: "stroke", occurredAtMs: 3_000 }), BASE_INTENT);
    director.reset();
    expect(director.sample(3_000)).toEqual(ZERO_REFLEX);
  });
});

function interactionEvent(
  overrides: Partial<AnimaInteractionEvent> = {},
): AnimaInteractionEvent {
  return {
    sequence: 1,
    area: "face",
    gesture: "tap",
    pointerType: "mouse",
    durationMs: 0,
    intensity: 0.7,
    occurredAtMs: 1_000,
    ...overrides,
  };
}
