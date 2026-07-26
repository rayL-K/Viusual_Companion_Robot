import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ensureRealtimeAdmission,
  requestTurnstileToken,
  type TurnstileApi,
} from "./admission";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("ensureRealtimeAdmission", () => {
  it("does not load a challenge when public admission is disabled or already ready", async () => {
    for (const status of [
      { required: false, ready: true, siteKey: "" },
      { required: true, ready: true, siteKey: "" },
    ]) {
      const fetcher = vi.fn(async () => jsonResponse(status));
      const requestToken = vi.fn(async () => "must-not-run");

      await ensureRealtimeAdmission({
        fetcher: fetcher as unknown as typeof fetch,
        requestToken,
      });

      expect(fetcher).toHaveBeenCalledTimes(1);
      expect(requestToken).not.toHaveBeenCalled();
    }
  });

  it("exchanges the opaque challenge token using same-origin cookies", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ required: true, ready: false, siteKey: "public-key" }))
      .mockResolvedValueOnce(jsonResponse({ ok: true }));
    const requestToken = vi.fn(async () => "opaque-single-use-token");

    await ensureRealtimeAdmission({
      fetcher: fetcher as unknown as typeof fetch,
      requestToken,
    });

    expect(requestToken).toHaveBeenCalledWith("public-key");
    expect(fetcher).toHaveBeenNthCalledWith(1, "/v2/admission/status", expect.objectContaining({
      method: "GET",
      credentials: "include",
      cache: "no-store",
    }));
    expect(fetcher).toHaveBeenNthCalledWith(2, "/v2/admission/verify", expect.objectContaining({
      method: "POST",
      credentials: "include",
      cache: "no-store",
      body: JSON.stringify({ token: "opaque-single-use-token" }),
    }));
  });

  it("fails closed for malformed status and rejected verification", async () => {
    const malformed = vi.fn(async () => jsonResponse({ required: true }));
    await expect(ensureRealtimeAdmission({ fetcher: malformed as unknown as typeof fetch }))
      .rejects.toThrow("连接校验状态格式无效");

    const rejected = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ required: true, ready: false, siteKey: "public-key" }))
      .mockResolvedValueOnce(jsonResponse({ ok: false }, 403));
    await expect(ensureRealtimeAdmission({
      fetcher: rejected as unknown as typeof fetch,
      requestToken: async () => "opaque-token",
    })).rejects.toThrow("连接校验未通过");
  });
});

describe("requestTurnstileToken", () => {
  it("uses explicit execution with the expected action and disposes the widget", async () => {
    const { documentLike, element } = fakeDocument();
    let renderedOptions: Parameters<TurnstileApi["render"]>[1] | undefined;
    const remove = vi.fn();
    const api: TurnstileApi = {
      render: (_container, options) => {
        renderedOptions = options;
        return "widget-1";
      },
      execute: () => renderedOptions?.callback("opaque-token"),
      remove,
    };

    await expect(requestTurnstileToken("public-key", {
      api,
      document: documentLike,
      timeoutMs: 1_000,
    })).resolves.toBe("opaque-token");

    expect(renderedOptions).toEqual(expect.objectContaining({
      sitekey: "public-key",
      action: "anima_admission",
      execution: "execute",
      appearance: "interaction-only",
    }));
    expect(remove).toHaveBeenCalledWith("widget-1");
    expect(element.removed).toBe(true);
  });

  it("rejects expired challenges and cleans up provider state", async () => {
    const { documentLike, element } = fakeDocument();
    let renderedOptions: Parameters<TurnstileApi["render"]>[1] | undefined;
    const remove = vi.fn();
    const api: TurnstileApi = {
      render: (_container, options) => {
        renderedOptions = options;
        return "widget-expired";
      },
      execute: () => renderedOptions?.["expired-callback"](),
      remove,
    };

    await expect(requestTurnstileToken("public-key", { api, document: documentLike }))
      .rejects.toThrow("已过期");
    expect(remove).toHaveBeenCalledWith("widget-expired");
    expect(element.removed).toBe(true);
  });

  it("times out and removes a challenge that never settles", async () => {
    vi.useFakeTimers();
    const { documentLike, element } = fakeDocument();
    const remove = vi.fn();
    const api: TurnstileApi = {
      render: () => "widget-timeout",
      execute: () => undefined,
      remove,
    };

    const result = requestTurnstileToken("public-key", {
      api,
      document: documentLike,
      timeoutMs: 100,
    });
    const rejected = expect(result).rejects.toThrow("等待超时");
    await vi.advanceTimersByTimeAsync(100);

    await rejected;
    expect(remove).toHaveBeenCalledWith("widget-timeout");
    expect(element.removed).toBe(true);
  });
});

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function fakeDocument(): {
  documentLike: Document;
  element: { removed: boolean };
} {
  const element = {
    className: "",
    removed: false,
    setAttribute: vi.fn(),
    remove() { this.removed = true; },
  };
  const documentLike = {
    createElement: () => element,
    body: { append: vi.fn() },
  } as unknown as Document;
  return { documentLike, element };
}
