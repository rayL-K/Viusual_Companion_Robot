const STORAGE_KEY = "visual-companion.device-config.v2";
const LEGACY_STORAGE_KEY = "visual-companion.device-config.v1";
const DEFAULT_DEVICE_CONFIG = Object.freeze({
  mode: "public",
  publicUrl: "https://robot.veyralux.org",
  host: "192.168.5.21",
  controlPort: 8765,
  token: "",
});

function normalizePublicUrl(rawUrl) {
  const value = String(rawUrl || DEFAULT_DEVICE_CONFIG.publicUrl).trim().replace(/\/$/, "");
  const match = /^https:\/\/([^/?#:]+)$/i.exec(value);
  if (!match) {
    throw new Error("公网入口必须是无端口、无路径的 HTTPS 域名。");
  }
  return `https://${normalizeHost(match[1]).toLowerCase()}`;
}

function normalizeHost(rawHost) {
  const host = String(rawHost || "").trim().replace(/^https?:\/\//, "").replace(/\/$/, "");
  const ipv4 = /^(?:\d{1,3}\.){3}\d{1,3}$/;
  const hostname = /^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i;
  const validHost = ipv4.test(host)
    ? host.split(".").every((part) => Number(part) <= 255)
    : hostname.test(host);
  if (!validHost) {
    throw new Error("设备地址必须是主机名或 IP 地址。");
  }
  return host;
}

function normalizePort(rawPort, fallback) {
  const port = Number(rawPort || fallback);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error("设备端口必须是 1 到 65535 之间的整数。");
  }
  return port;
}

function normalizeDeviceConfig(value = {}) {
  const mode = value.mode === "local" ? "local" : "public";
  return {
    mode,
    publicUrl: normalizePublicUrl(value.publicUrl),
    host: normalizeHost(value.host || DEFAULT_DEVICE_CONFIG.host),
    controlPort: normalizePort(value.controlPort, DEFAULT_DEVICE_CONFIG.controlPort),
    token: String(value.token || "").trim().slice(0, 256),
  };
}

function loadDeviceConfig() {
  try {
    const current = wx.getStorageSync(STORAGE_KEY);
    if (current) return normalizeDeviceConfig(current);
    // v1 曾允许把局域网模式持久化；手机离开该 Wi-Fi 后会同时造成 ELF2 和模型资源离线。
    // 首次迁移到 v2 时保留地址草稿，但恢复项目约定的公网默认模式。
    const legacy = wx.getStorageSync(LEGACY_STORAGE_KEY) || {};
    const migrated = normalizeDeviceConfig({ ...legacy, mode: "public" });
    wx.setStorageSync(STORAGE_KEY, migrated);
    return migrated;
  } catch (_error) {
    return { ...DEFAULT_DEVICE_CONFIG };
  }
}

function saveDeviceConfig(value) {
  const config = normalizeDeviceConfig(value);
  wx.setStorageSync(STORAGE_KEY, config);
  return config;
}

function controlBaseUrl(config) {
  const normalized = normalizeDeviceConfig(config);
  if (normalized.mode === "public") {
    return normalized.publicUrl;
  }
  return `http://${normalized.host}:${normalized.controlPort}`;
}

function displayDeviceAddress(config) {
  const normalized = normalizeDeviceConfig(config);
  return normalized.mode === "public" ? normalized.publicUrl : `${normalized.host}:${normalized.controlPort}`;
}

module.exports = {
  DEFAULT_DEVICE_CONFIG,
  STORAGE_KEY,
  controlBaseUrl,
  displayDeviceAddress,
  loadDeviceConfig,
  normalizeDeviceConfig,
  normalizePublicUrl,
  saveDeviceConfig,
};
