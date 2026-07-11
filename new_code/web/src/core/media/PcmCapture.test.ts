import { describe, expect, it } from "vitest";

import { PCM_FRAME_DURATION_MS, PCM_FRAME_SAMPLES, PCM_SAMPLE_RATE } from "./PcmCapture";

describe("PCM capture contract", () => {
  it("emits exact 20 ms frames for streaming ASR", () => {
    expect(PCM_SAMPLE_RATE).toBe(16_000);
    expect(PCM_FRAME_SAMPLES).toBe(320);
    expect(PCM_FRAME_DURATION_MS).toBe(20);
  });
});
