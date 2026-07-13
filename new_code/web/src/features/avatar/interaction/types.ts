export const ANIMA_BODY_AREAS = [
  "face",
  "ear.left",
  "ear.right",
  "hand.left",
  "hand.right",
  "arm.left",
  "arm.right",
  "torso",
  "skirt",
  "leg.left",
  "leg.right",
] as const;

// Directional suffixes are stage-visual left/right, never anatomical sides.
export type AnimaBodyArea = typeof ANIMA_BODY_AREAS[number];

export type ContactGesture =
  | "hover-enter"
  | "hover-leave"
  | "contact"
  | "tap"
  | "press"
  | "stroke"
  | "release";

export type ContactPointer = "mouse" | "touch" | "pen" | "keyboard";

/**
 * A privacy-safe semantic event. Raw pointer coordinates and paths stay local
 * to the renderer and are never part of the dialogue or persistence contract.
 */
export type AnimaInteractionEvent = Readonly<{
  sequence: number;
  area: AnimaBodyArea;
  gesture: ContactGesture;
  pointerType: ContactPointer;
  durationMs: number;
  intensity: number;
  direction?: Readonly<{ x: number; y: number }>;
  occurredAtMs: number;
}>;

export type BrowserPoint = Readonly<{
  clientX: number;
  clientY: number;
}>;

export type AvatarReflexFrame = Readonly<{
  headXOffset: number;
  headYOffset: number;
  bodyXOffset: number;
  smileOffset: number;
  eyeOpenOffset: number;
}>;

export interface AvatarHitTestPort {
  hitTest(point: BrowserPoint): AnimaBodyArea | null;
}
