const PUBLIC_GET_ROUTES = new Set([
  "/health",
  "/voices",
  "/tts-health",
  "/asr-health",
  "/emotion-health",
  "/vision-health",
  "/reference-audio",
  "/realtime",
]);

const PUBLIC_POST_ROUTES = new Set([
  "/chat",
  "/tts",
  "/tts-runtime",
  "/asr",
  "/emotion",
  "/active-speaker",
  "/vision",
]);

type GatewayEnv = Env & {
  DEVICE_TOKEN: string;
};

function jsonError(status: number, message: string, requestId: string): Response {
  return Response.json(
    { error: message, request_id: requestId },
    {
      status,
      headers: {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "X-Request-Id": requestId,
      },
    },
  );
}

function isAllowedRoute(method: string, pathname: string): boolean {
  if (method === "OPTIONS") {
    return pathname.startsWith("/live2d/") || PUBLIC_GET_ROUTES.has(pathname) || PUBLIC_POST_ROUTES.has(pathname);
  }
  if (method === "GET") {
    return pathname.startsWith("/live2d/") || PUBLIC_GET_ROUTES.has(pathname);
  }
  return method === "POST" && PUBLIC_POST_ROUTES.has(pathname);
}

function withPublicHeaders(
  response: Response,
  requestId: string,
  cacheable: boolean,
  edgeCache: "HIT" | "MISS" = "MISS",
): Response {
  const headers = new Headers(response.headers);
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("Referrer-Policy", "no-referrer");
  headers.set("X-Request-Id", requestId);
  if (cacheable) {
    headers.set("Access-Control-Allow-Origin", "*");
    headers.delete("Vary");
    headers.set("Cache-Control", "public, max-age=3600, s-maxage=86400");
    headers.set("X-Visual-Cache", edgeCache);
  }
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function withLive2dAssetContentType(response: Response, pathname: string): Response {
  if (response.headers.has("Content-Type")) {
    return response;
  }
  const headers = new Headers(response.headers);
  if (pathname.endsWith(".moc3")) headers.set("Content-Type", "application/octet-stream");
  else if (pathname.endsWith(".json")) headers.set("Content-Type", "application/json; charset=utf-8");
  else return response;
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

export default {
  async fetch(request, env, ctx): Promise<Response> {
    const url = new URL(request.url);
    const requestId = request.headers.get("CF-Ray") || crypto.randomUUID();
    if (url.hostname !== "robot.veyralux.org") {
      return jsonError(404, "Not found", requestId);
    }
    if (
      (request.method === "GET" || request.method === "HEAD")
      && url.pathname.startsWith("/live2d/")
    ) {
      const assetResponse = await env.ASSETS.fetch(request);
      if (assetResponse.status !== 404) {
        return withLive2dAssetContentType(
          withPublicHeaders(assetResponse, requestId, true, "HIT"),
          url.pathname,
        );
      }
    }
    if (!isAllowedRoute(request.method, url.pathname)) {
      if (request.method !== "GET" && request.method !== "HEAD") {
        return jsonError(404, "Not found", requestId);
      }
      return env.ASSETS.fetch(request);
    }

    const cacheable = request.method === "GET" && url.pathname.startsWith("/live2d/");
    const cacheKey = new Request(url.toString(), { method: "GET" });
    if (cacheable) {
      const cached = await caches.default.match(cacheKey);
      if (cached) {
        return withPublicHeaders(cached, requestId, true, "HIT");
      }
    }

    const targetUrl = new URL(`${url.pathname}${url.search}`, "http://localhost:8765");
    const headers = new Headers(request.headers);
    headers.set("X-Forwarded-Host", url.hostname);
    headers.set("X-Forwarded-Proto", "https");
    const clientIp = request.headers.get("CF-Connecting-IP");
    if (clientIp) {
      headers.set("X-Forwarded-For", clientIp);
    }

    try {
      if (!env.DEVICE_TOKEN) {
        return jsonError(503, "公网网关尚未配置设备凭据。", requestId);
      }
      headers.set("X-Device-Token", env.DEVICE_TOKEN);
      const proxyRequest = new Request(targetUrl, {
        method: request.method,
        headers,
        body: request.body,
        redirect: "manual",
      });
      const upstream = await env.ELF2.fetch(proxyRequest);
      if (url.pathname === "/realtime") {
        return upstream;
      }
      const response = withPublicHeaders(upstream, requestId, cacheable);
      if (cacheable && response.ok) {
        ctx.waitUntil(caches.default.put(cacheKey, response.clone()));
      }
      return response;
    } catch (error) {
      console.error(JSON.stringify({
        event: "elf2_proxy_error",
        requestId,
        path: url.pathname,
        error: error instanceof Error ? error.message : String(error),
      }));
      return jsonError(502, "ELF2 暂时不可用。", requestId);
    }
  },
} satisfies ExportedHandler<GatewayEnv>;
