import type { GestureHandlers, UserGestureConfig } from "@use-gesture/vanilla";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AvatarInteractionController,
  INTERACTION_TIMING,
  type AvatarInteractionCallbacks,
} from "./AvatarInteractionController";
import type {
  AnimaBodyArea,
  AnimaInteractionEvent,
  AvatarHitTestPort,
  BrowserPoint,
} from "./types";

type PointerInit = {
  pointerId?: number;
  pointerType?: string;
  button?: number;
  isPrimary?: boolean;
  clientX?: number;
  clientY?: number;
};

class FakePointerEvent extends Event {
  readonly pointerId: number;
  readonly pointerType: string;
  readonly button: number;
  readonly isPrimary: boolean;
  readonly clientX: number;
  readonly clientY: number;

  constructor(type: string, init: PointerInit = {}) {
    super(type);
    this.pointerId = init.pointerId ?? 1;
    this.pointerType = init.pointerType ?? "mouse";
    this.button = init.button ?? 0;
    this.isPrimary = init.isPrimary ?? true;
    this.clientX = init.clientX ?? 200;
    this.clientY = init.clientY ?? 100;
  }
}

type TestDragState = {
  active: boolean;
  first: boolean;
  last: boolean;
  canceled: boolean;
  tap: boolean;
  xy: [number, number];
  movement: [number, number];
  direction: [number, number];
  velocity: [number, number];
  event: Event;
};

type TestHandlers = {
  onPointerDown?: (state: { event: Event }) => void;
  onPointerCancel?: () => void;
  onLostPointerCapture?: () => void;
  onPointerLeave?: () => void;
  onMove?: (state: { xy: [number, number] }) => void;
  onDrag?: (state: TestDragState) => void;
};

type Harness = ReturnType<typeof createHarness>;

function createHarness(options: {
  area?: AnimaBodyArea | null;
  hitTest?: (point: BrowserPoint) => AnimaBodyArea | null;
} = {}) {
  let nowMs = 10_000;
  let handlers: TestHandlers = {};
  const events: AnimaInteractionEvent[] = [];
  const gazes: Array<Readonly<{ x: number; y: number }>> = [];
  const feedback: Array<Readonly<BrowserPoint & { area: AnimaBodyArea }>> = [];
  const gestureDestroy = vi.fn();
  const hitTest = vi.fn<AvatarHitTestPort["hitTest"]>(
    options.hitTest ?? (() => options.area === undefined ? "face" : options.area),
  );
  const host = {
    getBoundingClientRect: () => ({
      left: 100,
      top: 50,
      width: 200,
      height: 100,
      right: 300,
      bottom: 150,
      x: 100,
      y: 50,
      toJSON: () => ({}),
    }),
  } as unknown as HTMLElement;
  const callbacks: AvatarInteractionCallbacks = {
    onInteraction: (event) => events.push(event),
    onGaze: (gaze) => gazes.push(gaze),
    onFeedback: (value) => feedback.push(value),
  };
  const gestureFactory = vi.fn((
    target: EventTarget,
    registered: GestureHandlers,
    config: UserGestureConfig,
  ) => {
    handlers = registered as unknown as TestHandlers;
    return { destroy: gestureDestroy };
  });
  const controller = new AvatarInteractionController(
    host,
    { hitTest },
    callbacks,
    {
      now: () => nowMs,
      setTimer: (callback, delayMs) => setTimeout(callback, delayMs),
      clearTimer: (handle) => clearTimeout(handle),
      gestureFactory,
    },
  );
  controller.start();

  return {
    controller,
    events,
    gazes,
    feedback,
    gestureDestroy,
    gestureFactory,
    hitTest,
    host,
    get handlers() { return handlers; },
    advanceBy(ms: number) {
      nowMs += ms;
      vi.advanceTimersByTime(ms);
    },
    pointerDown(init: PointerInit = {}) {
      const event = new FakePointerEvent("pointerdown", init);
      handlers.onPointerDown?.({ event });
      return event;
    },
    drag(overrides: Partial<TestDragState> = {}) {
      const xy = overrides.xy ?? [200, 100];
      const event = overrides.event ?? new FakePointerEvent("pointermove", {
        clientX: xy[0],
        clientY: xy[1],
      });
      handlers.onDrag?.({
        active: true,
        first: false,
        last: false,
        canceled: false,
        tap: false,
        xy,
        movement: [0, 0],
        direction: [0, 0],
        velocity: [0, 0],
        event,
        ...overrides,
      });
    },
  };
}

function gestures(harness: Harness): string[] {
  return harness.events.map((event) => event.gesture);
}

