const { PcmBargeInDetector, PcmSpeechSegmenter } = require("./pcm-segmenter");
const { RealtimeAsrClient } = require("./realtime-asr-client");

const RECORDER_OPTIONS = Object.freeze({
  duration: 600000,
  sampleRate: 16000,
  numberOfChannels: 1,
  encodeBitRate: 256000,
  format: "PCM",
  frameSize: 4,
});

class AudioController {
  constructor(options) {
    this.api = options.api;
    this.onSegment = options.onSegment;
    this.onStatus = options.onStatus || (() => {});
    this.onPlayback = options.onPlayback || (() => {});
    this.onListening = options.onListening || (() => {});
    this.onSpeechStart = options.onSpeechStart || (() => {});
    this.recorder = wx.getRecorderManager();
    this.segmenter = new PcmSpeechSegmenter();
    this.bargeInDetector = new PcmBargeInDetector();
    this.realtimeAsr = new RealtimeAsrClient({ api: this.api });
    this.realtimeStreaming = false;
    this.listening = false;
    this.desiredListening = false;
    this.playing = false;
    this.audio = null;
    this.audioPath = "";
    this._bindRecorder();
  }

  start() {
    this.desiredListening = true;
    this.onListening(true);
    if (this.listening) {
      return;
    }
    this.segmenter.reset();
    this.bargeInDetector.reset();
    this.realtimeAsr.cancel();
    this.realtimeStreaming = false;
    this.realtimeAsr.connect().catch(() => {});
    this.recorder.start(RECORDER_OPTIONS);
  }

  stop() {
    this.desiredListening = false;
    this.onListening(false);
    if (this.listening) {
      this.recorder.stop();
    }
    this.realtimeAsr.cancel();
    this.realtimeStreaming = false;
    this.stopPlayback();
  }

  async playSpeech(payload) {
    this.stopPlayback();
    this.onStatus("正在由 ELF2 生成语音……");
    const audioData = await this.api.synthesize(payload);
    const filePath = `${wx.env.USER_DATA_PATH}/vc-tts-${Date.now()}.wav`;
    await this._writeFile(filePath, audioData);
    const audio = wx.createInnerAudioContext({ useWebAudioImplement: true });
    this.audio = audio;
    this.audioPath = filePath;
    audio.src = filePath;
    audio.onPlay(() => {
      this.playing = true;
      this.bargeInDetector.reset();
      this.onPlayback(true);
      this.onStatus("草莓兔兔正在说话；你开口时会自动打断。");
    });
    audio.onEnded(() => this._releasePlayback("语音播放完成。"));
    audio.onStop(() => this._releasePlayback("语音已停止。"));
    audio.onError((error) => this._releasePlayback(`语音播放失败：${error.errMsg || "未知错误"}`));
    audio.play();
  }

  stopPlayback() {
    if (!this.audio) {
      return;
    }
    const audio = this.audio;
    this.audio = null;
    audio.stop();
    audio.destroy();
    this._clearPlaybackState();
  }

  destroy() {
    this.stop();
    this.recorder.offStart?.(this.handleRecorderStart);
    this.recorder.offStop?.(this.handleRecorderStop);
    this.recorder.offError?.(this.handleRecorderError);
    this.recorder.offFrameRecorded?.(this.handleFrameRecorded);
    this.realtimeAsr.close();
  }

  _bindRecorder() {
    this.handleRecorderStart = () => {
      this.listening = true;
      if (!this.desiredListening) {
        this.recorder.stop();
        return;
      }
      this.onStatus("正在本机持续监听，句尾会自动发送到 ELF2。");
    };
    this.handleRecorderStop = () => {
      this.listening = false;
      const pending = this.segmenter.flush();
      if (pending) {
        const realtimePromise = this.realtimeStreaming ? this.realtimeAsr.finish() : null;
        this.realtimeStreaming = false;
        this.onSegment(pending, realtimePromise);
      } else if (this.realtimeStreaming) {
        this.realtimeAsr.cancel();
        this.realtimeStreaming = false;
      }
      if (this.desiredListening) {
        this.onStatus("录音分段已轮换，正在继续监听……");
        setTimeout(() => {
          if (this.desiredListening && !this.listening) {
            this.segmenter.reset();
            this.recorder.start(RECORDER_OPTIONS);
          }
        }, 80);
      } else {
        this.onStatus("麦克风监听已关闭。");
      }
    };
    this.handleRecorderError = (error) => {
      this.listening = false;
      this.desiredListening = false;
      this.onListening(false);
      this.onStatus(`录音失败：${error.errMsg || "请检查麦克风权限"}`);
    };
    this.handleFrameRecorded = ({ frameBuffer }) => this._handleFrame(frameBuffer);
    this.recorder.onStart(this.handleRecorderStart);
    this.recorder.onStop(this.handleRecorderStop);
    this.recorder.onError(this.handleRecorderError);
    this.recorder.onFrameRecorded(this.handleFrameRecorded);
  }

  _handleFrame(frameBuffer) {
    const samples = new Int16Array(frameBuffer);
    if (this.playing) {
      const interruption = this.bargeInDetector.push(samples);
      if (!interruption) {
        return;
      }
      this.stopPlayback();
      this.onStatus("检测到你正在说话，已停止播放并继续识别。");
      this._pushSpeechSamples(new Int16Array(interruption));
      return;
    }
    this._pushSpeechSamples(samples);
  }

  _pushSpeechSamples(samples) {
    const wasActive = this.segmenter.active;
    const segment = this.segmenter.push(samples);
    if (!wasActive && this.segmenter.active) {
      this.onSpeechStart();
      this.realtimeStreaming = this.realtimeAsr.begin(this.segmenter.chunks);
    } else if (wasActive && this.realtimeStreaming) {
      this.realtimeStreaming = this.realtimeAsr.append(samples);
      if (!this.realtimeStreaming) this.realtimeAsr.cancel();
    }
    if (segment) {
      const realtimePromise = this.realtimeStreaming ? this.realtimeAsr.finish() : null;
      this.realtimeStreaming = false;
      this.onSegment(segment, realtimePromise);
    }
  }

  _writeFile(filePath, data) {
    return new Promise((resolve, reject) => {
      wx.getFileSystemManager().writeFile({
        filePath,
        data,
        success: resolve,
        fail: reject,
      });
    });
  }

  _releasePlayback(status) {
    const audio = this.audio;
    this.audio = null;
    audio?.destroy();
    this._clearPlaybackState();
    this.onStatus(status);
  }

  _clearPlaybackState() {
    this.playing = false;
    this.onPlayback(false);
    this.bargeInDetector.reset();
    const filePath = this.audioPath;
    this.audioPath = "";
    if (filePath) {
      wx.getFileSystemManager().unlink({ filePath, fail: () => {} });
    }
  }
}

module.exports = { AudioController, RECORDER_OPTIONS };
