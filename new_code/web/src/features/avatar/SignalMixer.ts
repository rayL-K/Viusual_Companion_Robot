export type AffectFrame = {
  valence: number;
  arousal: number;
  affinity: number;
};

export type AvatarFrame = {
  headX: number;
  headY: number;
  eyeX: number;
  eyeY: number;
  eyeOpen: number;
  mouthOpen: number;
  smile: number;
  breath: number;
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
    eyeX: 0,
    eyeY: 0,
    eyeOpen: 1,
    mouthOpen: 0,
    smile: 0.3,
    breath: 0,
  };

  update(
    elapsedMs: number,
    deltaMs: number,
    affect: AffectFrame,
    audioRms: number,
    gaze: { x: number; y: number },
  ): AvatarFrame {
    const breath = 0.5 + Math.sin(elapsedMs / 1150) * 0.5;
    const microX = Math.sin(elapsedMs / 3370) * (1.1 + affect.arousal);
    const microY = Math.sin(elapsedMs / 4210 + 0.7) * 0.8;
    const targetHeadX = clamp(gaze.x * 24 + microX, -28, 28);
    const targetHeadY = clamp(gaze.y * 15 + microY, -18, 18);
    this.frame = {
      headX: smooth(this.frame.headX, targetHeadX, deltaMs, 180),
      headY: smooth(this.frame.headY, targetHeadY, deltaMs, 210),
      eyeX: smooth(this.frame.eyeX, clamp(gaze.x, -1, 1), deltaMs, 90),
      eyeY: smooth(this.frame.eyeY, clamp(gaze.y, -1, 1), deltaMs, 90),
      eyeOpen: smooth(this.frame.eyeOpen, clamp(0.76 + affect.arousal * 0.24, 0.55, 1), deltaMs, 120),
      mouthOpen: smooth(this.frame.mouthOpen, clamp(audioRms * 2.4, 0, 1), deltaMs, 55),
      smile: smooth(this.frame.smile, clamp((affect.valence + 1) / 2, 0, 1), deltaMs, 260),
      breath,
    };
    return this.frame;
  }
}
