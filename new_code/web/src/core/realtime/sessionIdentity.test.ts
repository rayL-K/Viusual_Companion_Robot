import { describe, expect, it } from "vitest";

import { getOrCreateAnonymousSessionId } from "./sessionIdentity";

class MemoryStorage {
  private readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

describe("anonymous session identity", () => {
  it("persists and reuses one anonymous session id", () => {
    const storage = new MemoryStorage();
    const first = getOrCreateAnonymousSessionId({
      storage,
      createUuid: () => "12345678-1234-1234-1234-123456789abc",
    });
    const second = getOrCreateAnonymousSessionId({
      storage,
      createUuid: () => "ffffffff-ffff-ffff-ffff-ffffffffffff",
    });

    expect(first).toBe("anon_12345678123412341234123456789abc");
    expect(second).toBe(first);
  });

  it("replaces malformed stored data instead of sending it to the gateway", () => {
    const storage = new MemoryStorage();
    storage.setItem("veyrasoul.anonymous-session.v1", "../../invalid");

    expect(getOrCreateAnonymousSessionId({
      storage,
      createUuid: () => "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    })).toBe("anon_aaaaaaaabbbbccccddddeeeeeeeeeeee");
  });

  it("keeps the current page usable when browser storage is unavailable", () => {
    const unavailableStorage = {
      getItem: () => { throw new Error("storage denied"); },
      setItem: () => { throw new Error("storage denied"); },
    };

    expect(getOrCreateAnonymousSessionId({
      storage: unavailableStorage,
      createUuid: () => "11111111-2222-3333-4444-555555555555",
    })).toBe("anon_11111111222233334444555555555555");
  });
});
