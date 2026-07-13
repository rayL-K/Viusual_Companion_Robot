import { describe, expect, it } from "vitest";

import { detectMediaCapabilities, type CapabilityScope } from "./MediaCapabilities";
import { normalizeMediaError } from "./MediaError";

describe("media capability detection", () => {
  it("does not claim getUserMedia support outside a secure context", () => {
    const capabilities = detectMediaCapabilities({
      isSecureContext: false,
      navigator: { mediaDevices: { getUserMedia: () => undefined } },
    });
    expect(capabilities.secureContext).toBe(false);
    expect(capabilities.getUserMedia).toBe(false);
    expect(capabilities.pcmCaptureMode).toBe("unavailable");
  });

  it("reports ScriptProcessor only as an explicit compatibility fallback", () => {
    const AudioContextProbe = function AudioContextProbe() {};
    AudioContextProbe.prototype.createScriptProcessor = () => undefined;
    const capabilities = detectMediaCapabilities({
      isSecureContext: true,
      navigator: { mediaDevices: { getUserMedia: () => undefined } },
      AudioContext: AudioContextProbe,
    } as CapabilityScope);
    expect(capabilities.getUserMedia).toBe(true);
    expect(capabilities.audioWorklet).toBe(false);
    expect(capabilities.scriptProcessorFallback).toBe(true);
    expect(capabilities.pcmCaptureMode).toBe("script-processor");
  });

  it("returns readable structured permission errors", () => {
    const error = normalizeMediaError({ name: "NotAllowedError" }, "permission");
    expect(error.details).toMatchObject({
      code: "permission-denied",
      stage: "permission",
      recoverable: true,
    });
    expect(error.message).toContain("站点设置");
  });
});
