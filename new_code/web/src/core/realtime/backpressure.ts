import { BINARY_HEADER_BYTES } from "./protocol";

export type RealtimeBackpressureConfig = Readonly<{
  /** PCM16 mono at 16 kHz: 16_000 samples * 2 bytes. */
  pcmBytesPerSecond: number;
  /** Do not let queued microphone audio exceed this latency budget. */
  pcmBacklogHardLimitMs: number;
  /** Resume microphone delivery only after the queue drains below this level. */
  pcmBacklogRecoveryMs: number;
  /** JPEG is opportunistic and may only enter an otherwise drained socket. */
  videoSendMaxBufferedBytes: number;
  /** A delayed keyframe is useless context, even if it is still the latest one. */
  videoPendingMaxAgeMs: number;
  /** Polling is necessary because browser WebSocket has no bufferedamountlow event. */
  drainPollIntervalMs: number;
}>;

export const DEFAULT_REALTIME_BACKPRESSURE: RealtimeBackpressureConfig = Object.freeze({
  pcmBytesPerSecond: 32_000,
  pcmBacklogHardLimitMs: 160,
  pcmBacklogRecoveryMs: 60,
  videoSendMaxBufferedBytes: 0,
  videoPendingMaxAgeMs: 1_000,
  drainPollIntervalMs: 25,
});

export function pcmBacklogBytes(
  config: RealtimeBackpressureConfig,
  durationMs: number,
): number {
  return Math.floor(config.pcmBytesPerSecond * durationMs / 1_000);
}

export function framedBinaryBytes(payload: ArrayBuffer): number {
  return BINARY_HEADER_BYTES + payload.byteLength;
}

export function assertBackpressureConfig(
  config: RealtimeBackpressureConfig,
): RealtimeBackpressureConfig {
  const finitePositive = [
    config.pcmBytesPerSecond,
    config.pcmBacklogHardLimitMs,
    config.videoPendingMaxAgeMs,
    config.drainPollIntervalMs,
  ].every((value) => Number.isFinite(value) && value > 0);
  if (!finitePositive) throw new Error("实时背压阈值必须是正数");
  if (
    !Number.isFinite(config.pcmBacklogRecoveryMs)
    || config.pcmBacklogRecoveryMs < 0
    || config.pcmBacklogRecoveryMs >= config.pcmBacklogHardLimitMs
  ) {
    throw new Error("PCM 恢复阈值必须小于硬上限");
  }
  if (!Number.isFinite(config.videoSendMaxBufferedBytes) || config.videoSendMaxBufferedBytes < 0) {
    throw new Error("视觉发送阈值不能为负数");
  }
  return config;
}
