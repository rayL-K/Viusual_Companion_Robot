const STATUS_ENDPOINT = "/v2/admission/status";
const VERIFY_ENDPOINT = "/v2/admission/verify";
const TURNSTILE_SCRIPT_URL =
  "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
const TURNSTILE_ACTION = "anima_admission";
const REQUEST_TIMEOUT_MS = 10_000;
const CHALLENGE_TIMEOUT_MS = 60_000;

type AdmissionStatus = Readonly<{
  required: boolean;
  ready: boolean;
  siteKey: string;
}>;

type TurnstileWidgetOptions = Readonly<{
  sitekey: string;
  action: string;
  execution: "execute";
  appearance: "interaction-only";
  theme: "auto";
  callback: (token: string) => void;
  "error-callback": (_code: string) => boolean;
  "expired-callback": () => void;
  "timeout-callback": () => void;
}>;

export type TurnstileApi = Readonly<{
  render: (container: HTMLElement, options: TurnstileWidgetOptions) => string;
  execute: (widgetId: string) => void;
  remove: (widgetId: string) => void;
}>;

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

type AdmissionOptions = Readonly<{
  fetcher?: typeof fetch;
  requestToken?: (siteKey: string) => Promise<string>;
  requestTimeoutMs?: number;
}>;

type ChallengeOptions = Readonly<{
  api?: TurnstileApi;
  document?: Document;
  timeoutMs?: number;
}>;

let turnstileScriptPromise: Promise<TurnstileApi> | null = null;

/**
 * Establishes the short-lived, HttpOnly admission cookie before a realtime
 * socket is opened. The challenge response is kept in memory only long enough
 * to exchange it with the same-origin gateway.
 */
export async function ensureRealtimeAdmission(options: AdmissionOptions = {}): Promise<void> {
  const fetcher = options.fetcher ?? globalThis.fetch;
  if (typeof fetcher !== "function") throw new Error("当前浏览器无法完成连接校验");
  const timeoutMs = options.requestTimeoutMs ?? REQUEST_TIMEOUT_MS;
  const statusResponse = await fetchWithTimeout(
    fetcher,
    STATUS_ENDPOINT,
    {
      method: "GET",
      credentials: "include",
      cache: "no-store",
      headers: { Accept: "application/json" },
    },
    timeoutMs,
  );
  if (!statusResponse.ok) throw new Error("连接校验状态暂不可用");
  const status = parseAdmissionStatus(await readJson(statusResponse));
  if (!status.required || status.ready) return;
  if (!status.siteKey) throw new Error("连接校验尚未配置完成");

  const token = await (options.requestToken ?? requestTurnstileToken)(status.siteKey);
  const verifyResponse = await fetchWithTimeout(
    fetcher,
    VERIFY_ENDPOINT,
    {
      method: "POST",
      credentials: "include",
      cache: "no-store",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ token }),
    },
    timeoutMs,
  );
  if (!verifyResponse.ok) throw new Error("连接校验未通过，请重试");
  const result = await readJson(verifyResponse);
  if (!isRecord(result) || result.ok !== true) throw new Error("连接校验未通过，请重试");
}

export async function requestTurnstileToken(
  siteKey: string,
  options: ChallengeOptions = {},
): Promise<string> {
  if (!siteKey) throw new Error("连接校验缺少站点标识");
  const documentLike = options.document ?? document;
  const api = options.api ?? await loadTurnstileScript();
  const container = documentLike.createElement("div");
  container.className = "turnstile-admission";
  container.setAttribute("role", "status");
  container.setAttribute("aria-label", "正在进行连接安全校验");
  documentLike.body.append(container);

  return new Promise<string>((resolve, reject) => {
    let widgetId: string | null = null;
    let removeAfterRender = false;
    let settled = false;
    const timer = setTimeout(
      () => finish(undefined, new Error("连接校验等待超时，请重试")),
      options.timeoutMs ?? CHALLENGE_TIMEOUT_MS,
    );

    const finish = (token?: string, error?: Error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (widgetId === null) {
        removeAfterRender = true;
      } else {
        safelyRemoveWidget(api, widgetId);
      }
      container.remove();
      if (error) reject(error);
      else if (token) resolve(token);
      else reject(new Error("连接校验未返回有效结果"));
    };

    try {
      widgetId = api.render(container, {
        sitekey: siteKey,
        action: TURNSTILE_ACTION,
        execution: "execute",
        appearance: "interaction-only",
        theme: "auto",
        callback: (token) => finish(token),
        "error-callback": () => {
          finish(undefined, new Error("连接校验暂时失败，请重试"));
          return true;
        },
        "expired-callback": () => finish(undefined, new Error("连接校验已过期，请重试")),
        "timeout-callback": () => finish(undefined, new Error("连接校验等待超时，请重试")),
      });
      if (!widgetId) throw new Error("连接校验组件启动失败");
      if (removeAfterRender) {
        safelyRemoveWidget(api, widgetId);
        return;
      }
      api.execute(widgetId);
    } catch (error) {
      finish(
        undefined,
        error instanceof Error ? error : new Error("连接校验组件启动失败"),
      );
    }
  });
}

async function loadTurnstileScript(): Promise<TurnstileApi> {
  if (window.turnstile) return window.turnstile;
  if (turnstileScriptPromise) return turnstileScriptPromise;

  const pending = new Promise<TurnstileApi>((resolve, reject) => {
    let script = document.querySelector<HTMLScriptElement>("script[data-anima-turnstile]");
    const created = script === null;
    if (!script) {
      script = document.createElement("script");
      script.src = TURNSTILE_SCRIPT_URL;
      script.async = true;
      script.defer = true;
      script.dataset.animaTurnstile = "true";
    }

    let settled = false;
    const cleanup = () => {
      clearInterval(poll);
      clearTimeout(timeout);
      script?.removeEventListener("error", onError);
    };
    const succeed = () => {
      if (settled || !window.turnstile) return;
      settled = true;
      cleanup();
      resolve(window.turnstile);
    };
    const onError = () => {
      if (settled) return;
      settled = true;
      cleanup();
      if (created) script?.remove();
      reject(new Error("连接校验组件加载失败"));
    };
    const poll = setInterval(succeed, 50);
    const timeout = setTimeout(onError, REQUEST_TIMEOUT_MS);
    script.addEventListener("load", succeed, { once: true });
    script.addEventListener("error", onError, { once: true });
    if (created) document.head.append(script);
    succeed();
  });
  turnstileScriptPromise = pending;
  try {
    return await pending;
  } catch (error) {
    if (turnstileScriptPromise === pending) turnstileScriptPromise = null;
    throw error;
  }
}

async function fetchWithTimeout(
  fetcher: typeof fetch,
  input: RequestInfo | URL,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetcher(input, { ...init, signal: controller.signal });
  } catch (error) {
    if (controller.signal.aborted) throw new Error("连接校验请求超时");
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    throw new Error("连接校验响应格式无效");
  }
}

function parseAdmissionStatus(value: unknown): AdmissionStatus {
  if (
    !isRecord(value)
    || typeof value.required !== "boolean"
    || typeof value.ready !== "boolean"
    || typeof value.siteKey !== "string"
  ) {
    throw new Error("连接校验状态格式无效");
  }
  return { required: value.required, ready: value.ready, siteKey: value.siteKey };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function safelyRemoveWidget(api: TurnstileApi, widgetId: string): void {
  try {
    api.remove(widgetId);
  } catch {
    // The DOM container is removed below even if the provider already disposed it.
  }
}
