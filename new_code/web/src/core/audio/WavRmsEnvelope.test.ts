import { describe, expect, it } from "vitest";

import { envelopeValueAt, wavRmsEnvelope } from "./WavRmsEnvelope";

describe("wavRmsEnvelope", () => {
  it("extracts a 20ms PCM16 RMS envelope", () => {
    const data = monoWav(new Int16Array(320).fill(16_384), 16_000);
    const envelope = wavRmsEnvelope(data);
    expect(envelope).not.toBeNull();
    expect(envelope?.length).toBe(1);
    expect(envelopeValueAt(envelope!, 0)).toBeCloseTo(0.5, 2);
  });

  it("rejects non-WAV bytes without breaking playback", () => {
    expect(wavRmsEnvelope(new Uint8Array([1, 2, 3]).buffer)).toBeNull();
  });
});

function monoWav(samples: Int16Array, sampleRate: number): ArrayBuffer {
  const buffer = new ArrayBuffer(44 + samples.byteLength);
  const view = new DataView(buffer);
  writeAscii(view, 0, "RIFF");
  view.setUint32(4, 36 + samples.byteLength, true);
  writeAscii(view, 8, "WAVEfmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeAscii(view, 36, "data");
  view.setUint32(40, samples.byteLength, true);
  new Int16Array(buffer, 44).set(samples);
  return buffer;
}

function writeAscii(view: DataView, offset: number, value: string): void {
  for (let index = 0; index < value.length; index += 1) view.setUint8(offset + index, value.charCodeAt(index));
}
