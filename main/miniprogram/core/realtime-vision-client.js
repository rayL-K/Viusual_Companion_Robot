class RealtimeVisionClient {
  constructor(options) {
    this.api = options.api;
    this.wx = options.wxApi || wx;
    this.timeoutMs = options.timeoutMs || 10000;
    this.socket = null;
    this.connectPromise = null;
    this.ready = false;
    this.pending = null;
  }

  connect() {
    if (this.ready) return Promise.resolve(true);
    if (this.connectPromise) return this.connectPromise;
    if (typeof this.wx.connectSocket !== "function") {
      return Promise.reject(new Error("当前微信版本不支持视觉实时通道。"));
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
      let connecting = true;
      socket.onOpen(() => {
        connecting = false;
        this.ready = true;
        this.connectPromise = null;
        resolve(true);
      });
      socket.onMessage((event) => this._handleMessage(event));
      socket.onError(() => {
        this.ready = false;
        this.connectPromise = null;
        this._rejectPending(new Error("视觉实时通道连接失败。"));
        if (connecting) reject(new Error("视觉实时通道连接失败。"));
        connecting = false;
      });
      socket.onClose(() => {
        this.ready = false;
        this.socket = null;
        this.connectPromise = null;
        this._rejectPending(new Error("视觉实时通道已断开。"));
        if (connecting) reject(new Error("视觉实时通道连接失败。"));
        connecting = false;
      });
    });
    return this.connectPromise;
  }

  analyze(image) {
    if (!this.ready || !this.socket || this.pending) {
      return Promise.reject(new Error("视觉实时通道尚未就绪。"));
    }
    const id = `vision-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(
        () => this._rejectPending(new Error("视觉实时结果返回超时。")),
        this.timeoutMs,
      );
      this.pending = { id, resolve, reject, timer };
      this.socket.send({ data: JSON.stringify({ id, type: "vision", image }) });
    });
  }

  close() {
    this._rejectPending(new Error("视觉实时通道已关闭。"));
    this.socket?.close?.({ code: 1000, reason: "camera stopped" });
    this.socket = null;
    this.ready = false;
    this.connectPromise = null;
  }

  _handleMessage(event) {
    let payload;
    try {
      payload = JSON.parse(String(event.data || ""));
    } catch (_error) {
      return;
    }
    if (!this.pending || payload.id !== this.pending.id || payload.type !== "vision") return;
    if (payload.ok === false) {
      this._rejectPending(new Error(payload.error || "视觉实时分析失败。"));
      return;
    }
    const pending = this.pending;
    this.pending = null;
    clearTimeout(pending.timer);
    pending.resolve(payload.data || payload);
  }

  _rejectPending(error) {
    const pending = this.pending;
    this.pending = null;
    if (!pending) return;
    clearTimeout(pending.timer);
    pending.reject(error);
  }
}

module.exports = { RealtimeVisionClient };
