from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from veyrasoul.gateway import AppServices, create_app
from veyrasoul.integrations import (
    DeepSeekConfig,
    DeepSeekStreamClient,
    LocalVlmClient,
    LocalVlmConfig,
    SherpaAsrConfig,
    SherpaStreamingAsr,
    SherpaTtsConfig,
    SherpaTtsSynthesizer,
)


def build_app():
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is required")
    v2_root = Path(__file__).resolve().parents[4]
    persona_path = Path(os.environ.get("VEYRASOUL_PERSONA_PATH", v2_root / "config" / "persona.md"))
    tts_model_value = os.environ.get("VEYRASOUL_TTS_MODEL_DIR", "").strip()
    if not tts_model_value:
        raise RuntimeError("VEYRASOUL_TTS_MODEL_DIR is required")
    tts_model_dir = Path(tts_model_value).expanduser()
    asr_model_value = os.environ.get("VEYRASOUL_ASR_MODEL_DIR", "").strip()
    if not asr_model_value:
        raise RuntimeError("VEYRASOUL_ASR_MODEL_DIR is required")
    asr_model_dir = Path(asr_model_value).expanduser()
    memory_path = Path(
        os.environ.get("VEYRASOUL_MEMORY_PATH", v2_root / "data" / "memory" / "veyrasoul.db")
    )
    web_dist_value = os.environ.get("VEYRASOUL_WEB_DIST", str(v2_root / "web" / "dist")).strip()
    web_dist = Path(web_dist_value).expanduser() if web_dist_value else None
    vlm = LocalVlmClient(
        LocalVlmConfig(
            base_url=os.environ.get("VEYRASOUL_VLM_URL", "http://127.0.0.1:8767"),
            timeout_seconds=float(os.environ.get("VEYRASOUL_VLM_TIMEOUT", "20")),
        )
    )
    llm = DeepSeekStreamClient(
        DeepSeekConfig(
            api_key=api_key,
            model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            max_tokens=int(os.environ.get("DEEPSEEK_MAX_TOKENS", "256")),
        )
    )
    tts = SherpaTtsSynthesizer(
        SherpaTtsConfig(
            model_dir=tts_model_dir,
            sid=int(os.environ.get("VEYRASOUL_TTS_SID", "0")),
            speed=float(os.environ.get("VEYRASOUL_TTS_SPEED", "1.0")),
            num_threads=int(os.environ.get("VEYRASOUL_TTS_THREADS", "4")),
        )
    )
    asr = SherpaStreamingAsr(
        SherpaAsrConfig(
            model_dir=asr_model_dir,
            num_threads=int(os.environ.get("VEYRASOUL_ASR_THREADS", "4")),
            decoding_method=os.environ.get(
                "VEYRASOUL_ASR_DECODING_METHOD", "greedy_search"
            ),
            rule1_min_trailing_silence=float(
                os.environ.get("VEYRASOUL_ASR_RULE1_SILENCE", "1.6")
            ),
            rule2_min_trailing_silence=float(
                os.environ.get("VEYRASOUL_ASR_RULE2_SILENCE", "0.55")
            ),
            rule3_min_utterance_length=float(
                os.environ.get("VEYRASOUL_ASR_RULE3_LENGTH", "20.0")
            ),
            queue_frames=int(os.environ.get("VEYRASOUL_ASR_QUEUE_FRAMES", "50")),
        )
    )
    services = AppServices(
        memory_path=memory_path,
        llm=llm,
        tts=tts,
        asr=asr,
        vision=vlm,
        vision_refresh_seconds=float(
            os.environ.get("VEYRASOUL_VISION_REFRESH_SECONDS", "5.0")
        ),
        stable_system_prompt=persona_path.read_text(encoding="utf-8"),
        startup=(asr.warmup, tts.warmup),
        shutdown=(llm.aclose, vlm.aclose),
        web_dist=web_dist,
    )
    return create_app(services)


def main() -> None:
    uvicorn.run(
        build_app(),
        host=os.environ.get("VEYRASOUL_HOST", "127.0.0.1"),
        port=int(os.environ.get("VEYRASOUL_PORT", "8875")),
        log_level=os.environ.get("VEYRASOUL_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
