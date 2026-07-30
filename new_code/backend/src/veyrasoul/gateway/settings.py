"""Validated composition-root settings for portable Anima deployments."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from veyrasoul.providers import ProviderSnapshot, default_provider_registry

from .admission import AdmissionPolicy


_DISABLED = {"", "disabled", "none", "off"}


@dataclass(frozen=True, slots=True)
class TocRuntimeSettings:
    enabled: bool = False
    issuer: str = ""
    audience: str = ""
    jwks_url: str = ""
    authorization_endpoint: str = ""
    token_endpoint: str = ""
    client_id: str = ""
    redirect_uri: str = ""
    auth_database: Path | None = None
    login_fernet_key: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if not self.enabled:
            return
        missing = [
            name
            for name, value in (
                ("ANIMA_OIDC_ISSUER", self.issuer),
                ("ANIMA_OIDC_AUDIENCE", self.audience),
                ("ANIMA_OIDC_JWKS_URL", self.jwks_url),
                (
                    "ANIMA_OIDC_AUTHORIZATION_ENDPOINT",
                    self.authorization_endpoint,
                ),
                ("ANIMA_OIDC_TOKEN_ENDPOINT", self.token_endpoint),
                ("ANIMA_OIDC_CLIENT_ID", self.client_id),
                ("ANIMA_OIDC_REDIRECT_URI", self.redirect_uri),
                ("ANIMA_AUTH_DATABASE", self.auth_database),
                ("ANIMA_LOGIN_FERNET_KEY", self.login_fernet_key),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                "ANIMA_TOC_ENABLED=true requires: " + ", ".join(missing)
            )


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    root: Path
    host: str
    port: int
    log_level: str
    persona_path: Path
    data_root: Path
    memory_path: Path
    web_dist: Path | None
    llm_provider: str
    llm_api_key: str = field(repr=False)
    provider_snapshot: ProviderSnapshot
    telemetry_hmac_key: str = field(default="", repr=False)
    admission: AdmissionPolicy = field(default_factory=AdmissionPolicy, repr=False)
    llm_model: str = "deepseek-v4-flash"
    llm_base_url: str = "https://api.deepseek.com"
    llm_max_tokens: int = 256
    tts_provider: str = "sherpa"
    tts_model_dir: Path | None = None
    tts_sid: int = 0
    tts_speed: float = 1.0
    tts_threads: int = 4
    asr_provider: str | None = None
    asr_model_dir: Path | None = None
    asr_threads: int = 4
    asr_decoding_method: str = "greedy_search"
    asr_rule1_silence: float = 1.6
    asr_rule2_silence: float = 0.55
    asr_rule3_length: float = 20.0
    asr_queue_frames: int = 50
    audio_api_key: str = field(default="", repr=False)
    audio_base_url: str = "https://api.openai.com/v1"
    audio_connect_timeout_seconds: float = 5.0
    audio_read_timeout_seconds: float = 30.0
    audio_max_response_bytes: int = 16 * 1024 * 1024
    audio_max_connections: int = 20
    audio_max_keepalive_connections: int = 10
    tts_cloud_model: str = "gpt-4o-mini-tts"
    tts_cloud_voice: str = "alloy"
    asr_cloud_model: str = "gpt-4o-mini-transcribe"
    vision_provider: str | None = None
    vision_url: str = "http://127.0.0.1:8767"
    vision_timeout_seconds: float = 20.0
    vision_refresh_seconds: float = 5.0
    realtime_allow_anonymous: bool = False
    realtime_allowed_origins: tuple[str, ...] = ()
    realtime_reauth_seconds: float = 30.0
    realtime_lease_renew_seconds: float = 60.0
    toc: TocRuntimeSettings = field(default_factory=TocRuntimeSettings, repr=False)

    def __post_init__(self) -> None:
        legacy = {
            "llm": self.llm_provider,
            "tts": self.tts_provider,
            "asr": self.asr_provider or "disabled",
            "vision": self.vision_provider or "disabled",
        }
        if self.provider_snapshot.capabilities() != legacy:
            raise ValueError("provider snapshot does not match legacy provider settings")
        if self.toc.enabled and self.realtime_allow_anonymous:
            raise ValueError(
                "ANIMA_REALTIME_ALLOW_ANONYMOUS must be false when ToC is enabled"
            )

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        root: Path | None = None,
    ) -> "RuntimeSettings":
        values = os.environ if environ is None else environ
        product_root = (root or Path(__file__).resolve().parents[4]).resolve()
        read = _Environment(values)

        llm_provider = _provider(read.get("ANIMA_LLM_PROVIDER", default="deepseek")) or ""
        if llm_provider != "deepseek":
            raise ValueError(f"unsupported ANIMA_LLM_PROVIDER: {llm_provider or 'disabled'}")
        llm_api_key = read.get("ANIMA_LLM_API_KEY", "DEEPSEEK_API_KEY")
        if not llm_api_key:
            raise ValueError("ANIMA_LLM_API_KEY or DEEPSEEK_API_KEY is required")

        tts_provider = _provider(read.get("ANIMA_TTS_PROVIDER", default="sherpa")) or ""
        if tts_provider not in {"sherpa", "openai-compatible"}:
            raise ValueError(f"unsupported ANIMA_TTS_PROVIDER: {tts_provider or 'disabled'}")
        tts_model = read.get("ANIMA_TTS_MODEL_DIR", "VEYRASOUL_TTS_MODEL_DIR")
        if tts_provider == "sherpa" and not tts_model:
            raise ValueError("ANIMA_TTS_MODEL_DIR is required for the sherpa TTS provider")

        asr_provider = _provider(read.get("ANIMA_ASR_PROVIDER", default="sherpa"))
        asr_model: str | None = None
        if asr_provider is not None:
            if asr_provider not in {"sherpa", "openai-compatible"}:
                raise ValueError(f"unsupported ANIMA_ASR_PROVIDER: {asr_provider}")
            asr_model = read.get("ANIMA_ASR_MODEL_DIR", "VEYRASOUL_ASR_MODEL_DIR")
            if asr_provider == "sherpa" and not asr_model:
                raise ValueError("ANIMA_ASR_MODEL_DIR is required for the sherpa ASR provider")

        cloud_audio_enabled = "openai-compatible" in {tts_provider, asr_provider}
        audio_api_key = read.get("ANIMA_AUDIO_API_KEY") if cloud_audio_enabled else ""
        if cloud_audio_enabled and not audio_api_key:
            raise ValueError("ANIMA_AUDIO_API_KEY is required for cloud ASR or TTS")

        vision_provider = _provider(read.get("ANIMA_VISION_PROVIDER", default="local-vlm"))
        if vision_provider not in {None, "local-vlm"}:
            raise ValueError(f"unsupported ANIMA_VISION_PROVIDER: {vision_provider}")

        data_root = _path(read.get("ANIMA_DATA_ROOT", "VEYRASOUL_DATA_ROOT"), product_root / "data")
        memory_path = _path(
            read.get("ANIMA_MEMORY_PATH", "VEYRASOUL_MEMORY_PATH"),
            data_root / "memory" / "anima.db",
        )
        web_value = read.get("ANIMA_WEB_DIST", "VEYRASOUL_WEB_DIST", default=str(product_root / "web" / "dist"))
        telemetry_hmac_key = read.get("ANIMA_TELEMETRY_HMAC_KEY")
        if telemetry_hmac_key and len(telemetry_hmac_key.encode("utf-8")) < 32:
            raise ValueError("ANIMA_TELEMETRY_HMAC_KEY must contain at least 32 bytes")
        # This is the production composition root: public admission fails closed
        # unless a loopback developer explicitly opts out.
        admission_required = read.boolean("ANIMA_ADMISSION_REQUIRED", default=True)
        admission = AdmissionPolicy(
            required=admission_required,
            secret=read.get("ANIMA_ADMISSION_SECRET"),
            turnstile_site_key=read.get("ANIMA_TURNSTILE_SITE_KEY"),
            turnstile_secret=read.get("ANIMA_TURNSTILE_SECRET"),
            allowed_origins=_origins(
                read.get(
                    "ANIMA_ALLOWED_ORIGINS",
                    # Authenticated browser WebSockets require an exact Origin
                    # allowlist even when the optional admission challenge is off.
                    default="https://anima.veyralux.org",
                )
            ),
            token_ttl_seconds=read.integer(
                "ANIMA_ADMISSION_TTL_SECONDS", default=3_600, minimum=60, maximum=86_400
            ),
            device_ttl_seconds=read.integer(
                "ANIMA_DEVICE_TTL_SECONDS",
                default=30 * 24 * 3_600,
                minimum=86_400,
                maximum=365 * 24 * 3_600,
            ),
            max_connections=read.integer(
                "ANIMA_MAX_CONNECTIONS", default=12, minimum=1, maximum=1_024
            ),
            max_connections_per_client=read.integer(
                "ANIMA_MAX_CONNECTIONS_PER_CLIENT", default=3, minimum=1, maximum=128
            ),
            max_concurrent_turns=read.integer(
                "ANIMA_MAX_CONCURRENT_TURNS", default=2, minimum=1, maximum=64
            ),
            max_turns_per_client_per_minute=read.integer(
                "ANIMA_MAX_TURNS_PER_CLIENT_PER_MINUTE",
                default=20,
                minimum=1,
                maximum=600,
            ),
            max_turns_global_per_minute=read.integer(
                "ANIMA_MAX_TURNS_GLOBAL_PER_MINUTE",
                default=60,
                minimum=1,
                maximum=10_000,
            ),
            binary_bytes_per_second=read.integer(
                "ANIMA_BINARY_BYTES_PER_SECOND",
                default=512 * 1024,
                minimum=32 * 1024,
                maximum=16 * 1024 * 1024,
            ),
            binary_burst_bytes=read.integer(
                "ANIMA_BINARY_BURST_BYTES",
                default=2 * 1024 * 1024,
                minimum=32 * 1024,
                maximum=32 * 1024 * 1024,
            ),
            control_events_per_second=read.integer(
                "ANIMA_CONTROL_EVENTS_PER_SECOND",
                default=10,
                minimum=1,
                maximum=100,
            ),
            control_burst_events=read.integer(
                "ANIMA_CONTROL_BURST_EVENTS",
                default=20,
                minimum=1,
                maximum=500,
            ),
            idle_timeout_seconds=read.integer(
                "ANIMA_IDLE_TIMEOUT_SECONDS", default=90, minimum=30, maximum=3_600
            ),
            max_session_seconds=read.integer(
                "ANIMA_MAX_SESSION_SECONDS", default=1_800, minimum=60, maximum=86_400
            ),
        )

        provider_snapshot = default_provider_registry().parse_snapshot(
            {
                "llm": llm_provider,
                "tts": tts_provider,
                "asr": asr_provider,
                "vision": vision_provider,
            }
        )
        toc_enabled = read.boolean("ANIMA_TOC_ENABLED", default=False)
        auth_database_value = read.get("ANIMA_AUTH_DATABASE")
        toc = TocRuntimeSettings(
            enabled=toc_enabled,
            issuer=read.get("ANIMA_OIDC_ISSUER"),
            audience=read.get("ANIMA_OIDC_AUDIENCE"),
            jwks_url=read.get("ANIMA_OIDC_JWKS_URL"),
            authorization_endpoint=read.get(
                "ANIMA_OIDC_AUTHORIZATION_ENDPOINT"
            ),
            token_endpoint=read.get("ANIMA_OIDC_TOKEN_ENDPOINT"),
            client_id=read.get("ANIMA_OIDC_CLIENT_ID"),
            redirect_uri=read.get("ANIMA_OIDC_REDIRECT_URI"),
            auth_database=(
                _path(auth_database_value, data_root / "auth.sqlite3")
                if auth_database_value
                else None
            ),
            login_fernet_key=read.get("ANIMA_LOGIN_FERNET_KEY"),
        )

        return cls(
            root=product_root,
            host=read.get("ANIMA_HOST", "VEYRASOUL_HOST", default="127.0.0.1"),
            port=read.integer("ANIMA_PORT", "VEYRASOUL_PORT", default=8875, minimum=1, maximum=65_535),
            log_level=read.get("ANIMA_LOG_LEVEL", "VEYRASOUL_LOG_LEVEL", default="info"),
            persona_path=_path(
                read.get("ANIMA_PERSONA_PATH", "VEYRASOUL_PERSONA_PATH"),
                product_root / "config" / "persona.md",
            ),
            data_root=data_root,
            memory_path=memory_path,
            web_dist=Path(web_value).expanduser() if web_value else None,
            llm_provider=llm_provider,
            llm_api_key=llm_api_key,
            provider_snapshot=provider_snapshot,
            telemetry_hmac_key=telemetry_hmac_key,
            admission=admission,
            llm_model=read.get("ANIMA_LLM_MODEL", "DEEPSEEK_MODEL", default="deepseek-v4-flash"),
            llm_base_url=_base_url(
                read.get(
                    "ANIMA_LLM_BASE_URL", "DEEPSEEK_BASE_URL", default="https://api.deepseek.com"
                )
            ),
            llm_max_tokens=read.integer(
                "ANIMA_LLM_MAX_TOKENS", "DEEPSEEK_MAX_TOKENS", default=256, minimum=32, maximum=2_048
            ),
            tts_provider=tts_provider,
            tts_model_dir=Path(tts_model).expanduser() if tts_model else None,
            tts_sid=read.integer("ANIMA_TTS_SID", "VEYRASOUL_TTS_SID", default=0, minimum=0, maximum=65_535),
            tts_speed=read.number("ANIMA_TTS_SPEED", "VEYRASOUL_TTS_SPEED", default=1.0, minimum=0.5, maximum=2.0),
            tts_threads=read.integer("ANIMA_TTS_THREADS", "VEYRASOUL_TTS_THREADS", default=4, minimum=1, maximum=64),
            asr_provider=asr_provider,
            asr_model_dir=Path(asr_model).expanduser() if asr_model else None,
            asr_threads=read.integer("ANIMA_ASR_THREADS", "VEYRASOUL_ASR_THREADS", default=4, minimum=1, maximum=64),
            asr_decoding_method=read.get(
                "ANIMA_ASR_DECODING_METHOD", "VEYRASOUL_ASR_DECODING_METHOD", default="greedy_search"
            ),
            asr_rule1_silence=read.number(
                "ANIMA_ASR_RULE1_SILENCE", "VEYRASOUL_ASR_RULE1_SILENCE", default=1.6, minimum=0.05, maximum=10.0
            ),
            asr_rule2_silence=read.number(
                "ANIMA_ASR_RULE2_SILENCE", "VEYRASOUL_ASR_RULE2_SILENCE", default=0.55, minimum=0.05, maximum=10.0
            ),
            asr_rule3_length=read.number(
                "ANIMA_ASR_RULE3_LENGTH", "VEYRASOUL_ASR_RULE3_LENGTH", default=20.0, minimum=0.1, maximum=120.0
            ),
            asr_queue_frames=read.integer(
                "ANIMA_ASR_QUEUE_FRAMES", "VEYRASOUL_ASR_QUEUE_FRAMES", default=50, minimum=10, maximum=500
            ),
            audio_api_key=audio_api_key,
            audio_base_url=_base_url(
                read.get("ANIMA_AUDIO_BASE_URL", default="https://api.openai.com/v1"),
                setting="ANIMA_AUDIO_BASE_URL",
            ),
            audio_connect_timeout_seconds=read.number(
                "ANIMA_AUDIO_CONNECT_TIMEOUT_SECONDS", default=5.0, minimum=0.1, maximum=60.0
            ),
            audio_read_timeout_seconds=read.number(
                "ANIMA_AUDIO_READ_TIMEOUT_SECONDS", default=30.0, minimum=0.1, maximum=300.0
            ),
            audio_max_response_bytes=read.integer(
                "ANIMA_AUDIO_MAX_RESPONSE_BYTES",
                default=16 * 1024 * 1024,
                minimum=1024,
                maximum=128 * 1024 * 1024,
            ),
            audio_max_connections=read.integer(
                "ANIMA_AUDIO_MAX_CONNECTIONS", default=20, minimum=1, maximum=256
            ),
            audio_max_keepalive_connections=read.integer(
                "ANIMA_AUDIO_MAX_KEEPALIVE_CONNECTIONS", default=10, minimum=0, maximum=256
            ),
            tts_cloud_model=read.get(
                "ANIMA_TTS_CLOUD_MODEL", default="gpt-4o-mini-tts"
            ),
            tts_cloud_voice=read.get("ANIMA_TTS_CLOUD_VOICE", default="alloy"),
            asr_cloud_model=read.get(
                "ANIMA_ASR_CLOUD_MODEL", default="gpt-4o-mini-transcribe"
            ),
            vision_provider=vision_provider,
            vision_url=_loopback_url(
                read.get(
                    "ANIMA_VISION_URL",
                    "VEYRASOUL_VLM_URL",
                    default="http://127.0.0.1:8767",
                ),
                setting="ANIMA_VISION_URL",
            ),
            vision_timeout_seconds=read.number(
                "ANIMA_VISION_TIMEOUT", "VEYRASOUL_VLM_TIMEOUT", default=20.0, minimum=0.1, maximum=120.0
            ),
            vision_refresh_seconds=read.number(
                "ANIMA_VISION_REFRESH_SECONDS", "VEYRASOUL_VISION_REFRESH_SECONDS", default=5.0, minimum=1.0, maximum=300.0
            ),
            realtime_allow_anonymous=read.boolean(
                "ANIMA_REALTIME_ALLOW_ANONYMOUS",
                default=False,
            ),
            realtime_allowed_origins=_origins(
                read.get(
                    "ANIMA_REALTIME_ALLOWED_ORIGINS",
                    default=read.get(
                        "ANIMA_ALLOWED_ORIGINS",
                        default="https://anima.veyralux.org",
                    ),
                )
            ),
            realtime_reauth_seconds=read.number(
                "ANIMA_REALTIME_REAUTH_SECONDS",
                default=30.0,
                minimum=1.0,
                maximum=300.0,
            ),
            realtime_lease_renew_seconds=read.number(
                "ANIMA_REALTIME_LEASE_RENEW_SECONDS",
                default=60.0,
                minimum=1.0,
                maximum=240.0,
            ),
            toc=toc,
        )

    def capabilities(self) -> dict[str, str]:
        return self.provider_snapshot.capabilities()


class _Environment:
    def __init__(self, values: Mapping[str, str]) -> None:
        self.values = values

    def get(self, *names: str, default: str = "") -> str:
        for name in names:
            value = str(self.values.get(name, "")).strip()
            if value:
                return value
        return default

    def integer(
        self,
        *names: str,
        default: int,
        minimum: int,
        maximum: int,
    ) -> int:
        raw = self.get(*names, default=str(default))
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError(f"{names[0]} must be an integer") from exc
        if not minimum <= value <= maximum:
            raise ValueError(f"{names[0]} must be between {minimum} and {maximum}")
        return value

    def number(
        self,
        *names: str,
        default: float,
        minimum: float,
        maximum: float,
    ) -> float:
        raw = self.get(*names, default=str(default))
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError(f"{names[0]} must be a number") from exc
        if not minimum <= value <= maximum:
            raise ValueError(f"{names[0]} must be between {minimum} and {maximum}")
        return value

    def boolean(self, *names: str, default: bool) -> bool:
        raw = self.get(*names, default="true" if default else "false").lower()
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"{names[0]} must be a boolean")


def _provider(value: str) -> str | None:
    normalized = value.strip().lower().replace("_", "-")
    return None if normalized in _DISABLED else normalized


def _path(value: str, default: Path) -> Path:
    return (Path(value).expanduser() if value else default).resolve()


def _base_url(value: str, *, setting: str = "ANIMA_LLM_BASE_URL") -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(f"{setting} must not contain credentials, query, or fragment")
    if parsed.scheme == "https" and parsed.netloc:
        return normalized
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return normalized
    raise ValueError(f"{setting} must use HTTPS, except for a loopback development endpoint")


def _loopback_url(value: str, *, setting: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{setting} must be a credential-free loopback HTTP(S) URL")
    return normalized


def _origins(value: str) -> tuple[str, ...]:
    origins: list[str] = []
    for raw in value.split(","):
        normalized = raw.strip().rstrip("/").lower()
        if not normalized:
            continue
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("ANIMA_ALLOWED_ORIGINS must contain exact HTTP(S) origins")
        origins.append(normalized)
    return tuple(dict.fromkeys(origins))
