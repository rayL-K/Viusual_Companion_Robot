import { describe, expect, it } from "vitest";

import { selectLive2DProfile, selectMouthAudioRms } from "./Live2DStageController";
import type { AvatarRenderIntent } from "./SignalMixer";

const speakingIntent: AvatarRenderIntent = {
  phase: "speaking",
  expression: "warm",
  motion: "talk",
  gazeStrength: 0.8,
  bodyTension: 0.5,
  smile: 0.7,
  eyeOpen: 0.85,
  speechRate: 1.1,
  speechPitch: 1.05,
  affect: { valence: 0.5, arousal: 0.6, dominance: 0.1, affinity: 0.8, trust: 0.7 },
};

describe("Live2D stage profile", () => {
  it("keeps desktop textures for capable PC promotion", () => {
    const profile = selectLive2DProfile({
      coarsePointer: false,
      narrowViewport: false,
      deviceMemoryGb: 16,
      maxTextureSize: 16_384,
    }, 1.5);

    expect(profile.label).toBe("desktop");
    expect(profile.modelUrl).toContain("Strawberry_Rabbit.model3.json");
    expect(profile.renderResolution).toBe(1.5);
  });

  it("uses the 1024 texture pack on constrained mobile GPUs", () => {
    const profile = selectLive2DProfile({
      coarsePointer: true,
      narrowViewport: true,
      deviceMemoryGb: 4,
      maxTextureSize: 4096,
    }, 2);

    expect(profile.label).toBe("mobile");
    expect(profile.modelUrl).toContain("mobile-1024-r2");
    expect(profile.renderResolution).toBe(1);
  });

  it("gives fresh WAV RMS absolute priority over synthetic mouth fallback", () => {
    const silentWavFrame = selectMouthAudioRms({
      actualRms: 0,
      actualAgeMs: 20,
      intent: speakingIntent,
      elapsedMs: 1_000,
    });
    const missingWavFrame = selectMouthAudioRms({
      actualRms: 0,
      actualAgeMs: 200,
      intent: speakingIntent,
      elapsedMs: 1_000,
    });

    expect(silentWavFrame).toBe(0);
    expect(missingWavFrame).toBeGreaterThan(0);
  });
});
