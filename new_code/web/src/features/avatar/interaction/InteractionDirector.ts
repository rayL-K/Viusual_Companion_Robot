import type { AvatarRenderIntent } from "../SignalMixer";
import type { AnimaInteractionEvent, AvatarReflexFrame } from "./types";

type ActiveReflex = AvatarReflexFrame & {
  startedAtMs: number;
  expiresAtMs: number;
};

const ZERO_REFLEX: AvatarReflexFrame = {
  headXOffset: 0,
  headYOffset: 0,
  bodyXOffset: 0,
  smileOffset: 0,
  eyeOpenOffset: 0,
};

export class InteractionDirector {
  private active: ActiveReflex | null = null;

  accept(event: AnimaInteractionEvent, intent: AvatarRenderIntent): void {
    if (event.gesture === "hover-leave" || event.gesture === "release") {
      if (this.active) this.active.expiresAtMs = Math.min(this.active.expiresAtMs, event.occurredAtMs + 180);
      return;
    }

    const socialSafety = clamp((intent.affect.affinity + intent.affect.trust + 2) / 4, 0, 1);
    const sensitive = event.area === "face" || event.area.startsWith("ear.");
    const withdraw = sensitive && socialSafety < 0.46;
    const side = event.area.endsWith(".left") ? -1 : event.area.endsWith(".right") ? 1 : 0;
    const phaseScale = intent.phase === "speaking" || intent.phase === "listening" ? 0.42 : 1;
    const gestureScale = gestureStrength(event.gesture) * clamp(event.intensity, 0.2, 1) * phaseScale;
    const approach = withdraw ? -1 : 1;
    const durationMs = gestureDuration(event.gesture);

    this.active = {
      startedAtMs: event.occurredAtMs,
      expiresAtMs: event.occurredAtMs + durationMs,
      headXOffset: side * approach * 3.2 * gestureScale,
      headYOffset: (sensitive ? (withdraw ? -1.4 : 1.2) : 0.45) * gestureScale,
      bodyXOffset: side * approach * 1.8 * gestureScale,
      smileOffset: (withdraw ? -0.16 : 0.04 + socialSafety * 0.1) * gestureScale,
      eyeOpenOffset: (withdraw ? 0.12 : event.gesture === "press" || event.gesture === "stroke" ? -0.07 : 0.035)
        * gestureScale,
    };
  }

  sample(nowMs: number): AvatarReflexFrame {
    const active = this.active;
    if (!active || nowMs >= active.expiresAtMs) {
      this.active = null;
      return ZERO_REFLEX;
    }
    const duration = Math.max(active.expiresAtMs - active.startedAtMs, 1);
    const progress = clamp((nowMs - active.startedAtMs) / duration, 0, 1);
    const decay = 1 - smoothStep(progress);
    return {
      headXOffset: active.headXOffset * decay,
      headYOffset: active.headYOffset * decay,
      bodyXOffset: active.bodyXOffset * decay,
      smileOffset: active.smileOffset * decay,
      eyeOpenOffset: active.eyeOpenOffset * decay,
    };
  }

  reset(): void {
    this.active = null;
  }
}

function gestureStrength(gesture: AnimaInteractionEvent["gesture"]): number {
  if (gesture === "stroke") return 1;
  if (gesture === "press") return 0.9;
  if (gesture === "tap") return 0.72;
  if (gesture === "contact") return 0.42;
  return 0.24;
}

function gestureDuration(gesture: AnimaInteractionEvent["gesture"]): number {
  if (gesture === "stroke") return 720;
  if (gesture === "press") return 920;
  if (gesture === "tap") return 560;
  if (gesture === "contact") return 240;
  return 200;
}

function smoothStep(value: number): number {
  return value * value * (3 - 2 * value);
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
