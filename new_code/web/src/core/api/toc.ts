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

export const PROVIDER_CAPABILITIES = ["llm", "asr", "tts", "vision"] as const;
export type ProviderCapability = typeof PROVIDER_CAPABILITIES[number];
type ProviderLocality = "local" | "cloud";

export type PublicProvider = {
  capability: ProviderCapability;
  alias: string;
  locality: ProviderLocality;
  models: readonly string[];
  voices: readonly string[];
  streaming: boolean;
};

export type ProviderCatalog = {
  revision: number;
  items: readonly PublicProvider[];
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
  constructor(
    private readonly fetcher: FetchLike = globalThis.fetch.bind(globalThis),
  ) {}

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

  async providerCatalog(): Promise<ProviderCatalog> {
    const payload = await this.request("/v2/providers");
    if (!isObject(payload) || !Array.isArray(payload.items)) {
      throw new TocApiError("invalid-response", "服务能力目录响应格式无效");
    }
    const revision = requiredRevision(payload.revision);
    const seen = new Set<string>();
    const items = payload.items.map((item) => {
      const provider = parseProvider(item);
      const identity = `${provider.capability}:${provider.alias}`;
      if (seen.has(identity)) {
        throw new TocApiError("invalid-response", "服务能力目录包含重复别名");
      }
      seen.add(identity);
      return provider;
    });
    return { revision, items };
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

function parseProvider(value: unknown): PublicProvider {
  if (!isObject(value)) {
    throw new TocApiError("invalid-response", "服务能力条目格式无效");
  }
  const unknown = Object.keys(value).filter(
    (key) => !["capability", "alias", "locality", "models", "voices", "streaming"].includes(key),
  );
  if (unknown.length > 0) {
    throw new TocApiError("invalid-response", "服务能力条目包含未公开字段");
  }
  if (!PROVIDER_CAPABILITIES.includes(value.capability as ProviderCapability)) {
    throw new TocApiError("invalid-response", "服务能力类型无效");
  }
  if (value.locality !== "local" && value.locality !== "cloud") {
    throw new TocApiError("invalid-response", "服务能力位置无效");
  }
  if (typeof value.streaming !== "boolean") {
    throw new TocApiError("invalid-response", "服务流式能力无效");
  }
  return {
    capability: value.capability as ProviderCapability,
    alias: requiredProviderValue(value.alias, "服务别名"),
    locality: value.locality,
    models: parseProviderValues(value.models, "模型", 160),
    voices: parseProviderValues(value.voices, "音色", 80),
    streaming: value.streaming,
  };
}

function parseProviderValues(
  value: unknown,
  label: string,
  maximumLength: number,
): readonly string[] {
  if (!Array.isArray(value) || value.length > 64) {
    throw new TocApiError("invalid-response", `${label}目录无效`);
  }
  const values = value.map((item) => requiredProviderValue(item, label, maximumLength));
  if (new Set(values).size !== values.length) {
    throw new TocApiError("invalid-response", `${label}目录包含重复值`);
  }
  return values;
}

function requiredProviderValue(
  value: unknown,
  label: string,
  maximumLength = 160,
): string {
  if (
    typeof value !== "string"
    || !value.trim()
    || value.length > maximumLength
    || value.includes("\0")
  ) {
    throw new TocApiError("invalid-response", `${label}无效`);
  }
  return value.trim();
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
