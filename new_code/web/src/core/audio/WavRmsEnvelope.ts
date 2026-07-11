const ENVELOPE_FRAME_SECONDS = 0.02;

export function wavRmsEnvelope(data: ArrayBuffer): Float32Array | null {
  const view = new DataView(data);
  if (view.byteLength < 44 || ascii(view, 0, 4) !== "RIFF" || ascii(view, 8, 4) !== "WAVE") {
    return null;
  }
  let channels = 0;
  let sampleRate = 0;
  let bitsPerSample = 0;
  let dataOffset = 0;
  let dataBytes = 0;
  for (let offset = 12; offset + 8 <= view.byteLength;) {
    const id = ascii(view, offset, 4);
    const size = view.getUint32(offset + 4, true);
    const body = offset + 8;
    if (body + size > view.byteLength) return null;
    if (id === "fmt " && size >= 16) {
      if (view.getUint16(body, true) !== 1) return null;
      channels = view.getUint16(body + 2, true);
      sampleRate = view.getUint32(body + 4, true);
      bitsPerSample = view.getUint16(body + 14, true);
    } else if (id === "data") {
      dataOffset = body;
      dataBytes = size;
    }
    offset = body + size + (size & 1);
  }
  if (channels < 1 || sampleRate < 1 || bitsPerSample !== 16 || dataBytes < channels * 2) {
    return null;
  }

  const samplesPerFrame = Math.max(1, Math.round(sampleRate * ENVELOPE_FRAME_SECONDS));
  const totalFrames = Math.ceil(dataBytes / (channels * 2 * samplesPerFrame));
  const envelope = new Float32Array(totalFrames);
  let byteOffset = dataOffset;
  for (let frame = 0; frame < totalFrames; frame += 1) {
    let squared = 0;
    let count = 0;
    for (let sample = 0; sample < samplesPerFrame && byteOffset + channels * 2 <= dataOffset + dataBytes; sample += 1) {
      let mixed = 0;
      for (let channel = 0; channel < channels; channel += 1) {
        mixed += view.getInt16(byteOffset, true) / 32768;
        byteOffset += 2;
      }
      mixed /= channels;
      squared += mixed * mixed;
      count += 1;
    }
    envelope[frame] = count ? Math.sqrt(squared / count) : 0;
  }
  return envelope;
}

export function envelopeValueAt(envelope: Float32Array, seconds: number): number {
  const index = Math.max(0, Math.min(envelope.length - 1, Math.floor(seconds / ENVELOPE_FRAME_SECONDS)));
  return envelope[index] ?? 0;
}

function ascii(view: DataView, offset: number, length: number): string {
  let value = "";
  for (let index = 0; index < length; index += 1) value += String.fromCharCode(view.getUint8(offset + index));
  return value;
}
