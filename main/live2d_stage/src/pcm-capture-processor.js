const BATCH_SAMPLES = 1024;

class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Float32Array(BATCH_SAMPLES);
    this.offset = 0;
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel?.length) {
      return true;
    }

    let sourceOffset = 0;
    while (sourceOffset < channel.length) {
      const copyLength = Math.min(channel.length - sourceOffset, BATCH_SAMPLES - this.offset);
      this.buffer.set(channel.subarray(sourceOffset, sourceOffset + copyLength), this.offset);
      this.offset += copyLength;
      sourceOffset += copyLength;
      if (this.offset === BATCH_SAMPLES) {
        const completed = this.buffer;
        this.buffer = new Float32Array(BATCH_SAMPLES);
        this.offset = 0;
        this.port.postMessage(completed.buffer, [completed.buffer]);
      }
    }
    return true;
  }
}

registerProcessor("pcm-capture-processor", PcmCaptureProcessor);