describe("AvatarInteractionController", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("PointerEvent", FakePointerEvent);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("binds the fake host and turns a primary left-button contact into local feedback", () => {
    const harness = createHarness({ area: "hand.left" });

    harness.pointerDown({
      pointerId: 8,
      pointerType: "mouse",
      button: 0,
      isPrimary: true,
      clientX: 155,
      clientY: 86,
    });

    expect(harness.gestureFactory).toHaveBeenCalledOnce();
    expect(harness.gestureFactory.mock.calls[0]?.[0]).toBe(harness.host);
    expect(harness.hitTest).toHaveBeenCalledWith({ clientX: 155, clientY: 86 });
    expect(harness.events).toEqual([
      expect.objectContaining({
        sequence: 1,
        area: "hand.left",
        gesture: "contact",
        pointerType: "mouse",
        durationMs: 0,
        intensity: 0.35,
        occurredAtMs: 10_000,
      }),
    ]);
    expect(harness.feedback).toEqual([{ clientX: 155, clientY: 86, area: "hand.left" }]);
    expect(vi.getTimerCount()).toBe(1);
  });

  it("emits the accessible primary contact as a keyboard face tap", () => {
    const harness = createHarness();

    harness.controller.primaryContact();

    expect(harness.events).toEqual([
      expect.objectContaining({
        sequence: 1,
        area: "face",
        gesture: "tap",
        pointerType: "keyboard",
        durationMs: 0,
        intensity: 0.55,
        occurredAtMs: 10_000,
      }),
    ]);
    expect(harness.hitTest).not.toHaveBeenCalled();
  });

  it("classifies a short contact as tap, clears its press timer, then releases", () => {
    const harness = createHarness({ area: "face" });
    const pointer = harness.pointerDown({ clientX: 200, clientY: 100 });
    harness.advanceBy(120);

    harness.drag({
      active: false,
      last: true,
      tap: true,
      xy: [201, 101],
      movement: [1, 1],
      event: pointer,
    });

    expect(gestures(harness)).toEqual(["contact", "tap", "release"]);
    expect(harness.events[1]).toMatchObject({
      durationMs: 120,
      intensity: 0.62,
      pointerType: "mouse",
    });
    expect(harness.events[2]).toMatchObject({ durationMs: 120, intensity: 0 });
    expect(harness.events.map((event) => event.sequence)).toEqual([1, 2, 3]);
    expect(vi.getTimerCount()).toBe(0);

    harness.advanceBy(INTERACTION_TIMING.pressDelayMs);
    expect(gestures(harness)).toEqual(["contact", "tap", "release"]);
  });

  it("emits one held press at the fake deadline and does not duplicate it on release", () => {
    const harness = createHarness({ area: "ear.right" });
    const pointer = harness.pointerDown({ pointerType: "touch", clientX: 230, clientY: 74 });

    harness.advanceBy(INTERACTION_TIMING.pressDelayMs - 1);
    expect(gestures(harness)).toEqual(["contact"]);
    harness.advanceBy(1);
    expect(gestures(harness)).toEqual(["contact", "press"]);
    expect(harness.events[1]).toMatchObject({
      area: "ear.right",
      pointerType: "touch",
      durationMs: INTERACTION_TIMING.pressDelayMs,
      intensity: 0.72,
    });

    harness.drag({
      active: false,
      last: true,
      tap: true,
      xy: [230, 74],
      event: pointer,
    });

    expect(gestures(harness)).toEqual(["contact", "press", "release"]);
    expect(harness.feedback).toHaveLength(2);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("throttles strokes, normalizes their direction, and cancels the pending press", () => {
    const harness = createHarness({ area: "torso" });
    const pointer = harness.pointerDown({ clientX: 180, clientY: 90 });

    harness.drag({
      xy: [188, 90],
      movement: [8, 0],
      direction: [3, 4],
      velocity: [0.4, 0.3],
      event: pointer,
    });
    expect(gestures(harness)).toEqual(["contact", "stroke"]);
    expect(harness.events[1]).toMatchObject({
      direction: { x: 0.6, y: 0.8 },
      durationMs: 0,
    });
    expect(vi.getTimerCount()).toBe(0);

    harness.advanceBy(INTERACTION_TIMING.strokeIntervalMs - 1);
    harness.drag({
      xy: [205, 90],
      movement: [25, 0],
      direction: [1, 0],
      velocity: [0.7, 0],
      event: pointer,
    });
    expect(gestures(harness)).toEqual(["contact", "stroke"]);

    harness.advanceBy(1);
    harness.drag({
      xy: [206, 90],
      movement: [26, 0],
      direction: [1, 0],
      velocity: [0.7, 0],
      event: pointer,
    });
    expect(gestures(harness)).toEqual(["contact", "stroke", "stroke"]);

    harness.drag({
      active: false,
      last: true,
      xy: [206, 90],
      movement: [26, 0],
      event: pointer,
    });
    expect(gestures(harness)).toEqual(["contact", "stroke", "stroke", "release"]);
    expect(harness.feedback).toHaveLength(3);
  });

  it("cancels contact and its pending press without emitting release", () => {
    const harness = createHarness({ area: "arm.left" });
    harness.pointerDown({ clientX: 140, clientY: 110 });

    harness.handlers.onPointerCancel?.();
    harness.advanceBy(INTERACTION_TIMING.pressDelayMs + 100);

    expect(gestures(harness)).toEqual(["contact"]);
    expect(vi.getTimerCount()).toBe(0);

    harness.drag({
      active: false,
      last: true,
      tap: true,
      xy: [140, 110],
    });
    expect(gestures(harness)).toEqual(["contact"]);
  });

  it("ignores right-click and non-primary contacts before hit testing", () => {
    const harness = createHarness();

    harness.pointerDown({ button: 2, pointerType: "mouse", isPrimary: true });
    harness.pointerDown({ button: 0, pointerType: "touch", isPrimary: false });

    expect(harness.hitTest).not.toHaveBeenCalled();
    expect(harness.events).toEqual([]);
    expect(harness.feedback).toEqual([]);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("normalizes and clamps gaze against the fake host bounds", () => {
    const harness = createHarness();

    harness.handlers.onMove?.({ xy: [100, 50] });
    harness.handlers.onMove?.({ xy: [200, 100] });
    harness.handlers.onMove?.({ xy: [350, 180] });

    expect(harness.gazes[0]).toEqual({ x: -1, y: 1 });
    expect(harness.gazes[1]?.x).toBeCloseTo(0);
    expect(harness.gazes[1]?.y).toBeCloseTo(0);
    expect(harness.gazes[2]).toEqual({ x: 1, y: -1 });

    harness.handlers.onPointerLeave?.();
    expect(harness.gazes.at(-1)).toEqual({ x: 0, y: 0 });
  });

  it("keeps raw coordinates and movement out of every semantic event", () => {
    const harness = createHarness({ area: "skirt" });
    const pointer = harness.pointerDown({ clientX: 173, clientY: 129 });
    harness.drag({
      xy: [191, 133],
      movement: [18, 4],
      direction: [1, 0.25],
      velocity: [0.8, 0.2],
      event: pointer,
    });
    harness.drag({
      active: false,
      last: true,
      xy: [191, 133],
      movement: [18, 4],
      event: pointer,
    });

    for (const event of harness.events) {
      expect(event).not.toHaveProperty("clientX");
      expect(event).not.toHaveProperty("clientY");
      expect(event).not.toHaveProperty("xy");
      expect(event).not.toHaveProperty("point");
      expect(event).not.toHaveProperty("path");
      expect(event).not.toHaveProperty("movement");
      expect(event).not.toHaveProperty("velocity");
    }
    expect(JSON.stringify(harness.events)).not.toContain("clientX");
    expect(JSON.stringify(harness.events)).not.toContain("clientY");
    expect(harness.feedback[0]).toMatchObject({ clientX: 173, clientY: 129 });
  });

  it("destroys gesture and pending timer idempotently", () => {
    const harness = createHarness();
    harness.pointerDown();
    expect(vi.getTimerCount()).toBe(1);

    harness.controller.destroy();
    harness.controller.destroy();

    expect(harness.gestureDestroy).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
    expect(harness.events).toEqual([
      expect.objectContaining({ gesture: "contact" }),
    ]);

    harness.advanceBy(INTERACTION_TIMING.pressDelayMs + 100);
    expect(gestures(harness)).toEqual(["contact"]);
  });

  it("clears an in-flight contact before rebinding", () => {
    const harness = createHarness();
    harness.pointerDown();
    expect(vi.getTimerCount()).toBe(1);

    harness.controller.start();
    expect(harness.gestureDestroy).toHaveBeenCalledOnce();
    expect(harness.gestureFactory).toHaveBeenCalledTimes(2);
    expect(vi.getTimerCount()).toBe(0);
    expect(harness.gazes.at(-1)).toEqual({ x: 0, y: 0 });

    harness.advanceBy(INTERACTION_TIMING.pressDelayMs + 100);
    expect(gestures(harness)).toEqual(["contact"]);
  });
});
