const SESSION_STORAGE_KEY = "veyrasoul.anonymous-session.v1";
const SESSION_ID_PATTERN = /^anon_[A-Za-z0-9_-]{16,96}$/;

type SessionStorage = Pick<Storage, "getItem" | "setItem">;

export type SessionIdentityOptions = {
  storage?: SessionStorage | null;
  createUuid?: () => string;
};

/** 浏览器会话身份只用于恢复陪伴上下文，不作为认证凭据。 */
export function getOrCreateAnonymousSessionId(options: SessionIdentityOptions = {}): string {
  const storage = options.storage === undefined ? readBrowserStorage() : options.storage;
  const stored = readStoredSessionId(storage);
  if (stored) return stored;

  const uuid = (options.createUuid ?? createBrowserUuid)().replaceAll("-", "");
  const sessionId = `anon_${uuid}`;
  if (!SESSION_ID_PATTERN.test(sessionId)) {
    throw new Error("无法生成有效的匿名会话标识");
  }
  writeStoredSessionId(storage, sessionId);
  return sessionId;
}

function readBrowserStorage(): SessionStorage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function readStoredSessionId(storage: SessionStorage | null): string | null {
  if (!storage) return null;
  try {
    const sessionId = storage.getItem(SESSION_STORAGE_KEY);
    return sessionId && SESSION_ID_PATTERN.test(sessionId) ? sessionId : null;
  } catch {
    return null;
  }
}

function writeStoredSessionId(storage: SessionStorage | null, sessionId: string): void {
  if (!storage) return;
  try {
    storage.setItem(SESSION_STORAGE_KEY, sessionId);
  } catch {
    // localStorage 在隐私模式或配额受限时可能不可写；当前页面仍可继续连接。
  }
}

function createBrowserUuid(): string {
  const browserCrypto = globalThis.crypto;
  if (typeof browserCrypto?.randomUUID === "function") return browserCrypto.randomUUID();
  if (typeof browserCrypto?.getRandomValues !== "function") {
    throw new Error("当前浏览器不支持安全随机数，无法创建匿名会话");
  }
  const bytes = browserCrypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}
