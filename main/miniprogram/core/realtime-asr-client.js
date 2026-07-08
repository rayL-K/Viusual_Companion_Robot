class RealtimeAsrClient {
  constructor(options) {
    this.api = options.api;
    this.wx = options.wxApi || wx;
    this.timeoutMs = options.timeoutMs || 15000;
    this.socket = null;
    this.connectPromise = null;
    this.ready = false;
    this.activeId = "";
    this.pendingResult = null;
  }

  connect() {
    if (this.ready) return Promise.resolve(true);
    if (this.connectPromise) return this.connectPromise;
    if (typeof this.wx.connectSocket !== "function") {
      return Promise.reject(new Error("当前微信版本不支持实时 ASR 通道。"));
    }
    this.connectPromise = new Promise((resolve, reject) => {
      const config = this.api.config();
      const header = config.token ? { "X-Device-Token": config.token } : {};
      const socket = this.wx.connectSocket({
        url: this.api.websocketUrl("/realtime"),
        header,
        timeout: 15000,
      });
      this.socket = socket;
      socket.onOpen(() => {
        this.ready = true;
        this.connectPromise = null;
        resolve(true);
      });
      socket.onMessage((event) => this._handleMessage(event));
      socket.onError(() => {
        this.ready = false;
        this.connectPromise = null;
        this.activeId = "";
        this._rejectPending(new Error("实时 ASR 通道连接失败。"));
        reject(new Error("实时 ASR 通道连接失败。"));
      });
      socket.onClose(() => {
        this.ready = false;
        this.socket = null;
        this.connectPromise = null;
        this.activeId = "";
        this._rejectPending(new Error("实时 ASR 通道已断开。"));
      });
    });
    return this.connectPromise;
  }

  begin(chunks) {
    if (!this.ready || this.activeId) return false;
    this.activeId = `asr-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    this._send({ id: this.activeId, type: "asr_start", sample_rate: 16000 });
    for (const chunk of chunks || []) this.append(chunk);
    return true;
  }

  append(rawSamples) {
    if (!this.ready || !this.activeId) return false;
    const samples = rawSamples instanceof Int16Array ? rawSamples : new Int16Array(rawSamples);
    const buffer = samples.buffer.slice(samples.byteOffset, samples.byteOffset + samples.byteLength);
    this._send({
      id: this.activeId,
      type: "asr_chunk",
      audio_pcm_base64: this.wx.arrayBufferToBase64(buffer),
    });
    return true;
  }

  finish() {
    if (!this.ready || !this.activeId || this.pendingResult) {
      return Promise.reject(new Error("实时 ASR 流未就绪。"));
    }
    const id = this.activeId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => this._rejectPending(new Error("实时 ASR 返回超时。")), this.timeoutMs);
      this.pendingResult = { id, resolve, reject, timer };
      this._send({ id, type: "asr_end" });
    });
  }

  cancel() {
    if (this.ready && this.activeId) this._send({ id: this.activeId, type: "asr_cancel" });
    this.activeId = "";
    this._rejectPending(new Error("实时 ASR 已取消。"));
  }

  close() {
    this.cancel();
    this.socket?.close?.({ code: 1000, reason: "audio monitor stopped" });
    this.socket = null;
    this.ready = false;
    this.connectPromise = null;
  }

  _send(payload) {
    if (!this.socket || !this.ready) {
      throw new Error("实时 ASR 通道未连接。");
    }
    this.socket.send({ data: JSON.stringify(payload) });
  }

  _handleMessage(event) {
    let payload;
    try {
      payload = JSON.parse(String(event.data || ""));
    } catch (_error) {
      return;
    }
    if (payload.id !== this.activeId) return;
    if (payload.ok === false) {
      this.activeId = "";
      this._rejectPending(new Error(payload.error || "实时 ASR 失败。"));
      return;
    }
    if (payload.type !== "asr_result" || !this.pendingResult) return;
    const pending = this.pendingResult;
    this.pendingResult = null;
    this.activeId = "";
    clearTimeout(pending.timer);
    pending.resolve(payload.data || payload);
  }

  _rejectPending(error) {
    const pending = this.pendingResult;
    this.pendingResult = null;
    if (!pending) return;
    clearTimeout(pending.timer);
    pending.reject(error);
  }
}

module.exports = { RealtimeAsrClient };
