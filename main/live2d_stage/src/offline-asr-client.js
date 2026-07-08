import { apiUrl } from "./runtime-config.js";

const DEFAULT_ASR_URL = apiUrl("/asr");
const DEFAULT_ASR_HEALTH_URL = apiUrl("/asr-health");

export const ASR_SAMPLE_RATE = 16000;

export function realtimeAsrUrl(locationLike = globalThis.location) {
  const httpUrl = apiUrl("/realtime", locationLike);
  if (httpUrl.startsWith("https://")) return `wss://${httpUrl.slice(8)}`;
  if (httpUrl.startsWith("http://")) return `ws://${httpUrl.slice(7)}`;
  return "ws://127.0.0.1:8765/realtime";
}

export function audioRms(samples) {
  if (!(samples instanceof Float32Array) || samples.length === 0) {
    return 0;
  }

  let sum = 0;
  for (const sample of samples) {
    sum += sample * sample;
  }
  return Math.sqrt(sum / samples.length);
}

export function audioZeroCrossingRate(samples) {
  if (!(samples instanceof Float32Array) || samples.length < 2) return 0;
  let crossings = 0;
  for (let index = 1; index < samples.length; index += 1) {
    if ((samples[index - 1] < 0) !== (samples[index] < 0)) crossings += 1;
  }
  return crossings / (samples.length - 1);
}

export function resampleAudio(samples, sourceRate, targetRate = ASR_SAMPLE_RATE) {
  if (!(samples instanceof Float32Array)) {
    throw new TypeError("samples 必须是 Float32Array");
  }
  if (!Number.isFinite(sourceRate) || sourceRate <= 0 || !Number.isFinite(targetRate) || targetRate <= 0) {
    throw new RangeError("采样率必须是正数");
  }
  if (samples.length === 0 || sourceRate === targetRate) {
    return samples.slice();
  }

  const outputLength = Math.max(1, Math.round(samples.length * targetRate / sourceRate));
  const output = new Float32Array(outputLength);
  const ratio = sourceRate / targetRate;
  for (let index = 0; index < outputLength; index += 1) {
    const position = Math.min(index * ratio, samples.length - 1);
    const left = Math.floor(position);
    const right = Math.min(left + 1, samples.length - 1);
    const fraction = position - left;
    output[index] = samples[left] + (samples[right] - samples[left]) * fraction;
  }
  return output;
}

export function floatToPcm16(samples) {
  if (!(samples instanceof Float32Array)) {
    throw new TypeError("samples 必须是 Float32Array");
  }

  const buffer = new ArrayBuffer(samples.length * 2);
  const view = new DataView(buffer);
  samples.forEach((sample, index) => {
    const normalized = Math.max(-1, Math.min(1, Number.isFinite(sample) ? sample : 0));
    const value = normalized < 0 ? Math.round(normalized * 32768) : Math.round(normalized * 32767);
    view.setInt16(index * 2, value, true);
  });
  return buffer;
}

function concatChunks(chunks, totalLength) {
  const output = new Float32Array(totalLength);
  let offset = 0;
  for (const chunk of chunks) {
    output.set(chunk, offset);
    offset += chunk.length;
  }
  return output;
}

export class PcmSpeechSegmenter {
  constructor(options = {}) {
    this.sampleRate = options.sampleRate || ASR_SAMPLE_RATE;
    this.energyThreshold = options.energyThreshold ?? 0.026;
    this.baselineMultiplier = options.baselineMultiplier ?? 3.0;
    this.maxStartZeroCrossingRate = options.maxStartZeroCrossingRate ?? 0.34;
    this.warmupSamples = Math.round(this.sampleRate * (options.warmupMs ?? 320) / 1000);
    this.minStartSamples = Math.round(this.sampleRate * (options.minStartMs ?? 120) / 1000);
    this.preRollSamples = Math.round(this.sampleRate * (options.preRollMs ?? 220) / 1000);
    this.silenceSamples = Math.round(this.sampleRate * (options.silenceMs ?? 320) / 1000);
    this.minSegmentSamples = Math.round(this.sampleRate * (options.minSegmentMs ?? 400) / 1000);
    this.maxSegmentSamples = Math.round(this.sampleRate * (options.maxSegmentMs ?? 20000) / 1000);
    this.noiseFloor = 0.003;
    this.observedSamples = 0;
    this.reset();
  }

  reset() {
    this.active = false;
    this.preRoll = [];
    this.preRollLength = 0;
    this.segment = [];
    this.segmentLength = 0;
    this.trailingSilenceLength = 0;
    this.speechCandidateSamples = 0;
  }

