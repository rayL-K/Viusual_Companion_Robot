import {
  PROVIDER_CAPABILITIES,
  type ProviderCapability,
  type ProviderCatalog,
  type PublicProvider,
} from "../../core/api/toc";

export type AnimaProviderSelection = {
  alias: string;
  model: string;
  voice: string;
};

type AnimaProviderSelections = Record<ProviderCapability, AnimaProviderSelection>;

export type AnimaSettings = {
  personaMarkdown: string;
  maxReplyChars: number;
  replyDelayMs: number;
  voiceId: string;
  providers: AnimaProviderSelections;
  revision: number;
};

export const DEFAULT_ANIMA_SETTINGS: AnimaSettings = {
  personaMarkdown: "",
  maxReplyChars: 160,
  replyDelayMs: 0,
  voiceId: "default",
  providers: emptyProviderSelections(),
  revision: 0,
};

export function parseAnimaSettings(payload: Record<string, unknown>): AnimaSettings {
  const voiceId = requireVoiceId(payload.voiceId);
  const providers = parseProviderSelections(payload.providers);
  if (providers.tts.voice && providers.tts.voice !== voiceId) {
    throw new Error("voiceId 必须与 providers.tts.config.voice 一致");
  }
  if (!providers.tts.voice) providers.tts.voice = voiceId;
  return {
    personaMarkdown: requireString(payload.personaMarkdown, "personaMarkdown", 1, 20_000),
    maxReplyChars: requireInteger(payload.maxReplyChars, "maxReplyChars", 8, 2_000),
    replyDelayMs: requireInteger(payload.replyDelayMs, "replyDelayMs", 0, 10_000),
    voiceId,
    providers,
    revision: requireInteger(payload.revision, "revision", 1, Number.MAX_SAFE_INTEGER),
  };
}

export function settingsPatch(
  settings: AnimaSettings,
  options: { includeProviders?: boolean } = {},
): Record<string, unknown> {
  if (settings.providers.tts.voice && settings.providers.tts.voice !== settings.voiceId.trim()) {
    throw new Error("voiceId 必须与 providers.tts.config.voice 一致");
  }
  const patch: Record<string, unknown> = {
    expectedRevision: settings.revision,
    personaMarkdown: settings.personaMarkdown.trim(),
    maxReplyChars: settings.maxReplyChars,
    replyDelayMs: settings.replyDelayMs,
    voiceId: settings.voiceId.trim(),
  };
  if (options.includeProviders !== false) {
    patch.providers = Object.fromEntries(PROVIDER_CAPABILITIES.map((capability) => {
      const selection = settings.providers[capability];
      const config: Record<string, string> = {};
      if (selection.model) config.model = selection.model;
      if (capability === "tts" && selection.voice) config.voice = selection.voice;
      return [capability, { provider: selection.alias, config }];
    }));
  }
  return patch;
}

export function catalogProviders(
  catalog: ProviderCatalog,
  capability: ProviderCapability,
): readonly PublicProvider[] {
  return catalog.items.filter((item) => item.capability === capability);
}

export function selectionFromCatalog(
  current: AnimaProviderSelection,
  provider: PublicProvider,
): AnimaProviderSelection {
  return {
    alias: provider.alias,
    model: provider.models.includes(current.model) ? current.model : (provider.models[0] ?? ""),
    voice: provider.voices.includes(current.voice) ? current.voice : (provider.voices[0] ?? ""),
  };
}

export function validateProviderSelections(
  settings: AnimaSettings,
  catalog: ProviderCatalog,
): string | null {
  for (const capability of PROVIDER_CAPABILITIES) {
    const selection = settings.providers[capability];
    if (
      selection.alias === "disabled"
      && (capability === "asr" || capability === "vision")
      && !selection.model
      && !selection.voice
    ) {
      continue;
    }
    const provider = catalog.items.find(
      (item) => item.capability === capability && item.alias === selection.alias,
    );
    if (!provider) return `${capability.toUpperCase()} 服务已不可用，请重新选择。`;
    if (provider.models.length > 0 && !provider.models.includes(selection.model)) {
      return `${capability.toUpperCase()} 模型已不可用，请重新选择。`;
    }
    if (
      capability === "tts"
      && provider.voices.length > 0
      && !provider.voices.includes(selection.voice)
    ) {
      return "TTS 音色已不可用，请重新选择。";
    }
  }
  return null;
}

function parseProviderSelections(value: unknown): AnimaProviderSelections {
  if (!isObject(value)) throw new Error("providers 必须是对象");
  const unknown = Object.keys(value).filter(
    (key) => !PROVIDER_CAPABILITIES.includes(key as ProviderCapability),
  );
  if (unknown.length > 0) throw new Error("providers 包含未知模态");
  return Object.fromEntries(PROVIDER_CAPABILITIES.map((capability) => [
    capability,
    parseProviderSelection(value[capability], capability),
  ])) as AnimaProviderSelections;
}

function parseProviderSelection(
  value: unknown,
  capability: ProviderCapability,
): AnimaProviderSelection {
  if (!isObject(value)) throw new Error(`${capability} provider 必须是对象`);
  const unknownSelection = Object.keys(value).filter(
    (key) => key !== "provider" && key !== "locality" && key !== "config",
  );
  if (unknownSelection.length > 0) throw new Error(`${capability} provider 包含未知字段`);
  const alias = requireProviderValue(value.provider, `${capability}.provider`);
  if (!isObject(value.config)) throw new Error(`${capability}.config 必须是对象`);
  const unknownConfig = Object.keys(value.config).filter(
    (key) => key !== "model" && (capability !== "tts" || key !== "voice"),
  );
  if (unknownConfig.length > 0) throw new Error(`${capability}.config 包含未知字段`);
  return {
    alias,
    model: optionalProviderValue(value.config.model, `${capability}.model`),
    voice: capability === "tts"
      ? optionalProviderValue(value.config.voice, "tts.voice")
      : "",
  };
}

function emptyProviderSelections(): AnimaProviderSelections {
  return Object.fromEntries(PROVIDER_CAPABILITIES.map((capability) => [
    capability,
    { alias: "", model: "", voice: "" },
  ])) as AnimaProviderSelections;
}

function optionalProviderValue(value: unknown, label: string): string {
  if (value === undefined) return "";
  return requireProviderValue(value, label);
}

function requireProviderValue(value: unknown, label: string): string {
  if (
    typeof value !== "string"
    || !value.trim()
    || value.length > 160
    || value.includes("\0")
  ) {
    throw new Error(`${label} 格式无效`);
  }
  return value.trim();
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

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
