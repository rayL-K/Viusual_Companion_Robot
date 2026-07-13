import { describe, expect, it } from "vitest";

import { parseAnimaSettings, settingsPatch } from "./model";

describe("Anima settings protocol", () => {
  it("parses a complete server profile", () => {
    expect(parseAnimaSettings({
      personaMarkdown: "# 草莓兔兔\r\n温柔但不造作。",
      maxReplyChars: 120,
      replyDelayMs: 0,
      voiceId: "local:zh-en-1",
      revision: 3,
    })).toEqual({
      personaMarkdown: "# 草莓兔兔\n温柔但不造作。",
      maxReplyChars: 120,
      replyDelayMs: 0,
      voiceId: "local:zh-en-1",
      revision: 3,
    });
  });

  it("rejects partial or unsafe wire values", () => {
    expect(() => parseAnimaSettings({
      personaMarkdown: "x",
      maxReplyChars: 7,
      replyDelayMs: 0,
      voiceId: "../voice",
      revision: 1,
    })).toThrow();
  });

  it("does not send server-owned revision", () => {
    const profile = parseAnimaSettings({
      personaMarkdown: "  自然、真诚。  ",
      maxReplyChars: 80,
      replyDelayMs: 60,
      voiceId: "default",
      revision: 2,
    });
    expect(settingsPatch(profile)).toEqual({
      expectedRevision: 2,
      personaMarkdown: "自然、真诚。",
      maxReplyChars: 80,
      replyDelayMs: 60,
      voiceId: "default",
    });
  });
});