  push(samples) {
    if (!(samples instanceof Float32Array) || samples.length === 0) {
      return null;
    }

    const chunk = samples.slice();
    const rms = audioRms(chunk);
    if (!this.active) {
      this.#appendPreRoll(chunk);
      if (this.observedSamples < this.warmupSamples) {
        this.observedSamples += chunk.length;
        this.noiseFloor = Math.max(this.noiseFloor, rms);
        return null;
      }
      const startThreshold = Math.max(this.energyThreshold, this.noiseFloor * this.baselineMultiplier);
      const looksLikeBroadbandNoise = rms < 0.08 && audioZeroCrossingRate(chunk) > this.maxStartZeroCrossingRate;
      if (rms < startThreshold || looksLikeBroadbandNoise) {
        this.noiseFloor = this.noiseFloor * 0.96 + rms * 0.04;
        this.speechCandidateSamples = 0;
        return null;
      }
      this.speechCandidateSamples += chunk.length;
      if (this.speechCandidateSamples < this.minStartSamples) {
        return null;
      }

      this.active = true;
      this.segment = this.preRoll;
      this.segmentLength = this.preRollLength;
      this.preRoll = [];
      this.preRollLength = 0;
      this.trailingSilenceLength = 0;
      this.speechCandidateSamples = 0;
    } else {
      const hasSpeech = rms >= Math.max(this.energyThreshold * 0.72, this.noiseFloor * 1.8);
      this.segment.push(chunk);
      this.segmentLength += chunk.length;
      this.trailingSilenceLength = hasSpeech ? 0 : this.trailingSilenceLength + chunk.length;
    }

    if (this.segmentLength >= this.maxSegmentSamples || this.trailingSilenceLength >= this.silenceSamples) {
      return this.#finishSegment();
    }
    return null;
  }

  flush() {
    return this.active ? this.#finishSegment() : null;
  }

  pushConfirmedSpeech(samples) {
    this.observedSamples = this.warmupSamples;
    this.speechCandidateSamples = this.minStartSamples;
    this.noiseFloor = Math.min(this.noiseFloor, this.energyThreshold / this.baselineMultiplier);
    return this.push(samples);
  }

  #appendPreRoll(chunk) {
    this.preRoll.push(chunk);
    this.preRollLength += chunk.length;
    while (this.preRoll.length > 1 && this.preRollLength > this.preRollSamples) {
      this.preRollLength -= this.preRoll[0].length;
      this.preRoll.shift();
    }
  }

  #finishSegment() {
    const chunks = this.segment;
    const length = this.segmentLength;
    this.reset();
    if (length < this.minSegmentSamples) {
      return null;
    }
    return concatChunks(chunks, length);
  }
}

export class PcmBargeInDetector {
  constructor(options = {}) {
    this.sampleRate = options.sampleRate || ASR_SAMPLE_RATE;
    this.energyThreshold = options.energyThreshold ?? 0.045;
    this.baselineMultiplier = options.baselineMultiplier ?? 1.8;
    this.warmupSamples = Math.round(this.sampleRate * (options.warmupMs ?? 320) / 1000);
    this.minSpeechSamples = Math.round(this.sampleRate * (options.minSpeechMs ?? 200) / 1000);
    this.reset();
  }

  reset() {
    this.baselineRms = 0;
    this.observedSamples = 0;
    this.#clearCandidate();
  }

  #clearCandidate() {
    this.chunks = [];
    this.totalLength = 0;
  }

  push(samples) {
    if (!(samples instanceof Float32Array) || samples.length === 0) {
      return null;
    }
    const rms = audioRms(samples);
    if (this.observedSamples < this.warmupSamples) {
      this.observedSamples += samples.length;
      this.baselineRms = Math.max(this.baselineRms, rms);
      this.#clearCandidate();
      return null;
    }

    const threshold = Math.max(this.energyThreshold, this.baselineRms * this.baselineMultiplier);
    if (rms < threshold) {
      this.baselineRms = this.baselineRms * 0.98 + rms * 0.02;
      this.#clearCandidate();
      return null;
    }

    const chunk = samples.slice();
    this.chunks.push(chunk);
    this.totalLength += chunk.length;
    if (this.totalLength < this.minSpeechSamples) {
      return null;
    }

    const detected = concatChunks(this.chunks, this.totalLength);
    this.#clearCandidate();
    return detected;
  }
}

export class OfflineAsrClient {
  constructor(options = {}) {
    this.asrUrl = options.asrUrl || DEFAULT_ASR_URL;
    this.healthUrl = options.healthUrl || DEFAULT_ASR_HEALTH_URL;
    this.timeoutMs = options.timeoutMs || 300000;
  }

