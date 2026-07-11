import { describe, expect, it } from "vitest";

import { SignalMixer } from "./SignalMixer";

describe("SignalMixer", () => {
  it("uses audio rms for responsive but bounded mouth movement", () => {
    const mixer = new SignalMixer();
    const quiet = mixer.update(0, 16, { valence: 0, arousal: 0.2, affinity: 0.3 }, 0, { x: 0, y: 0 });
    const speaking = mixer.update(16, 80, { valence: 0.4, arousal: 0.6, affinity: 0.5 }, 0.8, { x: 0.5, y: -0.2 });
    expect(speaking.mouthOpen).toBeGreaterThan(quiet.mouthOpen);
    expect(speaking.mouthOpen).toBeLessThanOrEqual(1);
    expect(speaking.headX).toBeGreaterThan(0);
  });
});
