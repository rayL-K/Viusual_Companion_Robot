import { signal } from "@preact/signals";
import type { AvatarIntentPayload } from "../realtime/protocol";

export type ConnectionPhase = "connecting" | "online" | "offline" | "error";
export type ReplyPhase = "idle" | "listening" | "thinking" | "speaking";

export type AvatarIntentState = AvatarIntentPayload & {
  sessionId: string;
  generation: number;
  seq: number;
};

export type AvatarIntentUpdate = {
  sessionId: string;
  generation: number;
  seq: number;
  payload: AvatarIntentPayload;
};

const INITIAL_AVATAR_INTENT: AvatarIntentState = {
  sessionId: "",
  generation: -1,
  seq: -1,
  phase: "idle",
  expression: "soft",
  motion: "idle",
  gazeStrength: 0.68,
  bodyTension: 0.22,
  smile: 0.52,
  eyeOpen: 0.82,
  speechRate: 1,
  speechPitch: 1,
  affect: {
    valence: 0.12,
    arousal: 0.15,
    dominance: 0,
    affinity: 0.25,
    trust: 0.2,
  },
};

export const connectionPhase = signal<ConnectionPhase>("connecting");
export const replyPhase = signal<ReplyPhase>("idle");
export const assistantText = signal("我在这里。想聊什么，或者让我看看你身边的世界？");
export const transcript = signal("");
export const visualSummary = signal("等待视觉感知");
export const speechAudioRms = signal(0);
export const avatarIntent = signal<AvatarIntentState>(INITIAL_AVATAR_INTENT);
export const drawerOpen = signal(false);

export function reduceAvatarIntent(
  current: AvatarIntentState,
  update: AvatarIntentUpdate,
): AvatarIntentState {
  if (update.sessionId !== current.sessionId) {
    return { ...update.payload, sessionId: update.sessionId, generation: update.generation, seq: update.seq };
  }
  const isOlderGeneration = update.generation < current.generation;
  const isStaleSequence = update.generation === current.generation && update.seq <= current.seq;
  if (isOlderGeneration || isStaleSequence) return current;
  return {
    ...update.payload,
    sessionId: update.sessionId,
    generation: update.generation,
    seq: update.seq,
  };
}

export function applyAvatarIntent(update: AvatarIntentUpdate): boolean {
  const next = reduceAvatarIntent(avatarIntent.value, update);
  if (next === avatarIntent.value) return false;
  avatarIntent.value = next;
  return true;
}

export function phaseLabel(phase: ReplyPhase): string {
  return {
    idle: "陪伴中",
    listening: "正在听你说",
    thinking: "正在理解",
    speaking: "正在回应",
  }[phase];
}
