import type { AnimaBodyArea } from "./types";

export const STRAWBERRY_RABBIT_HIT_AREA_MAP: Readonly<Record<string, AnimaBodyArea>> = {
  Face: "face",
  EarVisualLeft: "ear.left",
  EarVisualRight: "ear.right",
  HandVisualLeft: "hand.left",
  HandVisualRight: "hand.right",
  ArmVisualLeft: "arm.left",
  ArmVisualRight: "arm.right",
  Torso: "torso",
  Skirt: "skirt",
  LegVisualLeft: "leg.left",
  LegVisualRight: "leg.right",
};

export const STRAWBERRY_RABBIT_HIT_PRIORITY: readonly AnimaBodyArea[] = [
  "hand.left",
  "hand.right",
  "arm.left",
  "arm.right",
  "ear.left",
  "ear.right",
  "face",
  "torso",
  "skirt",
  "leg.left",
  "leg.right",
];

const PRIORITY = new Map(STRAWBERRY_RABBIT_HIT_PRIORITY.map((area, index) => [area, index]));

export function selectStrawberryRabbitBodyArea(hitAreaNames: readonly string[]): AnimaBodyArea | null {
  let selected: AnimaBodyArea | null = null;
  let selectedPriority = Number.POSITIVE_INFINITY;
  for (const name of hitAreaNames) {
    const area = STRAWBERRY_RABBIT_HIT_AREA_MAP[name];
    if (!area) continue;
    const priority = PRIORITY.get(area) ?? Number.POSITIVE_INFINITY;
    if (priority < selectedPriority) {
      selected = area;
      selectedPriority = priority;
    }
  }
  return selected;
}
