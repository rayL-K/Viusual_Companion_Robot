export type MediaErrorStage = "capability" | "permission" | "preview" | "pcm-capture" | "video-sampling";

export type MediaErrorCode =
  | "insecure-context"
  | "media-api-unavailable"
  | "permission-denied"
  | "device-not-found"
  | "device-busy"
  | "constraints-unsatisfied"
  | "request-aborted"
  | "security-blocked"
  | "preview-play-blocked"
  | "audio-context-unavailable"
  | "audio-context-suspended"
  | "audio-worklet-unavailable"
  | "pcm-capture-unavailable"
  | "frame-encoding-unavailable"
  | "frame-encoding-failed"
  | "frame-upload-unavailable"
  | "unknown-media-error";

export type MediaErrorDetails = {
  code: MediaErrorCode;
  stage: MediaErrorStage;
  message: string;
  recoverable: boolean;
  browserName?: string;
};

export class MediaSessionError extends Error {
  readonly details: MediaErrorDetails;
  override readonly cause: unknown;

  constructor(details: MediaErrorDetails, cause?: unknown) {
    super(details.message);
    this.name = "MediaSessionError";
    this.details = details;
    this.cause = cause;
  }
}

export function normalizeMediaError(error: unknown, stage: MediaErrorStage): MediaSessionError {
  if (error instanceof MediaSessionError) return error;
  const name = typeof DOMException !== "undefined" && error instanceof DOMException
    ? error.name
    : errorName(error);
  if (stage === "preview" && name === "NotAllowedError") {
    return mediaError("preview-play-blocked", stage, "浏览器阻止了画面播放，请点击页面后重试", true, name, error);
  }
  const mapped = MEDIA_ERROR_NAMES[name];
  if (mapped) return mediaError(mapped.code, stage, mapped.message, mapped.recoverable, name, error);
  return mediaError("unknown-media-error", stage, "无法启动摄像头或麦克风，请检查浏览器设置后重试", true, name, error);
}

export function mediaError(
  code: MediaErrorCode,
  stage: MediaErrorStage,
  message: string,
  recoverable: boolean,
  browserName?: string,
  cause?: unknown,
): MediaSessionError {
  return new MediaSessionError({ code, stage, message, recoverable, browserName }, cause);
}

function errorName(error: unknown): string {
  if (typeof error !== "object" || error === null || !("name" in error)) return "";
  return typeof error.name === "string" ? error.name : "";
}

const MEDIA_ERROR_NAMES: Record<string, Pick<MediaErrorDetails, "code" | "message" | "recoverable">> = {
  NotAllowedError: {
    code: "permission-denied",
    message: "摄像头或麦克风权限被拒绝，请在浏览器站点设置中允许后重试",
    recoverable: true,
  },
  PermissionDeniedError: {
    code: "permission-denied",
    message: "摄像头或麦克风权限被拒绝，请在浏览器站点设置中允许后重试",
    recoverable: true,
  },
  NotFoundError: {
    code: "device-not-found",
    message: "没有找到可用的摄像头或麦克风",
    recoverable: true,
  },
  DevicesNotFoundError: {
    code: "device-not-found",
    message: "没有找到可用的摄像头或麦克风",
    recoverable: true,
  },
  NotReadableError: {
    code: "device-busy",
    message: "摄像头或麦克风正被其他应用占用，请关闭占用程序后重试",
    recoverable: true,
  },
  TrackStartError: {
    code: "device-busy",
    message: "摄像头或麦克风正被其他应用占用，请关闭占用程序后重试",
    recoverable: true,
  },
  OverconstrainedError: {
    code: "constraints-unsatisfied",
    message: "当前设备无法满足通话采集参数，请更换设备后重试",
    recoverable: true,
  },
  ConstraintNotSatisfiedError: {
    code: "constraints-unsatisfied",
    message: "当前设备无法满足通话采集参数，请更换设备后重试",
    recoverable: true,
  },
  AbortError: {
    code: "request-aborted",
    message: "浏览器中止了媒体设备启动，请重试",
    recoverable: true,
  },
  SecurityError: {
    code: "security-blocked",
    message: "浏览器安全策略阻止了摄像头或麦克风访问",
    recoverable: false,
  },
};
