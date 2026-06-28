import assert from "node:assert/strict";

import {
  PcmSpeechSegmenter,
  audioRms,
  floatToPcm16,
  resampleAudio,
} from "../src/offline-asr-client.js";

const silence = new Float32Array(1600);
const speech = Float32Array.from({ length: 3200 }, (_, index) => 0.12 * Math.sin(index / 4));

assert.equal(audioRms(silence), 0);
assert(audioRms(speech) > 0.08);

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
});
const forcedSegment = maxLengthSegmenter.push(speech);
assert(forcedSegment instanceof Float32Array);
assert.equal(maxLengthSegmenter.active, false);

const quietSegmenter = new PcmSpeechSegmenter({ sampleRate: 16000, energyThreshold: 0.2 });
assert.equal(quietSegmenter.push(speech), null);
assert.equal(quietSegmenter.flush(), null);

console.log("offline audio tests passed");
