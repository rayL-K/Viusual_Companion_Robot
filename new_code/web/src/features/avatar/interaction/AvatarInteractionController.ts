import {
  Gesture,
  type GestureHandlers,
  type UserGestureConfig,
} from "@use-gesture/vanilla";

import type {
  AnimaBodyArea,
  AnimaInteractionEvent,
  AvatarHitTestPort,
  BrowserPoint,
  ContactPointer,
} from "./types";

const PRESS_DELAY_MS = 380;
const STROKE_DISTANCE_PX = 7;
const STROKE_INTERVAL_MS = 48;

type GestureHandle = { destroy: () => void };
type GestureFactory = (
  target: EventTarget,
  handlers: GestureHandlers,
  config: UserGestureConfig,
) => GestureHandle;

type TimerHandle = ReturnType<typeof setTimeout>;

type ActiveContact = {
  pointerId: number;
  pointerType: ContactPointer;
  area: AnimaBodyArea;
  startedAtMs: number;
  lastStrokeAtMs: number;
  lastPoint: BrowserPoint;
  pressEmitted: boolean;
  strokeEmitted: boolean;
};

export type LocalContactFeedback = Readonly<BrowserPoint & { area: AnimaBodyArea }>;

export type AvatarInteractionCallbacks = Readonly<{
  onInteraction: (event: AnimaInteractionEvent) => void;
  onGaze: (gaze: Readonly<{ x: number; y: number }>) => void;
  onFeedback: (feedback: LocalContactFeedback) => void;
}>;

export type AvatarInteractionControllerOptions = Readonly<{
  now?: () => number;
  setTimer?: (callback: () => void, delayMs: number) => TimerHandle;
  clearTimer?: (handle: TimerHandle) => void;
  gestureFactory?: GestureFactory;
}>;

const DEFAULT_GESTURE_CONFIG: UserGestureConfig = {
  drag: {
    filterTaps: true,
    tapsThreshold: STROKE_DISTANCE_PX,
    threshold: 0,
    pointer: {
      touch: false,
      capture: true,
      buttons: 1,
      keys: false,
    },
  },
  move: { mouseOnly: true },
};

export class AvatarInteractionController {
  private gesture: GestureHandle | null = null;
  private active: ActiveContact | null = null;
  private hoveredArea: AnimaBodyArea | null = null;
  private pressTimer: TimerHandle | null = null;
  private sequence = 0;
  private readonly now: () => number;
  private readonly setTimer: (callback: () => void, delayMs: number) => TimerHandle;
  private readonly clearTimer: (handle: TimerHandle) => void;
  private readonly gestureFactory: GestureFactory;

  constructor(
    private readonly host: HTMLElement,
    private readonly hitTestPort: AvatarHitTestPort,
    private readonly callbacks: AvatarInteractionCallbacks,
    options: AvatarInteractionControllerOptions = {},
  ) {
    this.now = options.now ?? (() => performance.now());
    this.setTimer = options.setTimer ?? ((callback, delayMs) => setTimeout(callback, delayMs));
    this.clearTimer = options.clearTimer ?? ((handle) => clearTimeout(handle));
    this.gestureFactory = options.gestureFactory ?? ((target, handlers, config) => (
      new Gesture(target, handlers, config)
    ));
  }

  start(): void {
    const wasStarted = this.gesture !== null;
    this.gesture?.destroy();
    this.gesture = null;
    this.clearPressTimer();
    this.active = null;
    this.hoveredArea = null;
    if (wasStarted) this.callbacks.onGaze({ x: 0, y: 0 });
    this.gesture = this.gestureFactory(this.host, this.createHandlers(), DEFAULT_GESTURE_CONFIG);
  }

  primaryContact(): void {
    const now = this.now();
    this.emit({
      area: "face",
      gesture: "tap",
      pointerType: "keyboard",
      durationMs: 0,
      intensity: 0.55,
      occurredAtMs: now,
    });
  }

  destroy(): void {
    this.gesture?.destroy();
    this.gesture = null;
    this.clearPressTimer();
    this.active = null;
    this.hoveredArea = null;
    this.callbacks.onGaze({ x: 0, y: 0 });
  }

