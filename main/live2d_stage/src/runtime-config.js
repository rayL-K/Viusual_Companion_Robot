const LOCAL_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]"]);

export function apiBaseUrl(locationLike = globalThis.location) {
  const hostname = String(locationLike?.hostname || "").toLowerCase();
  if (LOCAL_HOSTS.has(hostname)) {
    return "http://127.0.0.1:8765";
  }
  return String(locationLike?.origin || "").replace(/\/$/, "");
}

export function apiUrl(path, locationLike = globalThis.location) {
  const normalizedPath = String(path || "").startsWith("/") ? path : `/${path}`;
  return `${apiBaseUrl(locationLike)}${normalizedPath}`;
}
