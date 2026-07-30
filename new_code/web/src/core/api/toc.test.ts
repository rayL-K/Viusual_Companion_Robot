import { describe, expect, it, vi } from "vitest";

import {
  bootstrapAccess,
  loadTocSession,
  readCookie,
  TocApiClient,
} from "./toc";

describe("TocApiClient", () => {
  it("selects ToC, explicit anonymous, and unavailable modes from health only", async () => {
    const tocFetcher = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({
        tocEnabled: true,
        anonymousRealtimeEnabled: false,
      }))
      .mockResolvedValueOnce(jsonResponse({
        id: "alice",
        displayName: "Alice",
        revision: 1,
      }))
      .mockResolvedValueOnce(jsonResponse({
        items: [{ id: "rabbit", displayName: "月兔", state: "active", revision: 1 }],
      }));
    await expect(
      bootstrapAccess(new TocApiClient(tocFetcher as unknown as typeof fetch)),
    ).resolves.toMatchObject({ mode: "toc", user: { id: "alice" } });

    const anonymousFetcher = vi.fn().mockResolvedValue(jsonResponse({
      tocEnabled: false,
      anonymousRealtimeEnabled: true,
    }));
    await expect(
      bootstrapAccess(new TocApiClient(anonymousFetcher as unknown as typeof fetch)),
    ).resolves.toMatchObject({ mode: "anonymous", anima: { id: "default" } });
    expect(anonymousFetcher).toHaveBeenCalledTimes(1);

    const unavailableFetcher = vi.fn().mockResolvedValue(jsonResponse({
      tocEnabled: false,
      anonymousRealtimeEnabled: false,
    }));
    await expect(
      bootstrapAccess(new TocApiClient(unavailableFetcher as unknown as typeof fetch)),
    ).resolves.toEqual({ mode: "unavailable" });
    expect(unavailableFetcher).toHaveBeenCalledTimes(1);
  });

  it("parses the user and active Anima catalog with credentialed requests", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({
        id: "alice",
        displayName: "Alice",
        revision: 1,
      }))
      .mockResolvedValueOnce(jsonResponse({
        items: [
          { id: "rabbit", displayName: "月兔", state: "active", revision: 1 },
          { id: "old", displayName: "旧角色", state: "deleting", revision: 2 },
        ],
      }));
    const session = await loadTocSession(
      new TocApiClient(fetcher as unknown as typeof fetch),
    );

    expect(session.user.id).toBe("alice");
    expect(session.animas.map((anima) => anima.id)).toEqual(["rabbit"]);
    expect(fetcher).toHaveBeenNthCalledWith(
      1,
      "/v2/me",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("distinguishes 401 from a recoverable network failure", async () => {
    const unauthorized = new TocApiClient(
      vi.fn().mockResolvedValue(new Response("", { status: 401 })) as unknown as typeof fetch,
    );
    await expect(unauthorized.me()).rejects.toMatchObject({
      kind: "unauthenticated",
      status: 401,
    });

    const offline = new TocApiClient(
      vi.fn().mockRejectedValue(new TypeError("offline")) as unknown as typeof fetch,
    );
    await expect(offline.me()).rejects.toEqual(
      expect.objectContaining({ kind: "network" }),
    );
  });

  it("reads the CSRF cookie and sends the double-submit header on mutation", async () => {
    vi.stubGlobal("document", {
      cookie: "__Host-anima_csrf=csrf%20value; preference=compact",
    });
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    const api = new TocApiClient(fetcher as unknown as typeof fetch);

    await api.mutate("/v2/me", {
      method: "PATCH",
      body: JSON.stringify({ displayName: "Alice" }),
    });
    expect(readCookie("__Host-anima_csrf")).toBe("csrf value");
    expect(fetcher).toHaveBeenCalledWith(
      "/v2/me",
      expect.objectContaining({
        credentials: "include",
        headers: expect.objectContaining({ "X-CSRF-Token": "csrf value" }),
      }),
    );
    vi.unstubAllGlobals();
  });
});

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
