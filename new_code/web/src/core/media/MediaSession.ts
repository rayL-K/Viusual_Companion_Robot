import type { RealtimeClient } from "../realtime/RealtimeClient";
import { BINARY_KIND_JPEG, BINARY_KIND_PCM16 } from "../realtime/protocol";
import { PcmCapture } from "./PcmCapture";
import { VideoSampler } from "./VideoSampler";

export class MediaSession {
  private stream: MediaStream | null = null;
  private video: HTMLVideoElement | null = null;
  private readonly pcm = new PcmCapture();
  private readonly videoSampler = new VideoSampler();

  constructor(private readonly realtime: RealtimeClient) {}

  get active(): boolean {
    return this.stream !== null;
  }

  async start(video: HTMLVideoElement): Promise<MediaStream> {
    this.stop(video);
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("当前浏览器或页面环境不支持摄像头与麦克风通话");
    }
    const stream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: "user" },
        width: { ideal: 1280, max: 1280 },
        height: { ideal: 720, max: 720 },
        frameRate: { ideal: 60, max: 60 },
      },
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
      },
    });
    try {
      this.stream = stream;
      this.video = video;
      video.srcObject = stream;
      video.muted = true;
      video.playsInline = true;
      await video.play();
      this.videoSampler.start(video, (jpeg) => this.realtime.sendBinary(BINARY_KIND_JPEG, jpeg));
      await this.pcm.start(stream, (pcm16) => this.realtime.sendBinary(BINARY_KIND_PCM16, pcm16));
      return stream;
    } catch (error) {
      this.stop(video);
      throw error;
    }
  }

  setCameraEnabled(enabled: boolean): void {
    for (const track of this.stream?.getVideoTracks() ?? []) track.enabled = enabled;
    if (!enabled) {
      this.videoSampler.stop();
    } else if (this.video) {
      this.videoSampler.start(this.video, (jpeg) => this.realtime.sendBinary(BINARY_KIND_JPEG, jpeg));
    }
  }

  setMicrophoneEnabled(enabled: boolean): void {
    for (const track of this.stream?.getAudioTracks() ?? []) track.enabled = enabled;
    this.pcm.setEnabled(enabled);
  }

  stop(video?: HTMLVideoElement | null): void {
    this.videoSampler.stop();
    this.pcm.stop();
    for (const track of this.stream?.getTracks() ?? []) track.stop();
    this.stream = null;
    const attachedVideo = video ?? this.video;
    this.video = null;
    if (attachedVideo) attachedVideo.srcObject = null;
  }
}