  private createHandlers(): GestureHandlers {
    return {
      onPointerDown: ({ event }) => {
        if (!(event instanceof PointerEvent)) return;
        if (!event.isPrimary || (event.pointerType === "mouse" && event.button !== 0)) return;
        this.beginContact(
          { clientX: event.clientX, clientY: event.clientY },
          event.pointerId,
          pointerTypeOf(event),
        );
      },
      onPointerCancel: () => this.cancelContact(),
      onLostPointerCapture: () => this.cancelContact(),
      onPointerLeave: () => {
        if (!this.active) this.callbacks.onGaze({ x: 0, y: 0 });
      },
      onMove: ({ xy }) => this.updateGaze({ clientX: xy[0], clientY: xy[1] }),
      onHover: ({ hovering, xy, event }) => {
        if (hovering) {
          const point = { clientX: xy[0], clientY: xy[1] };
          const area = this.hitTestPort.hitTest(point);
          this.hoveredArea = area;
          if (area) this.emit({
            area,
            gesture: "hover-enter",
            pointerType: pointerTypeOf(event),
            durationMs: 0,
            intensity: 0.2,
            occurredAtMs: this.now(),
          });
          return;
        }
        if (this.hoveredArea) this.emit({
          area: this.hoveredArea,
          gesture: "hover-leave",
          pointerType: pointerTypeOf(event),
          durationMs: 0,
          intensity: 0,
          occurredAtMs: this.now(),
        });
        this.hoveredArea = null;
        if (!this.active) this.callbacks.onGaze({ x: 0, y: 0 });
      },
      onDrag: (state) => {
        const point = { clientX: state.xy[0], clientY: state.xy[1] };
        this.updateGaze(point);
        const active = this.active;
        if (!active) return;
        active.lastPoint = point;
        const now = this.now();
        const distance = Math.hypot(state.movement[0], state.movement[1]);
        if (state.active && distance >= STROKE_DISTANCE_PX && now - active.lastStrokeAtMs >= STROKE_INTERVAL_MS) {
          this.clearPressTimer();
          active.area = this.hitTestPort.hitTest(point) ?? active.area;
          active.lastStrokeAtMs = now;
          active.strokeEmitted = true;
          const magnitude = Math.hypot(state.direction[0], state.direction[1]) || 1;
          this.emit({
            area: active.area,
            gesture: "stroke",
            pointerType: active.pointerType,
            durationMs: Math.max(0, now - active.startedAtMs),
            intensity: clamp(0.35 + distance / 90 + Math.hypot(state.velocity[0], state.velocity[1]) * 0.18, 0, 1),
            direction: {
              x: state.direction[0] / magnitude,
              y: state.direction[1] / magnitude,
            },
            occurredAtMs: now,
          });
          this.callbacks.onFeedback({ ...point, area: active.area });
        }

        if (state.last) {
          if (state.canceled) this.cancelContact();
          else this.finishContact(state.tap);
        }
      },
    };
  }

  private beginContact(point: BrowserPoint, pointerId: number, pointerType: ContactPointer): void {
    const area = this.hitTestPort.hitTest(point);
    if (!area) return;
    this.cancelContact();
    const now = this.now();
    this.active = {
      pointerId,
      pointerType,
      area,
      startedAtMs: now,
      lastStrokeAtMs: now - STROKE_INTERVAL_MS,
      lastPoint: point,
      pressEmitted: false,
      strokeEmitted: false,
    };
    this.emit({
      area,
      gesture: "contact",
      pointerType,
      durationMs: 0,
      intensity: 0.35,
      occurredAtMs: now,
    });
    this.callbacks.onFeedback({ ...point, area });
    this.pressTimer = this.setTimer(() => this.emitPress(), PRESS_DELAY_MS);
  }

  private emitPress(): void {
    this.pressTimer = null;
    const active = this.active;
    if (!active || active.strokeEmitted) return;
    const now = this.now();
    active.pressEmitted = true;
    this.emit({
      area: active.area,
      gesture: "press",
      pointerType: active.pointerType,
      durationMs: Math.max(PRESS_DELAY_MS, now - active.startedAtMs),
      intensity: 0.72,
      occurredAtMs: now,
    });
    this.callbacks.onFeedback({ ...active.lastPoint, area: active.area });
  }

  private finishContact(tap: boolean): void {
    const active = this.active;
    if (!active) return;
    this.clearPressTimer();
    const now = this.now();
    const durationMs = Math.max(0, now - active.startedAtMs);
    if (tap && !active.pressEmitted && !active.strokeEmitted) {
      this.emit({
        area: active.area,
        gesture: "tap",
        pointerType: active.pointerType,
        durationMs,
        intensity: 0.62,
        occurredAtMs: now,
      });
    } else if (durationMs >= PRESS_DELAY_MS && !active.pressEmitted && !active.strokeEmitted) {
      this.emit({
        area: active.area,
        gesture: "press",
        pointerType: active.pointerType,
        durationMs,
        intensity: 0.72,
        occurredAtMs: now,
      });
    }
    this.emit({
      area: active.area,
      gesture: "release",
      pointerType: active.pointerType,
      durationMs,
      intensity: 0,
      occurredAtMs: now,
    });
    this.active = null;
  }

  private cancelContact(): void {
    this.clearPressTimer();
    this.active = null;
  }

  private clearPressTimer(): void {
    if (this.pressTimer === null) return;
    this.clearTimer(this.pressTimer);
    this.pressTimer = null;
  }

  private updateGaze(point: BrowserPoint): void {
    const rect = this.host.getBoundingClientRect();
    this.callbacks.onGaze({
      x: clamp((point.clientX - rect.left) / Math.max(rect.width, 1) * 2 - 1, -1, 1),
      y: clamp(-((point.clientY - rect.top) / Math.max(rect.height, 1) * 2 - 1), -1, 1),
    });
  }

  private emit(event: Omit<AnimaInteractionEvent, "sequence">): void {
    this.callbacks.onInteraction({ ...event, sequence: ++this.sequence });
  }
}

function pointerTypeOf(event: Event): ContactPointer {
  if (typeof PointerEvent !== "undefined" && event instanceof PointerEvent) {
    if (event.pointerType === "touch" || event.pointerType === "pen") return event.pointerType;
  }
  return "mouse";
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export const INTERACTION_TIMING = {
  pressDelayMs: PRESS_DELAY_MS,
  strokeDistancePx: STROKE_DISTANCE_PX,
  strokeIntervalMs: STROKE_INTERVAL_MS,
} as const;
