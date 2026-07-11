import { describe, expect, it } from "vitest";

import { AudioSegmentQueue, type PlayableAudio } from "./AudioSegmentQueue";

describe("AudioSegmentQueue", () => {
  it("does not reveal text before audio reports actual playback", async () => {
    let releasePlayback!: () => void;
    const playbackStarted = new Promise<void>((resolve) => { releasePlayback = resolve; });
    let revealed = false;
    const queue = new AudioSegmentQueue(() => ({
      play: () => playbackStarted,
      stop: releasePlayback,
      waitForEnd: async () => undefined,
      dispose: () => undefined,
    }));

    queue.enqueue(new ArrayBuffer(1), "audio/wav", () => { revealed = true; });
    await Promise.resolve();
    expect(revealed).toBe(false);
    releasePlayback();
    await queue.whenIdle();
    expect(revealed).toBe(true);
  });

  it("starts text callbacks in audio playback order", async () => {
    const started: string[] = [];
    const factory = (data: ArrayBuffer): PlayableAudio => {
      const id = String(new Uint8Array(data)[0]);
      return {
        play: async () => undefined,
        stop: () => undefined,
        waitForEnd: async () => undefined,
        dispose: () => undefined,
      };
    };
    const queue = new AudioSegmentQueue(factory);
    queue.enqueue(new Uint8Array([1]).buffer, "audio/wav", () => started.push("1"));
    queue.enqueue(new Uint8Array([2]).buffer, "audio/wav", () => started.push("2"));
    await queue.whenIdle();
    expect(started).toEqual(["1", "2"]);
  });

  it("suppresses queued segments after interruption", async () => {
    let releaseFirst!: () => void;
    const firstEnded = new Promise<void>((resolve) => { releaseFirst = resolve; });
    let created = 0;
    const queue = new AudioSegmentQueue(() => {
      created += 1;
      return {
        play: async () => undefined,
        stop: () => releaseFirst(),
        waitForEnd: () => created === 1 ? firstEnded : Promise.resolve(),
        dispose: () => undefined,
      };
    });
    const started: number[] = [];
    queue.enqueue(new ArrayBuffer(1), "audio/wav", () => started.push(1));
    queue.enqueue(new ArrayBuffer(1), "audio/wav", () => started.push(2));
    await Promise.resolve();
    queue.stop();
    releaseFirst();
    await Promise.resolve();
    expect(started).not.toContain(2);
  });
});
