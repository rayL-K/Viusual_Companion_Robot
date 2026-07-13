import type { AvatarRenderIntent } from "./SignalMixer";

export type AvatarCapabilities = {
  expressions: ReadonlySet<string>;
  motions: ReadonlySet<string>;
};

export type AvatarActionEnvelope = AvatarRenderIntent & {
  sessionId?: string;
  generation?: number;
  seq?: number;
};

export type AvatarOverlayExecutor = {
  setExpression: (name: string) => boolean | Promise<boolean>;
  resetExpression: () => void;
  startMotion: (group: string, priority: number) => boolean | Promise<boolean>;
  stopMotions: () => void;
};

export type AvatarActionSubmitResult = {
  accepted: boolean;
  expression: ActionDecision;
  motion: ActionDecision;
};

export type ActionDecision = "scheduled" | "unsupported" | "cooldown" | "blocked" | "none";

type ActionKind = "expression" | "motion";

type ActionProfile = {
  asset: string;
  priority: number;
  durationMs: number;
  cooldownMs: number;
};

type ActiveAction = ActionProfile & {
  token: number;
  timer: ReturnType<typeof setTimeout>;
};

type ActionOrder = {
  sessionId: string;
  generation: number;
  seq: number;
};

const EXPRESSION_ALIASES: Readonly<Record<string, string | undefined>> = {
  soft: undefined,
  attentive: "question",
  thoughtful: "question",
  warm: "blush",
  delighted: "heart",
  concerned: "anxious",
};

const MOTION_ALIASES: Readonly<Record<string, string | undefined>> = {
  idle: "scene1",
  listen: "governor",
  ponder: "scene1",
  talk: "captain",
  excited: "admiral",
  comfort: "governor",
};

const EXPRESSION_PROFILES: Readonly<Record<string, Omit<ActionProfile, "asset">>> = {
  question: { priority: 1, durationMs: 1_600, cooldownMs: 2_400 },
  blush: { priority: 1, durationMs: 2_100, cooldownMs: 3_200 },
  flowers: { priority: 2, durationMs: 2_300, cooldownMs: 4_000 },
  heart: { priority: 2, durationMs: 2_400, cooldownMs: 4_200 },
  finger_heart: { priority: 2, durationMs: 2_400, cooldownMs: 4_200 },
  anxious: { priority: 2, durationMs: 2_000, cooldownMs: 2_800 },
  angry: { priority: 3, durationMs: 2_100, cooldownMs: 3_200 },
  cry: { priority: 3, durationMs: 2_400, cooldownMs: 4_000 },
};

const MOTION_PROFILES: Readonly<Record<string, Omit<ActionProfile, "asset">>> = {
  scene1: { priority: 1, durationMs: 2_600, cooldownMs: 8_000 },
  governor: { priority: 1, durationMs: 2_600, cooldownMs: 3_200 },
  captain: { priority: 2, durationMs: 2_600, cooldownMs: 3_000 },
  admiral: { priority: 3, durationMs: 2_600, cooldownMs: 3_500 },
};

const DEFAULT_PROFILE: Omit<ActionProfile, "asset"> = {
  priority: 2,
  durationMs: 2_000,
  cooldownMs: 3_000,
};

export const STRAWBERRY_RABBIT_CAPABILITIES: AvatarCapabilities = {
  expressions: new Set([
    "heart", "finger_heart", "gaming", "dark_mode", "shadow_face", "blush", "flowers",
    "microphone", "plus", "cry", "sweat", "up", "angry", "twin_tail", "watermark",
    "tongue", "question", "down", "star_eyes", "right", "right_hand_up", "dizzy",
    "anxious", "left", "left_hand_up",
  ]),
  motions: new Set(["captain", "admiral", "governor", "scene1"]),
};

/**
 * Owns short-lived model assets only. Continuous pose, gaze and lip-sync remain
 * the responsibility of SignalMixer and are deliberately not written here.
 */
export class AvatarActionScheduler {
  private lastOrder: ActionOrder | null = null;
  private fallbackSeq = 0;
  private nextToken = 0;
  private lifecycle = 0;
  private destroyed = false;
  private active: Partial<Record<ActionKind, ActiveAction>> = {};
  private readonly cooldownUntil = new Map<string, number>();

  constructor(
    private readonly executor: AvatarOverlayExecutor,
    private readonly capabilities: AvatarCapabilities,
    private readonly now: () => number = Date.now,
  ) {}

