"""Verify the real local HTTP TTS -> resample -> ASR speech loop."""

from __future__ import annotations

import argparse
import difflib
import io
import json
import re
import time
import urllib.request
import wave

import numpy as np


def post(url: str, body: bytes, content_type: str, timeout: int = 180) -> tuple[bytes, float]:
    request = urllib.request.Request(url, data=body, headers={"Content-Type": content_type})
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
        if not 200 <= response.status < 300:
            raise RuntimeError(f"{url} returned HTTP {response.status}")
    return payload, (time.perf_counter() - started) * 1000


def wav_to_pcm16(audio: bytes, target_rate: int = 16000) -> tuple[bytes, int, int]:
    with wave.open(io.BytesIO(audio), "rb") as wav_file:
        if wav_file.getnchannels() != 1 or wav_file.getsampwidth() != 2:
            raise RuntimeError("TTS 必须返回 16 位单声道 WAV")
        source_rate = wav_file.getframerate()
        samples = np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype="<i2").astype(np.float32)
    if samples.size == 0:
        raise RuntimeError("TTS 返回了空 WAV")
    if source_rate != target_rate:
        output_length = round(samples.size * target_rate / source_rate)
        positions = np.arange(output_length) * source_rate / target_rate
        samples = np.interp(positions, np.arange(samples.size), samples)
    pcm = np.clip(samples, -32768, 32767).astype("<i2").tobytes()
    return pcm, source_rate, round(len(pcm) / 2 / target_rate * 1000)


def normalized_text(text: str) -> str:
    return re.sub(r"\W+", "", text, flags=re.UNICODE).lower()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-url", default="http://127.0.0.1:8765")
    parser.add_argument("--text", default="你好，我是草莓兔兔，这是本地语音闭环测试。")
    parser.add_argument("--voice", default="sherpa_vits")
    parser.add_argument("--min-similarity", type=float, default=0.45)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tts_body = json.dumps(
        {"text": args.text, "rate": 1.0, "voice": args.voice},
        ensure_ascii=False,
    ).encode("utf-8")
    audio, tts_ms = post(f"{args.control_url}/tts", tts_body, "application/json")
    pcm, source_rate, duration_ms = wav_to_pcm16(audio)
    asr_body, asr_ms = post(
        f"{args.control_url}/asr",
        pcm,
        "audio/pcm; rate=16000; channels=1",
    )
    asr = json.loads(asr_body.decode("utf-8"))
    recognized = str(asr.get("text") or "")
    similarity = difflib.SequenceMatcher(None, normalized_text(args.text), normalized_text(recognized)).ratio()
    result = {
        "ok": bool(asr.get("ok") and asr.get("speech_detected") and recognized and similarity >= args.min_similarity),
        "expected": args.text,
        "recognized": recognized,
        "similarity": round(similarity, 4),
        "source_rate": source_rate,
        "duration_ms": duration_ms,
        "tts_ms": round(tts_ms, 1),
        "asr_ms": round(asr_ms, 1),
        "speech_ratio": asr.get("speech_ratio"),
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
