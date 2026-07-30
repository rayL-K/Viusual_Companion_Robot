export type TocUser = {
  id: string;
  displayName: string;
  revision: number;
};

export type TocAnima = {
  id: string;
  displayName: string;
  state: "active" | "deleting";
  revision: number;
};

export type AccessBootstrap =
  | { mode: "toc"; user: TocUser; animas: TocAnima[] }
  | { mode: "anonymous"; anima: TocAnima }
  | { mode: "unavailable" };

export class TocApiError extends Error {
  constructor(
    readonly kind: "unauthenticated" | "network" | "invalid-response" | "request",
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "TocApiError";
  }
}

type FetchLike = typeof fetch;

export class TocApiClient {
  constructor(private readonly fetcher: FetchLike = fetch) {}

  async me(): Promise<TocUser> {
    return parseUser(await this.request("/v2/me"));
  }

  async capabilities(): Promise<{
    tocEnabled: boolean;
    anonymousRealtimeEnabled: boolean;
  }> {
    const payload = await this.request("/v2/health");
    if (
      !isObject(payload)
      || typeof payload.tocEnabled !== "boolean"
      || typeof payload.anonymousRealtimeEnabled !== "boolean"
    ) {
      throw new TocApiError("invalid-response", "服务访问能力响应格式无效");
    }
    return {
      tocEnabled: payload.tocEnabled,
      anonymousRealtimeEnabled: payload.anonymousRealtimeEnabled,
    };
  }

  async animas(): Promise<TocAnima[]> {
    const payload = await this.request("/v2/animas");
    if (!isObject(payload) || !Array.isArray(payload.items)) {
      throw new TocApiError("invalid-response", "Anima 列表响应格式无效");
    }
    return payload.items.map(parseAnima);
  }

  async mutate(path: string, init: RequestInit): Promise<unknown> {
    const csrf = readCookie("__Host-anima_csrf");
    if (!csrf) {
      throw new TocApiError("request", "安全会话缺少 CSRF 凭据");
    }
    return this.request(path, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...init.headers,
        "X-CSRF-Token": csrf,
      },
    });
  }

  private async request(path: string, init: RequestInit = {}): Promise<unknown> {
    let response: Response;
    try {
      response = await this.fetcher(path, { ...init, credentials: "include" });
    } catch {
      throw new TocApiError("network", "暂时无法连接 Anima 服务");
    }
    if (response.status === 401) {
      throw new TocApiError("unauthenticated", "需要登录后继续", 401);
    }
    if (!response.ok) {
      throw new TocApiError("request", `请求暂时失败（${response.status}）`, response.status);
    }
    try {
      return await response.json();
    } catch {
      throw new TocApiError("invalid-response", "服务响应格式无效");
    }
  }
}

export async function loadTocSession(
  api: TocApiClient,
): Promise<{ user: TocUser; animas: TocAnima[] }> {
  const user = await api.me();
  const animas = (await api.animas()).filter((anima) => anima.state === "active");
  return { user, animas };
}

export async function bootstrapAccess(api: TocApiClient): Promise<AccessBootstrap> {
  const capabilities = await api.capabilities();
  if (capabilities.tocEnabled) {
    return { mode: "toc", ...(await loadTocSession(api)) };
  }
  if (capabilities.anonymousRealtimeEnabled) {
    return {
      mode: "anonymous",
      anima: {
        id: "default",
        displayName: "Anima",
        state: "active",
        revision: 1,
      },
    };
  }
  return { mode: "unavailable" };
}

export function readCookie(name: string, cookie = document.cookie): string | null {
  const prefix = `${encodeURIComponent(name)}=`;
  for (const part of cookie.split(";")) {
    const normalized = part.trim();
    if (!normalized.startsWith(prefix)) continue;
    try {
      return decodeURIComponent(normalized.slice(prefix.length));
    } catch {
      return null;
    }
  }
  return null;
}

function parseUser(value: unknown): TocUser {
  if (!isObject(value)) throw new TocApiError("invalid-response", "用户响应格式无效");
  return {
    id: requiredId(value.id, "用户"),
    displayName: requiredText(value.displayName, "用户名称"),
    revision: requiredRevision(value.revision),
  };
}

function parseAnima(value: unknown): TocAnima {
  if (!isObject(value)) throw new TocApiError("invalid-response", "Anima 响应格式无效");
  if (value.state !== "active" && value.state !== "deleting") {
    throw new TocApiError("invalid-response", "Anima 状态无效");
  }
  return {
    id: requiredId(value.id, "Anima"),
    displayName: requiredText(value.displayName, "Anima 名称"),
    state: value.state,
    revision: requiredRevision(value.revision),
  };
}

function requiredId(value: unknown, label: string): string {
  if (typeof value !== "string" || !/^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$/.test(value)) {
    throw new TocApiError("invalid-response", `${label} ID 无效`);
  }
  return value;
}

function requiredText(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new TocApiError("invalid-response", `${label}无效`);
  }
  return value;
}

function requiredRevision(value: unknown): number {
  if (!Number.isSafeInteger(value) || Number(value) < 1) {
    throw new TocApiError("invalid-response", "revision 无效");
  }
  return Number(value);
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
