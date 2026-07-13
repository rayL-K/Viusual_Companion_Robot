import { describe, expect, it } from "vitest";

import desktopModel from "../../../../public/live2d/Strawberry_Rabbit/Strawberry_Rabbit.model3.json";
import mobileModel from "../../../../public/live2d/Strawberry_Rabbit/Strawberry_Rabbit.mobile-1024-r2.model3.json";
import manifest from "../../../../public/live2d/Strawberry_Rabbit/manifest.json";
import {
  selectStrawberryRabbitBodyArea,
  STRAWBERRY_RABBIT_HIT_AREA_MAP,
  STRAWBERRY_RABBIT_HIT_PRIORITY,
} from "./StrawberryRabbitHitAreas";

describe("StrawberryRabbitHitAreas", () => {
  it("keeps the runtime map, manifest, and desktop/mobile model hit areas synchronized", () => {
    expect(STRAWBERRY_RABBIT_HIT_AREA_MAP).toEqual(manifest.hitAreaMap);
    expect(STRAWBERRY_RABBIT_HIT_PRIORITY).toEqual(manifest.hitPriority);
    expect(desktopModel.HitAreas).toEqual(mobileModel.HitAreas);

    const declaredNames = desktopModel.HitAreas.map((area) => area.Name);
    expect(new Set(declaredNames)).toEqual(new Set(Object.keys(STRAWBERRY_RABBIT_HIT_AREA_MAP)));
    expect(new Set(desktopModel.HitAreas.map((area) => area.Id)).size).toBe(desktopModel.HitAreas.length);
  });

  it("ignores unknown meshes and selects overlapping areas by semantic priority", () => {
    expect(selectStrawberryRabbitBodyArea([
      "UnknownMesh",
      "Face",
      "ArmVisualLeft",
      "HandVisualRight",
      "Torso",
    ])).toBe("hand.right");
    expect(selectStrawberryRabbitBodyArea(["UnknownMesh"])).toBeNull();
    expect(selectStrawberryRabbitBodyArea([])).toBeNull();
  });
});
