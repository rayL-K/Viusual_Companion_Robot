import { describe, expect, it } from "vitest";

import { SignalMixer, type AvatarRenderIntent } from "./SignalMixer";

const neutralIntent: AvatarRenderIntent = {
  phase: "idle",
  expression: "soft",
  motion: "idle",
  gazeStrength: 0.6,
  bodyTension: 0.2,
  smile: 0.5,
  eyeOpen: 0.8,
  speechRate: 1,
  speechPitch: 1,
  affect: {
    valence: 0,
    arousal: 0.2,
    dominance: 0,
    affinity: 0.3,
    trust: 0.3,
  },
};

describe("SignalMixer", () => {
  it("uses actual audio rms for responsive but bounded mouth movement", () => {
    const mixer = new SignalMixer();
    const quiet = mixer.update({
      elapsedMs: 0,
      deltaMs: 16,
      intent: neutralIntent,
      audioRms: 0,
      gaze: { x: 0, y: 0 },
    });
    const speaking = mixer.update({
      elapsedMs: 16,
      deltaMs: 80,
      intent: { ...neutralIntent, phase: "speaking" },
      audioRms: 0.8,
      gaze: { x: 0.5, y: -0.2 },
    });
    expect(speaking.mouthOpen).toBeGreaterThan(quiet.mouthOpen);
    expect(speaking.mouthOpen).toBeLessThanOrEqual(1);
    expect(speaking.headX).toBeGreaterThan(0);
  });

  it("continuously reflects backend affect and posture intent", () => {
    const calmMixer = new SignalMixer();
    const vividMixer = new SignalMixer();
    const calm = calmMixer.update({
      elapsedMs: 300,
      deltaMs: 500,
      intent: neutralIntent,
      audioRms: 0,
      gaze: { x: 1, y: 0 },
    });
    const vivid = vividMixer.update({
      elapsedMs: 300,
      deltaMs: 500,
      intent: {
        ...neutralIntent,
        expression: "delighted",
        motion: "excited",
        gazeStrength: 1,
        bodyTension: 1,
        smile: 0.95,
        eyeOpen: 0.96,
        affect: { valence: 0.9, arousal: 0.95, dominance: 0.6, affinity: 0.9, trust: 0.9 },
      },
      audioRms: 0,
      gaze: { x: 1, y: 0 },
    });

    expect(vivid.headX).toBeGreaterThan(calm.headX);
    expect(Math.abs(vivid.bodyX)).toBeGreaterThan(Math.abs(calm.bodyX));
    expect(vivid.eyeOpen).toBeGreaterThan(calm.eyeOpen);
    expect(vivid.smile).toBeGreaterThan(calm.smile);
  });

  it("renders thoughtful ponder as a distinct subdued thinking pose", () => {
    const neutral = new SignalMixer().update({
      elapsedMs: 700,
      deltaMs: 500,
      intent: neutralIntent,
      audioRms: 0,
      gaze: { x: 0, y: 0 },
    });
    const thinking = new SignalMixer().update({
      elapsedMs: 700,
      deltaMs: 500,
      intent: {
        ...neutralIntent,
        phase: "thinking",
        expression: "thoughtful",
        motion: "ponder",
      },
      audioRms: 0,
      gaze: { x: 0, y: 0 },
    });

    expect(thinking.smile).toBeLessThan(neutral.smile);
    expect(thinking.eyeOpen).toBeLessThan(neutral.eyeOpen);
    expect(thinking.headY).toBeGreaterThan(neutral.headY);
  });

  it("turns real speech energy rises into a short embodied beat", () => {
    const quietMixer = new SignalMixer(() => 0.5);
    const beatMixer = new SignalMixer(() => 0.5);
    const speakingIntent = { ...neutralIntent, phase: "speaking" as const };
    quietMixer.update({
      elapsedMs: 0,
      deltaMs: 16,
      intent: speakingIntent,
      audioRms: 0.05,
      gaze: { x: 0.4, y: 0 },
    });
    beatMixer.update({
      elapsedMs: 0,
      deltaMs: 16,
      intent: speakingIntent,
      audioRms: 0.05,
      gaze: { x: 0.4, y: 0 },
    });
    const quiet = quietMixer.update({
      elapsedMs: 180,
      deltaMs: 180,
      intent: speakingIntent,
      audioRms: 0.06,
      gaze: { x: 0.4, y: 0 },
    });
    const beat = beatMixer.update({
      elapsedMs: 180,
      deltaMs: 180,
      intent: speakingIntent,
      audioRms: 0.72,
      gaze: { x: 0.4, y: 0 },
    });

    expect(beat.headY).toBeLessThan(quiet.headY);
    expect(beat.bodyX).toBeLessThan(quiet.bodyX);
  });

  it("adds irregular idle micro-saccades but yields to directed gaze", () => {
    const samples = [0, 0, 0.25, 1, 0, 0, 0, 0];
    const mixer = new SignalMixer(() => samples.shift() ?? 0);
    mixer.update({
      elapsedMs: 0,
      deltaMs: 16,
      intent: neutralIntent,
      audioRms: 0,
      gaze: { x: 0, y: 0 },
    });
    const saccade = mixer.update({
      elapsedMs: 701,
      deltaMs: 32,
      intent: neutralIntent,
      audioRms: 0,
      gaze: { x: 0, y: 0 },
    });
    const directed = mixer.update({
      elapsedMs: 720,
      deltaMs: 32,
      intent: neutralIntent,
      audioRms: 0,
      gaze: { x: 0.8, y: 0 },
    });

    expect(Math.abs(saccade.eyeX) + Math.abs(saccade.eyeY)).toBeGreaterThan(0);
    expect(directed.eyeX).toBeGreaterThan(saccade.eyeX);
  });
});
