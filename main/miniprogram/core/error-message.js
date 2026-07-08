function errorMessage(error, fallback = "未知错误") {
  if (typeof error === "string" && error.trim()) return error.trim();
  const message = error?.message || error?.errMsg || error?.error || error?.cause?.message;
  if (message) return String(message);
  try {
    const serialized = JSON.stringify(error);
    if (serialized && serialized !== "{}") return serialized;
  } catch (_ignored) {}
  return fallback;
}

module.exports = { errorMessage };
