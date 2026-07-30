from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import httpx
import uvicorn

from veyrasoul.auth import OidcVerifier, SqliteAuthRepository
from veyrasoul.auth.login import (
    HttpxAuthorizationCodeExchanger,
    LoginFlowConfig,
    SqliteLoginAttemptStore,
)
from veyrasoul.auth.maintenance import (
    AuthExpiryMaintenance,
    PeriodicAuthExpiryMaintenance,
)
from veyrasoul.auth.oidc import OidcVerifierConfig, PyJwtOidcVerifier
from veyrasoul.auth.routes import create_auth_router
from veyrasoul.gateway import AppServices, create_app
from veyrasoul.gateway.toc_composition import (
    TocComposition,
    create_toc_composition,
    create_toc_oidc_login_flow,
)
from veyrasoul.identity import AnimaId, UserId
from veyrasoul.integrations import (
    DeepSeekConfig,
    DeepSeekStreamClient,
    LocalVlmClient,
    LocalVlmConfig,
    OpenAiAudioConfig,
    OpenAiCompatibleAsr,
    OpenAiCompatibleTts,
    SherpaAsrConfig,
    SherpaStreamingAsr,
    SherpaTtsConfig,
    SherpaTtsSynthesizer,
)
from veyrasoul.memory import (
    DocumentIngestor,
    HashingEmbeddingProvider,
    MemoryNamespace,
    MemoryStore,
    bind_store,
)
from veyrasoul.personalization import (
    DataLayout,
    IdentityService,
    SqliteIdentityRepository,
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


def build_app(
    settings: RuntimeSettings | None = None,
    *,
    oidc_verifier: OidcVerifier | None = None,
    oidc_token_transport: httpx.BaseTransport | None = None,
    audio_transport: httpx.AsyncBaseTransport | None = None,
):
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
    cloud_audio_config = None
    if "openai-compatible" in {tts_selection.name, asr_selection.name}:
        cloud_audio_config = OpenAiAudioConfig(
            api_key=config.audio_api_key,
            base_url=config.audio_base_url,
            connect_timeout_seconds=config.audio_connect_timeout_seconds,
            read_timeout_seconds=config.audio_read_timeout_seconds,
            max_response_bytes=config.audio_max_response_bytes,
            max_connections=config.audio_max_connections,
            max_keepalive_connections=config.audio_max_keepalive_connections,
        )
    if tts_selection.name == "sherpa":
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
    elif tts_selection.name == "openai-compatible":
        assert cloud_audio_config is not None
        tts = OpenAiCompatibleTts(
            cloud_audio_config,
            model=config.tts_cloud_model,
            voice=config.tts_cloud_voice,
            transport=audio_transport,
        )
    else:
        raise RuntimeError(f"unsupported selected TTS provider: {tts_selection.name}")
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
    elif asr_selection.name == "openai-compatible":
        assert cloud_audio_config is not None
        asr = OpenAiCompatibleAsr(
            cloud_audio_config,
            model=config.asr_cloud_model,
            transport=audio_transport,
        )
    vlm = None
    if vision_selection.name == "local-vlm":
        vlm = LocalVlmClient(
            LocalVlmConfig(
                base_url=config.vision_url,
                timeout_seconds=config.vision_timeout_seconds,
            )
        )
    startup = list(
        callback for callback in (asr.warmup if asr else None, tts.warmup) if callback is not None
    )
    shutdown = list(
        callback
        for callback in (
            llm.aclose,
            vlm.aclose if vlm else None,
            tts.aclose if isinstance(tts, OpenAiCompatibleTts) else None,
            asr.aclose if isinstance(asr, OpenAiCompatibleAsr) else None,
        )
        if callback is not None
    )
    stable_system_prompt = config.persona_path.read_text(encoding="utf-8")
    embedding_provider = HashingEmbeddingProvider()
    toc_composition: TocComposition | None = None
    auth_router = None
    if config.toc.enabled:
        layout = DataLayout(config.data_root, config.memory_path)
        identity_service = IdentityService(
            SqliteIdentityRepository(layout.identity_database()),
            layout,
            stable_system_prompt,
        )

        def document_ingestor_factory(
            user_id: UserId,
            anima_id: AnimaId,
        ) -> DocumentIngestor:
            namespace = MemoryNamespace(user_id, anima_id)
            memory = MemoryStore(layout.state_database(user_id, anima_id))
            bind_store(memory, namespace)
            return DocumentIngestor(
                memory,
                namespace,
                embedding_provider,
            )

        resolved_verifier = oidc_verifier or PyJwtOidcVerifier(
            OidcVerifierConfig(
                issuer=config.toc.issuer,
                audience=config.toc.audience,
                client_id=config.toc.client_id,
                jwks_url=config.toc.jwks_url,
            )
        )
        assert config.toc.auth_database is not None
        auth_repository = SqliteAuthRepository(config.toc.auth_database)
        login_attempt_store = SqliteLoginAttemptStore(
            config.toc.auth_database,
            config.toc.login_fernet_key.encode("ascii"),
        )
        toc_composition = create_toc_composition(
            oidc_verifier=resolved_verifier,
            auth_repository=auth_repository,
            identity_service=identity_service,
            document_ingestor_factory=document_ingestor_factory,
        )
        login_config = LoginFlowConfig(
            authorization_endpoint=config.toc.authorization_endpoint,
            token_endpoint=config.toc.token_endpoint,
            client_id=config.toc.client_id,
            redirect_uri=config.toc.redirect_uri,
        )
        login_flow = create_toc_oidc_login_flow(
            toc_composition,
            config=login_config,
            store=login_attempt_store,
            exchanger=HttpxAuthorizationCodeExchanger(
                login_config,
                transport=oidc_token_transport,
            ),
        )
        auth_maintenance = PeriodicAuthExpiryMaintenance(
            AuthExpiryMaintenance(auth_repository, login_attempt_store),
            on_error=lambda exc: trace_logger.warning(
                "Auth expiry cleanup failed (%s)",
                type(exc).__name__,
            ),
        )
        startup.append(auth_maintenance.start)
        shutdown.append(auth_maintenance.aclose)
        auth_router = create_auth_router(
            login_flow,
            toc_composition.session_boundary,
        )
    services = AppServices(
        memory_path=config.memory_path,
        llm=llm,
        tts=tts,
        asr=asr,
        vision=vlm,
        vision_refresh_seconds=config.vision_refresh_seconds,
        stable_system_prompt=stable_system_prompt,
        startup=tuple(startup),
        shutdown=tuple(shutdown),
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
                    (
                        config.asr_model_dir.name
                        if config.asr_model_dir
                        else config.asr_cloud_model
                        if asr_selection.name == "openai-compatible"
                        else "disabled"
                    ),
                ),
                llm=ProviderModel(llm_selection.name, config.llm_model),
                tts=ProviderModel(
                    tts_selection.name,
                    (
                        config.tts_model_dir.name
                        if config.tts_model_dir
                        else config.tts_cloud_model
                    ),
                ),
            ),
        ),
        admission=config.admission,
        release_digest=_release_digest(config.root),
        provider_snapshot=config.provider_snapshot,
        allow_anonymous_realtime=config.realtime_allow_anonymous,
        embedding_provider=embedding_provider,
        realtime_authenticator=(
            toc_composition.auth_service.authenticate
            if toc_composition is not None
            else None
        ),
        identity_service=(
            toc_composition.identity_service
            if toc_composition is not None
            else None
        ),
        realtime_access_cookie_name=(
            toc_composition.access_cookie_name
            if toc_composition is not None
            else "__Host-anima_session"
        ),
        realtime_allowed_origins=config.realtime_allowed_origins,
        realtime_reauth_seconds=config.realtime_reauth_seconds,
        realtime_lease_renew_seconds=config.realtime_lease_renew_seconds,
        auth_router=auth_router,
        toc_router=(
            toc_composition.router if toc_composition is not None else None
        ),
    )
    return create_app(services)


def main() -> None:
    settings = RuntimeSettings.from_environment()
    uvicorn.run(build_app(settings), **_server_options(settings))


if __name__ == "__main__":
    main()
