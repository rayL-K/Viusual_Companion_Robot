import type { AvatarReflexFrame } from "./interaction/types";

export type AffectFrame = {
  valence: number;
  arousal: number;
  dominance: number;
  affinity: number;
  trust: number;
};

export type AvatarRenderIntent = {
  phase: "idle" | "listening" | "thinking" | "speaking";
  expression: string;
  motion: string;
  gazeStrength: number;
  bodyTension: number;
  smile: number;
  eyeOpen: number;
  speechRate: number;
  speechPitch: number;
  affect: AffectFrame;
};

export type AvatarFrame = {
  headX: number;
  headY: number;
  bodyX: number;
  eyeX: number;
  eyeY: number;
  eyeOpen: number;
  mouthOpen: number;
  smile: number;
  breath: number;
};

export type SignalMixerInput = {
  elapsedMs: number;
  deltaMs: number;
  intent: AvatarRenderIntent;
  audioRms: number;
  gaze: { x: number; y: number };
  reflex?: AvatarReflexFrame;
};

type MotionProfile = {
  periodMs: number;
  headX: number;
  headY: number;
  bodyX: number;
};

const DEFAULT_MOTION: MotionProfile = { periodMs: 4_200, headX: 0.55, headY: 0.45, bodyX: 0.55 };
const MOTION_PROFILES: Readonly<Record<string, MotionProfile>> = {
  idle: DEFAULT_MOTION,
  listen: { periodMs: 2_800, headX: 0.45, headY: 1.15, bodyX: 0.65 },
  ponder: { periodMs: 3_200, headX: 0.35, headY: 1.05, bodyX: 0.45 },
  talk: { periodMs: 1_800, headX: 1.35, headY: 0.8, bodyX: 1.1 },
  excited: { periodMs: 1_050, headX: 2.7, headY: 1.9, bodyX: 2.1 },
  comfort: { periodMs: 3_600, headX: 0.8, headY: 0.55, bodyX: 1.4 },
};

const DEFAULT_EXPRESSION = { smile: 0, eyeOpen: 0 };
const EXPRESSION_BIASES: Readonly<Record<string, { smile: number; eyeOpen: number }>> = {
  soft: DEFAULT_EXPRESSION,
  attentive: { smile: 0.02, eyeOpen: 0.06 },
  thoughtful: { smile: -0.05, eyeOpen: -0.04 },
  warm: { smile: 0.06, eyeOpen: 0.02 },
  delighted: { smile: 0.13, eyeOpen: 0.08 },
  concerned: { smile: -0.16, eyeOpen: -0.05 },
};

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));
const smooth = (current: number, target: number, deltaMs: number, responseMs: number) => {
  const weight = 1 - Math.exp(-Math.max(0, deltaMs) / responseMs);
  return current + (target - current) * weight;
};

export class SignalMixer {
  private frame: AvatarFrame = {
    headX: 0,
    headY: 0,
    bodyX: 0,
    eyeX: 0,
    eyeY: 0,
    eyeOpen: 1,
    mouthOpen: 0,
    smile: 0.3,
    breath: 0,
  };

  update(input: SignalMixerInput): AvatarFrame {
    const { elapsedMs, deltaMs, intent, audioRms, gaze } = input;
    const reflex = input.reflex ?? {
      headXOffset: 0,
      headYOffset: 0,
      bodyXOffset: 0,
      smileOffset: 0,
      eyeOpenOffset: 0,
    };
    const { affect } = intent;
    const motion = MOTION_PROFILES[intent.motion.toLowerCase()] ?? DEFAULT_MOTION;
    const expression = EXPRESSION_BIASES[intent.expression.toLowerCase()] ?? DEFAULT_EXPRESSION;
    const socialAttention = clamp((affect.affinity + affect.trust + 2) / 4, 0, 1);
    const gazeWeight = clamp(intent.gazeStrength, 0, 1) * (0.68 + socialAttention * 0.32);
    const cadence = intent.phase === "speaking"
      ? clamp(intent.speechRate * Math.sqrt(intent.speechPitch), 0.65, 1.65)
      : 1;
    const motionPhase = elapsedMs / motion.periodMs * Math.PI * 2 * cadence;
    const tension = clamp(intent.bodyTension, 0, 1);
    const microScale = 0.7 + affect.arousal * 0.75 + tension * 0.55;
    const microX = Math.sin(elapsedMs / 3_370) * microScale;
    const microY = Math.sin(elapsedMs / 4_210 + 0.7) * (0.55 + tension * 0.35);
    const motionX = Math.sin(motionPhase) * motion.headX * tension;
    const motionY = Math.sin(motionPhase * 0.58 + 0.8) * motion.headY * tension;
    const targetHeadX = clamp(gaze.x * 24 * gazeWeight + microX + motionX + reflex.headXOffset, -28, 28);
    const targetHeadY = clamp(
      gaze.y * 15 * gazeWeight + microY + motionY + affect.dominance * 1.5 + reflex.headYOffset,
      -18,
      18,
    );
    const targetBodyX = clamp(
      targetHeadX * 0.1 + Math.sin(motionPhase * 0.72) * motion.bodyX * (0.35 + tension)
        + reflex.bodyXOffset,
      -10,
      10,
    );
    const emotionalSmile = (affect.valence + 1) / 2;
    const targetSmile = clamp(
      intent.smile * 0.78 + emotionalSmile * 0.22 + expression.smile + reflex.smileOffset,
      0,
      1,
    );
    const targetEyeOpen = clamp(
      intent.eyeOpen + expression.eyeOpen + affect.arousal * 0.03 + reflex.eyeOpenOffset,
      0.45,
      1,
    );
    const breathPeriod = 1_350 - affect.arousal * 320 + tension * 90;
    const breath = 0.5 + Math.sin(elapsedMs / breathPeriod) * 0.5;
    const postureResponseMs = 260 - tension * 115;

    this.frame = {
      headX: smooth(this.frame.headX, targetHeadX, deltaMs, postureResponseMs),
      headY: smooth(this.frame.headY, targetHeadY, deltaMs, postureResponseMs + 30),
      bodyX: smooth(this.frame.bodyX, targetBodyX, deltaMs, postureResponseMs + 80),
      eyeX: smooth(this.frame.eyeX, clamp(gaze.x * gazeWeight, -1, 1), deltaMs, 90),
      eyeY: smooth(this.frame.eyeY, clamp(gaze.y * gazeWeight, -1, 1), deltaMs, 90),
      eyeOpen: smooth(this.frame.eyeOpen, targetEyeOpen, deltaMs, 120),
      mouthOpen: smooth(this.frame.mouthOpen, clamp(audioRms * 2.4, 0, 1), deltaMs, 55),
      smile: smooth(this.frame.smile, targetSmile, deltaMs, 260),
      breath,
    };
    return this.frame;
  }
}
