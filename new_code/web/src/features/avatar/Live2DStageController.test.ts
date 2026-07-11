import { describe, expect, it } from "vitest";

import { selectLive2DProfile } from "./Live2DStageController";

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
});
