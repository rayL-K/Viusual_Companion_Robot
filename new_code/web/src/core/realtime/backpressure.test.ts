import { describe, expect, it } from "vitest";

import {
  assertBackpressureConfig,
  DEFAULT_REALTIME_BACKPRESSURE,
  pcmBacklogBytes,
} from "./backpressure";

describe("realtime backpressure thresholds", () => {
  it("keeps the default PCM hard budget inside the 120-200ms target", () => {
    expect(DEFAULT_REALTIME_BACKPRESSURE.pcmBacklogHardLimitMs).toBeGreaterThanOrEqual(120);
    expect(DEFAULT_REALTIME_BACKPRESSURE.pcmBacklogHardLimitMs).toBeLessThanOrEqual(200);
    expect(pcmBacklogBytes(DEFAULT_REALTIME_BACKPRESSURE, 160)).toBe(5_120);
  });

  it("rejects a recovery watermark that cannot provide hysteresis", () => {
    expect(() => assertBackpressureConfig({
      ...DEFAULT_REALTIME_BACKPRESSURE,
      pcmBacklogRecoveryMs: DEFAULT_REALTIME_BACKPRESSURE.pcmBacklogHardLimitMs,
    })).toThrow("PCM 恢复阈值必须小于硬上限");
  });
});
