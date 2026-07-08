const assert = require("node:assert/strict");
const test = require("node:test");

const { PcmBargeInDetector, PcmSpeechSegmenter, audioRms } = require("../core/pcm-segmenter");

function tone(length, amplitude = 12000) {
  return Int16Array.from({ length }, (_, index) => Math.round(amplitude * Math.sin(index / 4)));
}

test("PCM 能量计算使用归一化振幅", () => {
  assert.equal(audioRms(new Int16Array(160)), 0);
  assert(audioRms(tone(160)) > 0.2);
});

test("句段器在持续静音后输出完整语音", () => {
  const segmenter = new PcmSpeechSegmenter({ sampleRate: 16000, minSpeechMs: 100, silenceMs: 100, preRollMs: 0, warmupMs: 0, minStartMs: 0 });
  assert.equal(segmenter.push(tone(1600)), null);
  const result = segmenter.push(new Int16Array(1600));
  assert(result instanceof ArrayBuffer);
  assert(new Int16Array(result).length >= 3200);
});

test("持续背景噪音不会误触发语音句段", () => {
  const segmenter = new PcmSpeechSegmenter({ sampleRate: 16000, warmupMs: 256, minStartMs: 100 });
  const noise = tone(2048, 700);
  assert.equal(segmenter.push(noise), null);
  assert.equal(segmenter.push(noise), null);
  assert.equal(segmenter.push(noise), null);
  assert.equal(segmenter.active, false);
  assert.equal(segmenter.push(tone(2048, 12000)), null);
  assert.equal(segmenter.active, true);
});

test("语音打断要求连续高能量输入", () => {
  const detector = new PcmBargeInDetector({ sampleRate: 16000, energyThreshold: 0.05, minSpeechMs: 200 });
  assert.equal(detector.push(tone(1600)), null);
  assert(detector.push(tone(1600)) instanceof ArrayBuffer);
  detector.reset();
  assert.equal(detector.push(tone(1600, 300)), null);
});