  submit(intent: AvatarActionEnvelope): AvatarActionSubmitResult {
    if (this.destroyed) return rejectedResult();
    const order = this.readOrder(intent);
    const domainChanged = this.lastOrder === null
      || order.sessionId !== this.lastOrder.sessionId
      || order.generation > this.lastOrder.generation;
    if (!this.accepts(order)) return rejectedResult();

    if (domainChanged) {
      this.interruptAll();
      this.cooldownUntil.clear();
    }
    this.lastOrder = order;

    return {
      accepted: true,
      expression: this.schedule("expression", resolveProfile(
        intent.expression,
        EXPRESSION_ALIASES,
        EXPRESSION_PROFILES,
        this.capabilities.expressions,
      )),
      motion: this.schedule("motion", resolveProfile(
        intent.motion,
        MOTION_ALIASES,
        MOTION_PROFILES,
        this.capabilities.motions,
      )),
    };
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.lifecycle += 1;
    this.interruptAll();
    this.cooldownUntil.clear();
  }

  private accepts(order: ActionOrder): boolean {
    const previous = this.lastOrder;
    if (!previous || order.sessionId !== previous.sessionId) return true;
    if (order.generation < previous.generation) return false;
    return order.generation > previous.generation || order.seq > previous.seq;
  }

  private readOrder(intent: AvatarActionEnvelope): ActionOrder {
    if (Number.isSafeInteger(intent.generation) && Number.isSafeInteger(intent.seq)) {
      return {
        sessionId: intent.sessionId ?? "",
        generation: Number(intent.generation),
        seq: Number(intent.seq),
      };
    }
    this.fallbackSeq += 1;
    return { sessionId: "local", generation: 0, seq: this.fallbackSeq };
  }

  private schedule(kind: ActionKind, profile: ActionProfile | null | "unsupported"): ActionDecision {
    if (profile === null) return "none";
    if (profile === "unsupported") return "unsupported";
    const active = this.active[kind];
    if (active && profile.priority < active.priority) return "blocked";

    const cooldownKey = `${kind}:${profile.asset}`;
    if ((this.cooldownUntil.get(cooldownKey) ?? 0) > this.now()) return "cooldown";

    this.interrupt(kind);
    const token = ++this.nextToken;
    const lifecycle = this.lifecycle;
    const timer = setTimeout(() => this.finish(kind, token), profile.durationMs);
    this.active[kind] = { ...profile, token, timer };
    this.cooldownUntil.set(cooldownKey, this.now() + profile.cooldownMs);

    let start: boolean | Promise<boolean>;
    try {
      start = kind === "expression"
        ? this.executor.setExpression(profile.asset)
        : this.executor.startMotion(profile.asset, profile.priority);
    } catch {
      this.finish(kind, token);
      return "scheduled";
    }
    void Promise.resolve(start).then(
      (started) => {
        if (!started && this.lifecycle === lifecycle) this.finish(kind, token);
      },
      () => {
        if (this.lifecycle === lifecycle) this.finish(kind, token);
      },
    );
    return "scheduled";
  }

  private finish(kind: ActionKind, token: number): void {
    const current = this.active[kind];
    if (!current || current.token !== token) return;
    clearTimeout(current.timer);
    delete this.active[kind];
    this.reset(kind);
  }

  private interrupt(kind: ActionKind): void {
    const current = this.active[kind];
    if (current) {
      clearTimeout(current.timer);
      delete this.active[kind];
    }
    this.reset(kind);
  }

  private interruptAll(): void {
    this.interrupt("expression");
    this.interrupt("motion");
  }

  private reset(kind: ActionKind): void {
    if (kind === "expression") this.executor.resetExpression();
    else this.executor.stopMotions();
  }
}

function resolveProfile(
  requestedName: string,
  aliases: Readonly<Record<string, string | undefined>>,
  profiles: Readonly<Record<string, Omit<ActionProfile, "asset">>>,
  supported: ReadonlySet<string>,
): ActionProfile | null | "unsupported" {
  const normalized = requestedName.trim().toLowerCase();
  if (Object.prototype.hasOwnProperty.call(aliases, normalized) && aliases[normalized] === undefined) {
    return null;
  }
  const asset = aliases[normalized] ?? normalized;
  if (!supported.has(asset)) return "unsupported";
  return { asset, ...(profiles[asset] ?? DEFAULT_PROFILE) };
}

function rejectedResult(): AvatarActionSubmitResult {
  return { accepted: false, expression: "none", motion: "none" };
}
