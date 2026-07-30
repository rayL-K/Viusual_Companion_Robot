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
  private nextSaccadeAtMs = Number.NaN;
  private saccadeUntilMs = 0;
  private saccade = { x: 0, y: 0 };
  private previousAudioRms = 0;
  private speechBeat = 0;
  private lastSpeechBeatAtMs = Number.NEGATIVE_INFINITY;

  constructor(private readonly random: () => number = Math.random) {}

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
    const speechBeat = this.updateSpeechBeat(elapsedMs, deltaMs, intent.phase, audioRms);
    const saccade = this.updateSaccade(elapsedMs, gaze);
    const targetHeadX = clamp(
      gaze.x * 24 * gazeWeight + microX + motionX + reflex.headXOffset + speechBeat * 0.8,
      -28,
      28,
    );
    const targetHeadY = clamp(
      gaze.y * 15 * gazeWeight + microY + motionY + affect.dominance * 1.5
        + reflex.headYOffset - speechBeat * 1.8,
      -18,
      18,
    );
    const targetBodyX = clamp(
      targetHeadX * 0.1 + Math.sin(motionPhase * 0.72) * motion.bodyX * (0.35 + tension)
        + reflex.bodyXOffset - speechBeat * 0.55,
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
      eyeX: smooth(this.frame.eyeX, clamp(gaze.x * gazeWeight + saccade.x, -1, 1), deltaMs, 38),
      eyeY: smooth(this.frame.eyeY, clamp(gaze.y * gazeWeight + saccade.y, -1, 1), deltaMs, 42),
      eyeOpen: smooth(this.frame.eyeOpen, targetEyeOpen, deltaMs, 120),
      mouthOpen: smooth(this.frame.mouthOpen, clamp(audioRms * 2.4, 0, 1), deltaMs, 55),
      smile: smooth(this.frame.smile, targetSmile, deltaMs, 260),
      breath,
    };
    return this.frame;
  }

  private updateSpeechBeat(
    elapsedMs: number,
    deltaMs: number,
    phase: AvatarRenderIntent["phase"],
    audioRms: number,
  ): number {
    const risingEnergy = audioRms - this.previousAudioRms;
    const beatReady = elapsedMs - this.lastSpeechBeatAtMs >= 150;
    if (phase === "speaking" && audioRms >= 0.12 && risingEnergy >= 0.055 && beatReady) {
      this.speechBeat = clamp(0.25 + risingEnergy * 1.8 + audioRms * 0.35, 0, 1);
      this.lastSpeechBeatAtMs = elapsedMs;
    } else {
      this.speechBeat *= Math.exp(-Math.max(0, deltaMs) / 135);
    }
    if (phase !== "speaking") this.speechBeat = 0;
    this.previousAudioRms = audioRms;
    return this.speechBeat;
  }

  private updateSaccade(
    elapsedMs: number,
    gaze: { x: number; y: number },
  ): { x: number; y: number } {
    const userDirectedGaze = Math.hypot(gaze.x, gaze.y) > 0.075;
    if (userDirectedGaze) {
      this.saccadeUntilMs = 0;
      this.saccade = { x: 0, y: 0 };
      this.nextSaccadeAtMs = elapsedMs + this.saccadeIntervalMs();
      return this.saccade;
    }
    if (!Number.isFinite(this.nextSaccadeAtMs)) {
      this.nextSaccadeAtMs = elapsedMs + this.saccadeIntervalMs();
    }
    if (elapsedMs >= this.nextSaccadeAtMs) {
      const direction = this.random() * Math.PI * 2;
      const radius = 0.025 + this.random() * 0.07;
      this.saccade = {
        x: Math.cos(direction) * radius,
        y: Math.sin(direction) * radius * 0.62,
      };
      this.saccadeUntilMs = elapsedMs + 85 + this.random() * 95;
      this.nextSaccadeAtMs = this.saccadeUntilMs + this.saccadeIntervalMs();
    } else if (elapsedMs >= this.saccadeUntilMs) {
      this.saccade = { x: 0, y: 0 };
    }
    return this.saccade;
  }

  private saccadeIntervalMs(): number {
    const sample = this.random();
    if (sample < 0.58) return 700 + this.random() * 1_050;
    if (sample < 0.9) return 1_750 + this.random() * 1_900;
    return 3_650 + this.random() * 3_250;
  }
}