  async health() {
    const response = await fetch(this.healthUrl, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || payload.message || `ASR 健康检查失败 (${response.status})`);
    }
    return payload;
  }

  async transcribe(samples) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await fetch(this.asrUrl, {
        method: "POST",
        headers: { "Content-Type": `audio/pcm; rate=${ASR_SAMPLE_RATE}; channels=1` },
        body: floatToPcm16(samples),
        signal: controller.signal,
      });
      const payload = await response.json();
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.error || payload.message || `离线语音识别失败 (${response.status})`);
      }
      return payload;
    } catch (error) {
      if (error.name === "AbortError") {
        throw new Error("离线语音识别超时；首次运行可能仍在下载模型，请稍后重试。");
      }
      throw error;
    } finally {
      window.clearTimeout(timeout);
    }
  }
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
}

export class RealtimeAsrClient {
  constructor(options = {}) {
    this.url = options.url || realtimeAsrUrl();
    this.timeoutMs = options.timeoutMs || 15000;
    this.WebSocketCtor = options.WebSocketCtor || globalThis.WebSocket;
    this.socket = null;
    this.connectPromise = null;
    this.activeId = "";
    this.pendingResult = null;
  }

  get ready() {
    return this.socket?.readyState === this.WebSocketCtor?.OPEN;
  }

  connect() {
    if (this.ready) return Promise.resolve(true);
    if (this.connectPromise) return this.connectPromise;
    if (!this.WebSocketCtor) return Promise.reject(new Error("当前浏览器不支持 WebSocket。"));

    this.connectPromise = new Promise((resolve, reject) => {
      const socket = new this.WebSocketCtor(this.url);
      this.socket = socket;
      const failConnect = () => {
        this.connectPromise = null;
        reject(new Error("实时 ASR 通道连接失败。"));
      };
      socket.addEventListener("open", () => {
        this.connectPromise = null;
        resolve(true);
      }, { once: true });
      socket.addEventListener("error", failConnect, { once: true });
      socket.addEventListener("message", (event) => this.#handleMessage(event));
      socket.addEventListener("close", () => {
        this.socket = null;
        this.connectPromise = null;
        this.#rejectPending(new Error("实时 ASR 通道已断开。"));
      });
    });
    return this.connectPromise;
  }

  begin(chunks, sourceRate) {
    if (!this.ready || this.activeId) return false;
    this.activeId = `asr-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    this.#send({ id: this.activeId, type: "asr_start", sample_rate: ASR_SAMPLE_RATE });
    for (const chunk of chunks || []) {
      if (!this.append(chunk, sourceRate)) {
        this.cancel();
        return false;
      }
    }
    return true;
  }

  append(samples, sourceRate) {
    if (!this.ready || !this.activeId || this.socket.bufferedAmount > 512 * 1024) return false;
    const resampled = resampleAudio(samples, sourceRate);
    const pcm = floatToPcm16(resampled);
    this.#send({
      id: this.activeId,
      type: "asr_chunk",
      audio_pcm_base64: arrayBufferToBase64(pcm),
    });
    return true;
  }

  finish() {
    if (!this.ready || !this.activeId || this.pendingResult) {
      return Promise.reject(new Error("实时 ASR 流未就绪。"));
    }
    const id = this.activeId;
    return new Promise((resolve, reject) => {
      const timer = globalThis.setTimeout(() => {
        this.#rejectPending(new Error("实时 ASR 返回超时。"));
      }, this.timeoutMs);
      this.pendingResult = { id, resolve, reject, timer };
      this.#send({ id, type: "asr_end" });
    });
  }

  cancel() {
    if (this.ready && this.activeId) {
      this.#send({ id: this.activeId, type: "asr_cancel" });
    }
    this.activeId = "";
    this.#rejectPending(new Error("实时 ASR 已取消。"));
  }

  close() {
    this.cancel();
    this.socket?.close();
    this.socket = null;
    this.connectPromise = null;
  }

  #send(payload) {
    this.socket.send(JSON.stringify(payload));
  }

  #handleMessage(event) {
    let payload;
    try {
      payload = JSON.parse(String(event.data || ""));
    } catch {
      return;
    }
    if (payload.id !== this.activeId) return;
    if (payload.ok === false) {
      this.activeId = "";
      this.#rejectPending(new Error(payload.error || "实时 ASR 失败。"));
      return;
    }
    if (payload.type !== "asr_result" || !this.pendingResult) return;
    const pending = this.pendingResult;
    this.pendingResult = null;
    this.activeId = "";
    globalThis.clearTimeout(pending.timer);
    pending.resolve(payload.data || payload);
  }

  #rejectPending(error) {
    const pending = this.pendingResult;
    this.pendingResult = null;
    if (!pending) return;
    globalThis.clearTimeout(pending.timer);
    pending.reject(error);
  }
}

export const offlineAsrClient = new OfflineAsrClient();
export const realtimeAsrClient = new RealtimeAsrClient();
