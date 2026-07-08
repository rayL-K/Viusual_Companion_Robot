import { floatToPcm16 } from "./offline-asr-client.js";
import { apiUrl } from "./runtime-config.js";

const ACTIVE_SPEAKER_URL = apiUrl("/active-speaker");
const MAX_AUDIO_SAMPLES = 16000 * 2;

export async function detectActiveSpeaker(samples, frames) {
  if (!(samples instanceof Float32Array) || !Array.isArray(frames) || frames.length < 4) {
    return null;
  }
  const audio = samples.length > MAX_AUDIO_SAMPLES ? samples.slice(-MAX_AUDIO_SAMPLES) : samples;
  const response = await fetch(ACTIVE_SPEAKER_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sample_rate: 16000,
      audio_pcm_base64: arrayBufferToBase64(floatToPcm16(audio)),
      frames: frames.slice(-16),
    }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result.ok !== true || result.backend !== "elf2-local-light-asd") {
    throw new Error(result.error || `主动说话人服务返回 HTTP ${response.status}`);
  }
  return result;
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
}
