function audioRms(samples) {
  if (!(samples instanceof Int16Array) || samples.length === 0) {
    return 0;
  }
  let sum = 0;
  for (let index = 0; index < samples.length; index += 1) {
    const value = samples[index] / 32768;
    sum += value * value;
  }
  return Math.sqrt(sum / samples.length);
}

function concatInt16(chunks, totalLength) {
  const result = new Int16Array(totalLength);
  let offset = 0;
  chunks.forEach((chunk) => {
    result.set(chunk, offset);
    offset += chunk.length;
  });
  return result;
}

class PcmSpeechSegmenter {
  constructor(options = {}) {
    this.sampleRate = options.sampleRate || 16000;
    this.energyThreshold = options.energyThreshold ?? 0.03;
    this.baselineMultiplier = options.baselineMultiplier ?? 2.6;
    this.warmupSamples = Math.round(this.sampleRate * (options.warmupMs ?? 384) / 1000);
    this.minStartSamples = Math.round(this.sampleRate * (options.minStartMs ?? 120) / 1000);
    this.minSpeechSamples = Math.round(this.sampleRate * (options.minSpeechMs ?? 240) / 1000);
    this.silenceSamplesRequired = Math.round(this.sampleRate * (options.silenceMs ?? 480) / 1000);
    this.maxSamples = Math.round(this.sampleRate * (options.maxSpeechMs ?? 12000) / 1000);
    this.preRollSamples = Math.round(this.sampleRate * (options.preRollMs ?? 240) / 1000);
    this.noiseFloor = 0.004;
    this.observedSamples = 0;
    this.reset();
  }

  reset() {
    this.active = false;
    this.chunks = [];
    this.totalLength = 0;
    this.silentLength = 0;
    this.preRoll = [];
    this.preRollLength = 0;
    this.speechCandidateSamples = 0;
  }

  push(rawSamples) {
    const samples = rawSamples instanceof Int16Array ? rawSamples : new Int16Array(rawSamples);
    if (!samples.length) {
      return null;
    }
    const rms = audioRms(samples);
    if (!this.active) {
      this._rememberPreRoll(samples);
      if (this.observedSamples < this.warmupSamples) {
        this.observedSamples += samples.length;
        this.noiseFloor = Math.max(this.noiseFloor, rms);
        return null;
      }
      const startThreshold = Math.max(this.energyThreshold, this.noiseFloor * this.baselineMultiplier);
      if (rms < startThreshold) {
        this.noiseFloor = this.noiseFloor * 0.95 + rms * 0.05;
        this.speechCandidateSamples = 0;
        return null;
      }
      this.speechCandidateSamples += samples.length;
      if (this.speechCandidateSamples < this.minStartSamples) {
        return null;
      }
      this.active = true;
      this.chunks = this.preRoll.map((chunk) => chunk.slice());
      this.totalLength = this.preRollLength;
      this.silentLength = 0;
      this.preRoll = [];
      this.preRollLength = 0;
      this.speechCandidateSamples = 0;
    } else {
      const speaking = rms >= Math.max(this.energyThreshold * 0.72, this.noiseFloor * 1.8);
      const chunk = samples.slice();
      this.chunks.push(chunk);
      this.totalLength += chunk.length;
      this.silentLength = speaking ? 0 : this.silentLength + chunk.length;
    }
    const reachedSentenceEnd = this.silentLength >= this.silenceSamplesRequired;
    if (this.totalLength >= this.maxSamples || (reachedSentenceEnd && this.totalLength >= this.minSpeechSamples)) {
      return this._complete();
    }
    return null;
  }

  flush() {
    if (!this.active || this.totalLength < this.minSpeechSamples) {
      this.reset();
      return null;
    }
    return this._complete();
  }

  _rememberPreRoll(samples) {
    const chunk = samples.slice();
    this.preRoll.push(chunk);
    this.preRollLength += chunk.length;
    while (this.preRollLength > this.preRollSamples && this.preRoll.length > 1) {
      const removed = this.preRoll.shift();
      this.preRollLength -= removed.length;
    }
  }

  _complete() {
    const result = concatInt16(this.chunks, this.totalLength);
    this.reset();
    return result.buffer;
  }
}

class PcmBargeInDetector {
  constructor(options = {}) {
    this.sampleRate = options.sampleRate || 16000;
    this.energyThreshold = options.energyThreshold ?? 0.055;
    this.minSpeechSamples = Math.round(this.sampleRate * (options.minSpeechMs ?? 200) / 1000);
    this.reset();
  }

  reset() {
    this.chunks = [];
    this.totalLength = 0;
  }

  push(rawSamples) {
    const samples = rawSamples instanceof Int16Array ? rawSamples : new Int16Array(rawSamples);
    if (!samples.length || audioRms(samples) < this.energyThreshold) {
      this.reset();
      return null;
    }
    const chunk = samples.slice();
    this.chunks.push(chunk);
    this.totalLength += chunk.length;
    if (this.totalLength < this.minSpeechSamples) {
      return null;
    }
    const result = concatInt16(this.chunks, this.totalLength);
    this.reset();
    return result.buffer;
  }
}

module.exports = { PcmBargeInDetector, PcmSpeechSegmenter, audioRms, concatInt16 };
