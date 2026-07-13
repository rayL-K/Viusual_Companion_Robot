import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AvatarActionScheduler,
  STRAWBERRY_RABBIT_CAPABILITIES,
  type AvatarActionEnvelope,
  type AvatarOverlayExecutor,
} from "./AvatarActionScheduler";

const BASE_INTENT: AvatarActionEnvelope = {
  sessionId: "session-a",
  generation: 1,
  seq: 1,
  phase: "thinking",
  expression: "attentive",
  motion: "listen",
  gazeStrength: 0.8,
  bodyTension: 0.4,
  smile: 0.55,
  eyeOpen: 0.88,
  speechRate: 1,
  speechPitch: 1,
  affect: { valence: 0.2, arousal: 0.4, dominance: 0, affinity: 0.5, trust: 0.5 },
};

function createExecutor(overrides: Partial<AvatarOverlayExecutor> = {}) {
  return {
    setExpression: vi.fn(() => true),
    resetExpression: vi.fn(),
    startMotion: vi.fn(() => true),
    stopMotions: vi.fn(),
    ...overrides,
  } satisfies AvatarOverlayExecutor;
}

describe("AvatarActionScheduler", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-13T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("maps semantic intent to real model assets and lets higher-priority overlays preempt", () => {
    const executor = createExecutor();
    const scheduler = new AvatarActionScheduler(executor, STRAWBERRY_RABBIT_CAPABILITIES);

    expect(scheduler.submit(BASE_INTENT)).toMatchObject({
      accepted: true,
      expression: "scheduled",
      motion: "scheduled",
    });
    expect(executor.setExpression).toHaveBeenLastCalledWith("question");
    expect(executor.startMotion).toHaveBeenLastCalledWith("governor", 1);

    expect(scheduler.submit({
      ...BASE_INTENT,
      seq: 2,
      expression: "delighted",
      motion: "excited",
    })).toMatchObject({ expression: "scheduled", motion: "scheduled" });
    expect(executor.setExpression).toHaveBeenLastCalledWith("heart");
    expect(executor.startMotion).toHaveBeenLastCalledWith("admiral", 3);

    expect(scheduler.submit({ ...BASE_INTENT, seq: 3 })).toMatchObject({
      accepted: true,
      expression: "blocked",
      motion: "blocked",
    });
    scheduler.destroy();
  });

  it("maps the backend thoughtful and ponder semantics to supported model assets", () => {
    const executor = createExecutor();
    const scheduler = new AvatarActionScheduler(executor, STRAWBERRY_RABBIT_CAPABILITIES);

    expect(scheduler.submit({
      ...BASE_INTENT,
      expression: "thoughtful",
      motion: "ponder",
    })).toMatchObject({
      accepted: true,
      expression: "scheduled",
      motion: "scheduled",
    });
    expect(executor.setExpression).toHaveBeenLastCalledWith("question");
    expect(executor.startMotion).toHaveBeenLastCalledWith("scene1", 1);
    scheduler.destroy();
  });

  it("rejects stale generation and sequence while a new domain clears cooldowns", () => {
    const executor = createExecutor();
    const scheduler = new AvatarActionScheduler(executor, STRAWBERRY_RABBIT_CAPABILITIES);
    scheduler.submit({ ...BASE_INTENT, expression: "heart", motion: "captain" });
    const expressionCalls = vi.mocked(executor.setExpression).mock.calls.length;

    expect(scheduler.submit({ ...BASE_INTENT, generation: 0, seq: 99 }).accepted).toBe(false);
    expect(scheduler.submit({ ...BASE_INTENT, seq: 1 }).accepted).toBe(false);
    expect(executor.setExpression).toHaveBeenCalledTimes(expressionCalls);

    expect(scheduler.submit({ ...BASE_INTENT, generation: 2, seq: 0, expression: "heart" })).toMatchObject({
      accepted: true,
      expression: "scheduled",
    });
    expect(scheduler.submit({
      ...BASE_INTENT,
      sessionId: "session-b",
      generation: 0,
      seq: 0,
      expression: "heart",
    })).toMatchObject({ accepted: true, expression: "scheduled" });
    scheduler.destroy();
  });

  it("enforces per-asset cooldown after duration without leaving timers behind", () => {
    const executor = createExecutor();
    const scheduler = new AvatarActionScheduler(executor, STRAWBERRY_RABBIT_CAPABILITIES);
    scheduler.submit({ ...BASE_INTENT, expression: "heart", motion: "missing-motion" });

    vi.advanceTimersByTime(2_400);
    expect(executor.resetExpression).toHaveBeenCalled();
    expect(scheduler.submit({
      ...BASE_INTENT,
      seq: 2,
      expression: "heart",
      motion: "missing-motion",
    }).expression).toBe("cooldown");

    vi.advanceTimersByTime(1_800);
    expect(scheduler.submit({
      ...BASE_INTENT,
      seq: 3,
      expression: "heart",
      motion: "missing-motion",
    }).expression).toBe("scheduled");
    scheduler.destroy();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("safely ignores unsupported capabilities and cleans up rejected starts", async () => {
    const executor = createExecutor({
      setExpression: vi.fn(() => Promise.reject(new Error("asset load failed"))),
    });
    const scheduler = new AvatarActionScheduler(executor, {
      expressions: new Set(["heart"]),
      motions: new Set(),
    });

    expect(scheduler.submit({
      ...BASE_INTENT,
      expression: "missing-expression",
      motion: "missing-motion",
    })).toMatchObject({ expression: "unsupported", motion: "unsupported" });
    expect(executor.setExpression).not.toHaveBeenCalled();
    expect(executor.startMotion).not.toHaveBeenCalled();

    expect(scheduler.submit({
      ...BASE_INTENT,
      seq: 2,
      expression: "heart",
      motion: "missing-motion",
    }).expression).toBe("scheduled");
    await Promise.resolve();
    expect(vi.getTimerCount()).toBe(0);
    expect(executor.resetExpression).toHaveBeenCalled();
    scheduler.destroy();
  });

  it("does not let a stale async start completion cancel its replacement", async () => {
    let resolveFirst: ((started: boolean) => void) | undefined;
    const firstStart = new Promise<boolean>((resolve) => { resolveFirst = resolve; });
    const executor = createExecutor({
      setExpression: vi.fn()
        .mockReturnValueOnce(firstStart)
        .mockReturnValue(true),
    });
    const scheduler = new AvatarActionScheduler(executor, STRAWBERRY_RABBIT_CAPABILITIES);
    scheduler.submit({ ...BASE_INTENT, expression: "question", motion: "missing-motion" });
    scheduler.submit({
      ...BASE_INTENT,
      seq: 2,
      expression: "heart",
      motion: "missing-motion",
    });

    resolveFirst?.(false);
    await Promise.resolve();
    expect(vi.getTimerCount()).toBe(1);
    vi.advanceTimersByTime(2_400);
    expect(vi.getTimerCount()).toBe(0);
    scheduler.destroy();
  });
});
