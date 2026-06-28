const DEFAULT_ASR_URL = "http://127.0.0.1:8765/asr";
const DEFAULT_ASR_HEALTH_URL = "http://127.0.0.1:8765/asr-health";

export const ASR_SAMPLE_RATE = 16000;

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
    this.energyThreshold = options.energyThreshold ?? 0.015;
    this.preRollSamples = Math.round(this.sampleRate * (options.preRollMs ?? 300) / 1000);
    this.silenceSamples = Math.round(this.sampleRate * (options.silenceMs ?? 700) / 1000);
    this.minSegmentSamples = Math.round(this.sampleRate * (options.minSegmentMs ?? 400) / 1000);
    this.maxSegmentSamples = Math.round(this.sampleRate * (options.maxSegmentMs ?? 20000) / 1000);
    this.reset();
  }

  reset() {
    this.active = false;
    this.preRoll = [];
    this.preRollLength = 0;
    this.segment = [];
    this.segmentLength = 0;
    this.trailingSilenceLength = 0;
  }

  push(samples) {
    if (!(samples instanceof Float32Array) || samples.length === 0) {
      return null;
    }

    const chunk = samples.slice();
    const hasSpeech = audioRms(chunk) >= this.energyThreshold;
    if (!this.active) {
      this.#appendPreRoll(chunk);
      if (!hasSpeech) {
        return null;
      }

      this.active = true;
      this.segment = this.preRoll;
      this.segmentLength = this.preRollLength;
      this.preRoll = [];
      this.preRollLength = 0;
      this.trailingSilenceLength = 0;
    } else {
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

export const offlineAsrClient = new OfflineAsrClient();
