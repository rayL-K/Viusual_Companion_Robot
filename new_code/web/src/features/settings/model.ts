export type AnimaSettings = {
  personaMarkdown: string;
  maxReplyChars: number;
  replyDelayMs: number;
  voiceId: string;
  revision: number;
};

export const DEFAULT_ANIMA_SETTINGS: AnimaSettings = {
  personaMarkdown: "",
  maxReplyChars: 160,
  replyDelayMs: 0,
  voiceId: "default",
  revision: 0,
};

export function parseAnimaSettings(payload: Record<string, unknown>): AnimaSettings {
  return {
    personaMarkdown: requireString(payload.personaMarkdown, "personaMarkdown", 1, 20_000),
    maxReplyChars: requireInteger(payload.maxReplyChars, "maxReplyChars", 8, 2_000),
    replyDelayMs: requireInteger(payload.replyDelayMs, "replyDelayMs", 0, 10_000),
    voiceId: requireVoiceId(payload.voiceId),
    revision: requireInteger(payload.revision, "revision", 1, Number.MAX_SAFE_INTEGER),
  };
}

export function settingsPatch(settings: AnimaSettings): Record<string, unknown> {
  return {
    expectedRevision: settings.revision,
    personaMarkdown: settings.personaMarkdown.trim(),
    maxReplyChars: settings.maxReplyChars,
    replyDelayMs: settings.replyDelayMs,
    voiceId: settings.voiceId.trim(),
  };
}

function requireString(
  value: unknown,
  label: string,
  minimumLength: number,
  maximumLength: number,
): string {
  if (typeof value !== "string") throw new Error(`${label} 必须是字符串`);
  const normalized = value.replace(/\r\n?/g, "\n").trim();
  if (normalized.length < minimumLength || normalized.length > maximumLength) {
    throw new Error(`${label} 长度无效`);
  }
  return normalized;
}

function requireInteger(value: unknown, label: string, minimum: number, maximum: number): number {
  if (!Number.isSafeInteger(value) || Number(value) < minimum || Number(value) > maximum) {
    throw new Error(`${label} 超出范围`);
  }
  return Number(value);
}

function requireVoiceId(value: unknown): string {
  if (typeof value !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$/.test(value)) {
    throw new Error("voiceId 格式无效");
  }
  return value;
}
