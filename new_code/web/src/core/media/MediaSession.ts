import type { RealtimeClient } from "../realtime/RealtimeClient";
import { BINARY_KIND_JPEG, BINARY_KIND_PCM16 } from "../realtime/protocol";
import { detectMediaCapabilities, type MediaCapabilities } from "./MediaCapabilities";
import type { MediaErrorDetails } from "./MediaError";
import { mediaError, normalizeMediaError } from "./MediaError";
import { PcmCapture, type ActivePcmCaptureMode } from "./PcmCapture";
import { VideoSampler, type VideoSamplerStatus } from "./VideoSampler";

export type MediaSessionStatus = {
  active: boolean;
  capabilities: MediaCapabilities;
  pcmCaptureMode: ActivePcmCaptureMode | null;
  videoSampling: VideoSamplerStatus;
  warning?: MediaErrorDetails;
};

const INACTIVE_VIDEO_STATUS: VideoSamplerStatus = { active: false, encoder: "unavailable" };

export class MediaSession {
  private stream: MediaStream | null = null;
  private video: HTMLVideoElement | null = null;
  private readonly pcm = new PcmCapture();
  private readonly videoSampler = new VideoSampler();
  private readonly mediaCapabilities = detectMediaCapabilities();
  private sessionStatus: MediaSessionStatus = {
    active: false,
    capabilities: this.mediaCapabilities,
    pcmCaptureMode: null,
    videoSampling: INACTIVE_VIDEO_STATUS,
  };

  constructor(private readonly realtime: RealtimeClient) {}

  get active(): boolean {
    return this.stream !== null;
  }

  get capabilities(): MediaCapabilities {
    return this.mediaCapabilities;
  }

  get status(): MediaSessionStatus {
    return {
      ...this.sessionStatus,
      capabilities: { ...this.sessionStatus.capabilities },
      videoSampling: { ...this.sessionStatus.videoSampling },
      warning: this.sessionStatus.warning ? { ...this.sessionStatus.warning } : undefined,
    };
  }

  async start(video: HTMLVideoElement): Promise<MediaStream> {
    this.stop(video);
    await this.pcm.whenStopped();
    this.assertCallCapabilities();
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia(mediaConstraints());
    } catch (error) {
      throw normalizeMediaError(error, "permission");
    }
    try {
      this.stream = stream;
      this.video = video;
      video.srcObject = stream;
      video.muted = true;
      video.playsInline = true;
      try {
        await video.play();
      } catch (error) {
        throw normalizeMediaError(error, "preview");
      }
      const videoSampling = this.startVideoSampling(video);
      const pcm = await this.pcm.start(
        stream,
        (frame) => { this.realtime.sendBinary(BINARY_KIND_PCM16, frame); },
      );
      this.sessionStatus = {
        active: true,
        capabilities: this.mediaCapabilities,
        pcmCaptureMode: pcm.mode,
        videoSampling,
        warning: pcm.degradedReason ?? videoSampling.error,
      };
      return stream;
    } catch (error) {
      this.stop(video);
      await this.pcm.whenStopped();
      throw error;
    }
  }

  setCameraEnabled(enabled: boolean): void {
    for (const track of this.stream?.getVideoTracks() ?? []) track.enabled = enabled;
    if (!enabled) {
      this.videoSampler.stop();
      this.sessionStatus = {
        ...this.sessionStatus,
        videoSampling: { ...this.sessionStatus.videoSampling, active: false },
      };
    } else if (this.video) {
      const videoSampling = this.startVideoSampling(this.video);
      this.sessionStatus = {
        ...this.sessionStatus,
        videoSampling,
        warning: videoSampling.error ?? this.sessionStatus.warning,
      };
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
    if (attachedVideo) {
      attachedVideo.pause();
      attachedVideo.srcObject = null;
    }
    this.sessionStatus = {
      active: false,
      capabilities: this.mediaCapabilities,
      pcmCaptureMode: null,
      videoSampling: INACTIVE_VIDEO_STATUS,
    };
  }

  async whenStopped(): Promise<void> {
    await this.pcm.whenStopped();
  }

  private startVideoSampling(video: HTMLVideoElement): VideoSamplerStatus {
    return this.videoSampler.start(
      video,
      (jpeg) => this.realtime.sendBinary(BINARY_KIND_JPEG, jpeg),
      (warning) => {
        this.sessionStatus = { ...this.sessionStatus, warning };
      },
    );
  }

  private assertCallCapabilities(): void {
    if (!this.mediaCapabilities.secureContext) {
      throw mediaError(
        "insecure-context",
        "capability",
        "摄像头与麦克风只能在 HTTPS 或 localhost 安全页面中使用",
        false,
      );
    }
    if (!this.mediaCapabilities.getUserMedia) {
      throw mediaError(
        "media-api-unavailable",
        "capability",
        "当前浏览器不提供摄像头与麦克风访问接口",
        false,
      );
    }
    if (!this.mediaCapabilities.audioContext) {
      throw mediaError(
        "audio-context-unavailable",
        "capability",
        "当前浏览器不支持实时语音处理",
        false,
      );
    }
    if (this.mediaCapabilities.pcmCaptureMode === "unavailable") {
      throw mediaError(
        "pcm-capture-unavailable",
        "capability",
        "当前浏览器没有可用的实时 PCM 语音采集接口",
        false,
      );
    }
  }
}

function mediaConstraints(): MediaStreamConstraints {
  return {
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
  };
}
