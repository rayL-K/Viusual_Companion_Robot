import { afterEach, describe, expect, it, vi } from "vitest";

import { VideoSampler } from "./VideoSampler";

describe("VideoSampler", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("disables only semantic uploads when no frame encoder exists", () => {
    vi.stubGlobal("window", {
      setTimeout: () => 1,
      clearTimeout: () => undefined,
    });
    const errors: string[] = [];
    const status = new VideoSampler().start(
      {} as HTMLVideoElement,
      () => true,
      (error) => errors.push(error.code),
    );
    expect(status).toMatchObject({ active: false, encoder: "unavailable" });
    expect(errors).toEqual(["frame-encoding-unavailable"]);
  });
});
