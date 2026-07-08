import assert from "node:assert/strict";

import {
  PcmBargeInDetector,
  PcmSpeechSegmenter,
  audioZeroCrossingRate,
  audioRms,
  floatToPcm16,
  resampleAudio,
} from "../src/offline-asr-client.js";

const silence = new Float32Array(1600);
const speech = Float32Array.from({ length: 3200 }, (_, index) => 0.12 * Math.sin(index / 4));

assert.equal(audioRms(silence), 0);
assert(audioRms(speech) > 0.08);
assert(audioZeroCrossingRate(speech) < 0.34);

const resampled = resampleAudio(Float32Array.from({ length: 48000 }, (_, index) => Math.sin(index / 20)), 48000);
assert.equal(resampled.length, 16000);
assert.throws(() => resampleAudio(speech, 0), /采样率/);

const pcm = floatToPcm16(Float32Array.from([-1, 0, 1, Number.NaN]));
const pcmView = new DataView(pcm);
assert.equal(pcmView.getInt16(0, true), -32768);
assert.equal(pcmView.getInt16(2, true), 0);
assert.equal(pcmView.getInt16(4, true), 32767);
assert.equal(pcmView.getInt16(6, true), 0);

const segmenter = new PcmSpeechSegmenter({
  sampleRate: 16000,
  preRollMs: 100,
  silenceMs: 100,
  minSegmentMs: 100,
  warmupMs: 0,
  minStartMs: 0,
});
assert.equal(segmenter.push(silence), null);
assert.equal(segmenter.push(speech), null);
const segment = segmenter.push(silence);
assert(segment instanceof Float32Array);
assert(segment.length >= speech.length + 1600);
assert.equal(segmenter.active, false);

const maxLengthSegmenter = new PcmSpeechSegmenter({
  sampleRate: 16000,
  preRollMs: 0,
  silenceMs: 1000,
  minSegmentMs: 50,
  maxSegmentMs: 100,
  warmupMs: 0,
  minStartMs: 0,
});
const forcedSegment = maxLengthSegmenter.push(speech);
assert(forcedSegment instanceof Float32Array);
assert.equal(maxLengthSegmenter.active, false);

const quietSegmenter = new PcmSpeechSegmenter({ sampleRate: 16000, energyThreshold: 0.2, warmupMs: 0, minStartMs: 0 });
assert.equal(quietSegmenter.push(speech), null);
assert.equal(quietSegmenter.flush(), null);

const adaptiveSegmenter = new PcmSpeechSegmenter({ sampleRate: 16000, warmupMs: 200, minStartMs: 80 });
const steadyNoise = Float32Array.from({ length: 1600 }, (_, index) => 0.022 * Math.sin(index / 4));
assert.equal(adaptiveSegmenter.push(steadyNoise), null);
assert.equal(adaptiveSegmenter.push(steadyNoise), null);
assert.equal(adaptiveSegmenter.push(steadyNoise), null);
assert.equal(adaptiveSegmenter.active, false);
assert.equal(adaptiveSegmenter.push(speech.slice(0, 1600)), null);
assert.equal(adaptiveSegmenter.active, true);

const noiseRejectingSegmenter = new PcmSpeechSegmenter({ sampleRate: 16000, warmupMs: 0, minStartMs: 80 });
const broadbandNoise = Float32Array.from({ length: 1600 }, (_, index) => (index % 2 ? 0.04 : -0.04));
assert(audioZeroCrossingRate(broadbandNoise) > 0.9);
assert.equal(noiseRejectingSegmenter.push(broadbandNoise), null);
assert.equal(noiseRejectingSegmenter.active, false);

const confirmedSpeechSegmenter = new PcmSpeechSegmenter({
  sampleRate: 16000,
  warmupMs: 500,
  minStartMs: 120,
});
assert.equal(confirmedSpeechSegmenter.pushConfirmedSpeech(speech.slice(0, 1600)), null);
assert.equal(confirmedSpeechSegmenter.active, true);

const bargeIn = new PcmBargeInDetector({
  sampleRate: 16000,
  energyThreshold: 0.05,
  warmupMs: 0,
  minSpeechMs: 200,
});
assert.equal(bargeIn.push(speech.slice(0, 1600)), null);
const interruptionAudio = bargeIn.push(speech.slice(1600, 3200));
assert(interruptionAudio instanceof Float32Array);
assert.equal(interruptionAudio.length, 3200);
assert.equal(bargeIn.push(speech.slice(0, 1600)), null);
assert.equal(bargeIn.push(silence), null);
assert.equal(bargeIn.push(speech.slice(1600, 3200)), null);

const echoProtectedBargeIn = new PcmBargeInDetector({
  sampleRate: 16000,
  energyThreshold: 0.02,
  baselineMultiplier: 1.8,
  warmupMs: 200,
  minSpeechMs: 200,
});
const echo = Float32Array.from({ length: 1600 }, (_, index) => 0.03 * Math.sin(index / 4));
assert.equal(echoProtectedBargeIn.push(echo), null);
assert.equal(echoProtectedBargeIn.push(echo), null);
assert.equal(echoProtectedBargeIn.push(echo), null);
assert.equal(echoProtectedBargeIn.push(speech.slice(0, 1600)), null);
assert(echoProtectedBargeIn.push(speech.slice(1600, 3200)) instanceof Float32Array);

console.log("offline audio tests passed");
