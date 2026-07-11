class VeyraSoulPcmCapture extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const settings = options.processorOptions || {};
    this.targetRate = settings.targetRate || 16000;
    this.frameSamples = settings.frameSamples || 320;
    this.phase = 0;
    this.sum = 0;
    this.count = 0;
    this.output = new Int16Array(this.frameSamples);
    this.outputIndex = 0;
  }

  process(inputs) {
    const input = inputs[0] && inputs[0][0];
    if (!input) return true;
    for (let index = 0; index < input.length; index += 1) {
      this.sum += input[index];
      this.count += 1;
      this.phase += this.targetRate;
      if (this.phase < sampleRate) continue;
      this.phase -= sampleRate;
      const average = Math.max(-1, Math.min(1, this.sum / this.count));
      this.output[this.outputIndex] = average < 0 ? average * 32768 : average * 32767;
      this.outputIndex += 1;
      this.sum = 0;
      this.count = 0;
      if (this.outputIndex === this.output.length) {
        const frame = this.output;
        this.port.postMessage(frame.buffer, [frame.buffer]);
        this.output = new Int16Array(this.frameSamples);
        this.outputIndex = 0;
      }
    }
    return true;
  }
}

registerProcessor("veyrasoul-pcm-capture", VeyraSoulPcmCapture);
