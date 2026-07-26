from __future__ import annotations

import hashlib
import logging
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
from veyrasoul.telemetry import (
    JsonLogTraceSink,
    ProviderModel,
    TraceProviders,
    TraceSettings,
)

from .settings import RuntimeSettings


# Keep transport-level buffers below the application JPEG ceiling.  Application
# validation happens only after the WebSocket implementation has assembled a
# message, so relying on it alone would allow many 16 MiB messages to queue in
# Uvicorn before our own byte budget sees them.
WS_MAX_MESSAGE_BYTES = 1_600_000
WS_MAX_QUEUE = 2


def _release_digest(root: Path) -> str:
    manifest = root / ".release.sha256"
    try:
        payload = manifest.read_bytes()
    except OSError:
        return "development"
    return hashlib.sha256(payload).hexdigest()


def _server_options(settings: RuntimeSettings) -> dict[str, object]:
    return {
        "host": settings.host,
        "port": settings.port,
        "log_level": settings.log_level,
        # Uvicorn's SansIO integration supports current websockets releases;
        # the legacy implementation imports websockets.legacy, removed in 16.x.
        "ws": "websockets-sansio",
        "ws_max_size": WS_MAX_MESSAGE_BYTES,
        "ws_max_queue": WS_MAX_QUEUE,
        "ws_ping_interval": 20.0,
        "ws_ping_timeout": 20.0,
        "ws_per_message_deflate": False,
        "limit_concurrency": 64,
        "backlog": 128,
        "timeout_keep_alive": 5,
        "timeout_graceful_shutdown": 15,
        "access_log": False,
    }


def build_app(settings: RuntimeSettings | None = None):
    config = settings or RuntimeSettings.from_environment()
    llm_selection = config.provider_snapshot.resolve("llm")
    tts_selection = config.provider_snapshot.resolve("tts")
    asr_selection = config.provider_snapshot.resolve("asr")
    vision_selection = config.provider_snapshot.resolve("vision")
    # Reuse Uvicorn's production logger; its logging config is applied after build_app().
    trace_logger = logging.getLogger("uvicorn.error")
    llm = DeepSeekStreamClient(
        DeepSeekConfig(
            api_key=config.llm_api_key,
            model=config.llm_model,
            base_url=config.llm_base_url,
            max_tokens=config.llm_max_tokens,
        )
    )
    if config.tts_model_dir is None:
        raise RuntimeError("selected TTS provider has no model directory")
    tts = SherpaTtsSynthesizer(
        SherpaTtsConfig(
            model_dir=config.tts_model_dir,
            sid=config.tts_sid,
            speed=config.tts_speed,
            num_threads=config.tts_threads,
        )
    )
    asr = None
    if asr_selection.name == "sherpa":
        if config.asr_model_dir is None:
            raise RuntimeError("selected ASR provider has no model directory")
        asr = SherpaStreamingAsr(
            SherpaAsrConfig(
                model_dir=config.asr_model_dir,
                num_threads=config.asr_threads,
                decoding_method=config.asr_decoding_method,
                rule1_min_trailing_silence=config.asr_rule1_silence,
                rule2_min_trailing_silence=config.asr_rule2_silence,
                rule3_min_utterance_length=config.asr_rule3_length,
                queue_frames=config.asr_queue_frames,
            )
        )
    vlm = None
    if vision_selection.name == "local-vlm":
        vlm = LocalVlmClient(
            LocalVlmConfig(
                base_url=config.vision_url,
                timeout_seconds=config.vision_timeout_seconds,
            )
        )
    startup = tuple(
        callback for callback in (asr.warmup if asr else None, tts.warmup) if callback is not None
    )
    shutdown = tuple(
        callback for callback in (llm.aclose, vlm.aclose if vlm else None) if callback is not None
    )
    services = AppServices(
        memory_path=config.memory_path,
        llm=llm,
        tts=tts,
        asr=asr,
        vision=vlm,
        vision_refresh_seconds=config.vision_refresh_seconds,
        stable_system_prompt=config.persona_path.read_text(encoding="utf-8"),
        startup=startup,
        shutdown=shutdown,
        web_dist=config.web_dist,
        data_root=config.data_root,
        trace=TraceSettings(
            sink=JsonLogTraceSink(
                trace_logger,
                hmac_key=config.telemetry_hmac_key or None,
            ),
            providers=TraceProviders(
                asr=ProviderModel(
                    asr_selection.name,
                    config.asr_model_dir.name if config.asr_model_dir else "disabled",
                ),
                llm=ProviderModel(llm_selection.name, config.llm_model),
                tts=ProviderModel(
                    tts_selection.name,
                    config.tts_model_dir.name,
                ),
            ),
        ),
        admission=config.admission,
        release_digest=_release_digest(config.root),
        provider_snapshot=config.provider_snapshot,
    )
    return create_app(services)


def main() -> None:
    settings = RuntimeSettings.from_environment()
    uvicorn.run(build_app(settings), **_server_options(settings))


if __name__ == "__main__":
    main()
