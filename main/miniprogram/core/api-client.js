const { controlBaseUrl } = require("./config");

class DeviceApiError extends Error {
  constructor(message, statusCode = 0) {
    super(message);
    this.name = "DeviceApiError";
    this.statusCode = statusCode;
  }
}

class DeviceApiClient {
  constructor(configProvider) {
    this.configProvider = configProvider;
  }

  config() {
    return this.configProvider();
  }

  assetUrl(path) {
    return `${controlBaseUrl(this.config())}${path}`;
  }

  websocketUrl(path) {
    const baseUrl = controlBaseUrl(this.config());
    const websocketBase = baseUrl.startsWith("https://")
      ? `wss://${baseUrl.slice(8)}`
      : `ws://${baseUrl.slice(7)}`;
    return `${websocketBase}${path}`;
  }

  request(path, options = {}) {
    const config = this.config();
    const baseUrl = controlBaseUrl(config);
    const headers = { ...(options.header || {}) };
    if (config.token) {
      headers["X-Device-Token"] = config.token;
    }
    return new Promise((resolve, reject) => {
      wx.request({
        url: `${baseUrl}${path}`,
        method: options.method || "GET",
        data: options.data,
        header: headers,
        responseType: options.responseType || "text",
        timeout: options.timeout || 30000,
        success(response) {
          if (response.statusCode >= 200 && response.statusCode < 300) {
            resolve(response.data);
            return;
          }
          const detail = response.data?.error || response.errMsg || `HTTP ${response.statusCode}`;
          reject(new DeviceApiError(detail, response.statusCode));
        },
        fail(error) {
          reject(new DeviceApiError(error.errMsg || "无法连接 ELF2。"));
        },
      });
    });
  }

  health() {
    return this.request("/health", { timeout: 5000 });
  }

  voices() {
    return this.request("/voices", { timeout: 10000 });
  }

  chat(text, rate, vision) {
    return this.request("/chat", {
      method: "POST",
      data: { text, rate, vision },
      header: { "Content-Type": "application/json" },
      timeout: 90000,
    });
  }

  synthesize(payload) {
    return this.request("/tts", {
      method: "POST",
      data: payload,
      header: { "Content-Type": "application/json" },
      responseType: "arraybuffer",
      timeout: 120000,
    });
  }

  transcribe(pcm) {
    return this.request("/asr", {
      method: "POST",
      data: pcm,
      header: { "Content-Type": "audio/pcm; rate=16000" },
      timeout: 90000,
    });
  }

  activeSpeaker(pcm, frames) {
    const view = pcm instanceof Int16Array ? pcm : new Int16Array(pcm);
    const audio = view.length > 32000 ? view.subarray(view.length - 32000) : view;
    const audioBuffer = audio.buffer.slice(audio.byteOffset, audio.byteOffset + audio.byteLength);
    return this.request("/active-speaker", {
      method: "POST",
      data: {
        sample_rate: 16000,
        audio_pcm_base64: wx.arrayBufferToBase64(audioBuffer),
        frames: frames.slice(-16),
      },
      header: { "Content-Type": "application/json" },
      timeout: 30000,
    });
  }

  vision(imageBase64) {
    return this.request("/vision", {
      method: "POST",
      data: { image: imageBase64 },
      header: { "Content-Type": "application/json" },
      timeout: 20000,
    });
  }

  visionHealth() {
    return this.request("/vision-health", { timeout: 10000 });
  }
}

module.exports = { DeviceApiClient, DeviceApiError };
