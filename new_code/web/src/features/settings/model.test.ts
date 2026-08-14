import { describe, expect, it } from "vitest";

import {
  parseAnimaSettings,
  selectionFromCatalog,
  settingsPatch,
  validateProviderSelections,
} from "./model";

const providers = {
  llm: { provider: "dialogue", locality: "cloud", config: { model: "chat-v2" } },
  asr: { provider: "hearing", locality: "cloud", config: { model: "asr-v1" } },
  tts: {
    provider: "voice",
    locality: "cloud",
    config: { model: "tts-v1", voice: "warm.zh" },
  },
  vision: { provider: "sight", locality: "cloud", config: { model: "vlm-v1" } },
};

const catalog = {
  revision: 1,
  items: [
    { capability: "llm" as const, alias: "dialogue", locality: "cloud" as const, models: ["chat-v2"], voices: [], streaming: true },
    { capability: "asr" as const, alias: "hearing", locality: "cloud" as const, models: ["asr-v1"], voices: [], streaming: true },
    { capability: "tts" as const, alias: "voice", locality: "cloud" as const, models: ["tts-v1"], voices: ["warm.zh"], streaming: true },
    { capability: "vision" as const, alias: "sight", locality: "cloud" as const, models: ["vlm-v1"], voices: [], streaming: false },
  ],
};

describe("Anima settings protocol", () => {
  it("parses a complete server profile", () => {
    expect(parseAnimaSettings({
      personaMarkdown: "# 草莓兔兔\r\n温柔但不造作。",
      maxReplyChars: 120,
      replyDelayMs: 0,
      voiceId: "warm.zh",
      providers,
      revision: 3,
    })).toEqual({
      personaMarkdown: "# 草莓兔兔\n温柔但不造作。",
      maxReplyChars: 120,
      replyDelayMs: 0,
      voiceId: "warm.zh",
      providers: {
        llm: { alias: "dialogue", model: "chat-v2", voice: "" },
        asr: { alias: "hearing", model: "asr-v1", voice: "" },
        tts: { alias: "voice", model: "tts-v1", voice: "warm.zh" },
        vision: { alias: "sight", model: "vlm-v1", voice: "" },
      },
      revision: 3,
    });
  });

  it("rejects partial or unsafe wire values", () => {
    expect(() => parseAnimaSettings({
      personaMarkdown: "x",
      maxReplyChars: 7,
      replyDelayMs: 0,
      voiceId: "../voice",
      providers,
      revision: 1,
    })).toThrow();
  });

  it("does not send server-owned revision", () => {
    const profile = parseAnimaSettings({
      personaMarkdown: "  自然、真诚。  ",
      maxReplyChars: 80,
      replyDelayMs: 60,
      voiceId: "warm.zh",
      providers,
      revision: 2,
    });
    expect(settingsPatch(profile)).toEqual({
      expectedRevision: 2,
      personaMarkdown: "自然、真诚。",
      maxReplyChars: 80,
      replyDelayMs: 60,
      voiceId: "warm.zh",
      providers: {
        llm: { provider: "dialogue", config: { model: "chat-v2" } },
        asr: { provider: "hearing", config: { model: "asr-v1" } },
        tts: { provider: "voice", config: { model: "tts-v1", voice: "warm.zh" } },
        vision: { provider: "sight", config: { model: "vlm-v1" } },
      },
    });
  });

  it("never accepts or emits provider transport secrets", () => {
    expect(() => parseAnimaSettings({
      personaMarkdown: "自然、真诚。",
      maxReplyChars: 80,
      replyDelayMs: 0,
      voiceId: "default",
      providers: {
        ...providers,
        llm: {
          provider: "dialogue",
          config: { model: "chat-v2", baseURL: "https://untrusted.example" },
        },
      },
      revision: 1,
    })).toThrow(/未知字段/);
  });

  it("rejects conflicting legacy and provider TTS voice fields", () => {
    expect(() => parseAnimaSettings({
      personaMarkdown: "自然、真诚。",
      maxReplyChars: 80,
      replyDelayMs: 0,
      voiceId: "default",
      providers,
      revision: 1,
    })).toThrow(/必须与/);

    const valid = parseAnimaSettings({
      personaMarkdown: "自然、真诚。",
      maxReplyChars: 80,
      replyDelayMs: 0,
      voiceId: "warm.zh",
      providers,
      revision: 1,
    });
    expect(() => settingsPatch({ ...valid, voiceId: "default" })).toThrow(/必须与/);
  });

  it("validates selections against only the server catalog", () => {
    const settings = parseAnimaSettings({
      personaMarkdown: "自然、真诚。",
      maxReplyChars: 80,
      replyDelayMs: 0,
      voiceId: "warm.zh",
      providers,
      revision: 1,
    });
    expect(validateProviderSelections(settings, catalog)).toBeNull();
    expect(validateProviderSelections({
      ...settings,
      providers: {
        ...settings.providers,
        llm: { alias: "not-public", model: "chat-v2", voice: "" },
      },
    }, catalog)).toMatch(/不可用/);
  });

  it("retains only model and voice choices supported by a selected catalog entry", () => {
    expect(selectionFromCatalog(
      { alias: "old", model: "old-model", voice: "old-voice" },
      catalog.items[2]!,
    )).toEqual({ alias: "voice", model: "tts-v1", voice: "warm.zh" });
  });

  it("allows ASR and vision to be explicitly disabled without a catalog item", () => {
    const settings = parseAnimaSettings({
      personaMarkdown: "自然、真诚。",
      maxReplyChars: 80,
      replyDelayMs: 0,
      voiceId: "warm.zh",
      providers: {
        ...providers,
        asr: { provider: "disabled", locality: "disabled", config: {} },
        vision: { provider: "disabled", locality: "disabled", config: {} },
      },
      revision: 4,
    });

    expect(validateProviderSelections(settings, catalog)).toBeNull();
    expect(settingsPatch(settings).providers).toMatchObject({
      asr: { provider: "disabled", config: {} },
      vision: { provider: "disabled", config: {} },
    });
  });
});
