import { signal } from "@preact/signals";

export type ConnectionPhase = "connecting" | "online" | "offline" | "error";
export type ReplyPhase = "idle" | "listening" | "thinking" | "speaking";

export const connectionPhase = signal<ConnectionPhase>("connecting");
export const replyPhase = signal<ReplyPhase>("idle");
export const assistantText = signal("我在这里。想聊什么，或者让我看看你身边的世界？");
export const transcript = signal("");
export const visualSummary = signal("等待视觉感知");
export const drawerOpen = signal(false);

export function phaseLabel(phase: ReplyPhase): string {
  return {
    idle: "陪伴中",
    listening: "正在听你说",
    thinking: "正在理解",
    speaking: "正在回应",
  }[phase];
}
