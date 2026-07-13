export type PcmCaptureMode = "audio-worklet" | "script-processor" | "unavailable";

export type MediaCapabilities = {
  secureContext: boolean;
  getUserMedia: boolean;
  audioContext: boolean;
  audioWorklet: boolean;
  scriptProcessorFallback: boolean;
  pcmCaptureMode: PcmCaptureMode;
  htmlCanvasToBlob: boolean;
  offscreenCanvasEncoding: boolean;
  videoFrameEncoding: boolean;
  htmlAudioPlayback: boolean;
};

export type CapabilityScope = {
  isSecureContext?: boolean;
  navigator?: { mediaDevices?: { getUserMedia?: unknown } };
  AudioContext?: Function & { prototype?: { audioWorklet?: unknown; createScriptProcessor?: unknown } };
  AudioWorkletNode?: unknown;
  HTMLCanvasElement?: Function & { prototype?: { toBlob?: unknown } };
  OffscreenCanvas?: Function & { prototype?: { convertToBlob?: unknown } };
  createImageBitmap?: unknown;
  Audio?: unknown;
};

export function detectMediaCapabilities(
  scope: CapabilityScope = globalThis as CapabilityScope,
): MediaCapabilities {
  const secureContext = scope.isSecureContext === true;
  const getUserMedia = secureContext
    && typeof scope.navigator?.mediaDevices?.getUserMedia === "function";
  const audioContext = typeof scope.AudioContext === "function";
  const audioWorklet = audioContext
    && typeof scope.AudioWorkletNode === "function"
    && "audioWorklet" in (scope.AudioContext?.prototype ?? {});
  const scriptProcessorFallback = audioContext
    && typeof scope.AudioContext?.prototype?.createScriptProcessor === "function";
  const htmlCanvasToBlob = typeof scope.HTMLCanvasElement?.prototype?.toBlob === "function";
  const offscreenCanvasEncoding = typeof scope.OffscreenCanvas === "function"
    && typeof scope.OffscreenCanvas.prototype?.convertToBlob === "function"
    && typeof scope.createImageBitmap === "function";
  return {
    secureContext,
    getUserMedia,
    audioContext,
    audioWorklet,
    scriptProcessorFallback,
    pcmCaptureMode: audioWorklet
      ? "audio-worklet"
      : scriptProcessorFallback ? "script-processor" : "unavailable",
    htmlCanvasToBlob,
    offscreenCanvasEncoding,
    videoFrameEncoding: htmlCanvasToBlob || offscreenCanvasEncoding,
    htmlAudioPlayback: typeof scope.Audio === "function",
  };
}
