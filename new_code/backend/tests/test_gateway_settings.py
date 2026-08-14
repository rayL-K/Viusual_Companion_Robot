from pathlib import Path

import pytest

from veyrasoul.gateway.settings import RuntimeSettings


def _minimum_environment(tmp_path: Path) -> dict[str, str]:
    return {
        "ANIMA_LLM_API_KEY": "unit-test-secret",
        "ANIMA_TTS_MODEL_DIR": str(tmp_path / "tts"),
        "ANIMA_ASR_PROVIDER": "disabled",
        "ANIMA_VISION_PROVIDER": "disabled",
        "ANIMA_ADMISSION_REQUIRED": "false",
    }


def test_settings_support_a_portable_text_first_server_profile(tmp_path) -> None:
    settings = RuntimeSettings.from_environment(
        _minimum_environment(tmp_path),
        root=tmp_path,
    )

    assert settings.asr_provider is None
    assert settings.vision_provider is None
    assert settings.capabilities() == {
        "llm": "deepseek",
        "tts": "sherpa",
        "asr": "disabled",
        "vision": "disabled",
    }
    assert settings.data_root == (tmp_path / "data").resolve()
    assert settings.realtime_allow_anonymous is False
    assert settings.admission.max_concurrent_asr_requests == 2
    assert settings.admission.max_asr_requests_per_client_per_minute == 12
    assert settings.admission.max_asr_requests_global_per_minute == 48
    assert settings.admission.pcm_bytes_per_second == 32_000
    assert settings.admission.pcm_burst_bytes == 32_000
    assert settings.websocket_send_timeout_seconds == 5.0
    assert "unit-test-secret" not in repr(settings)


def test_pcm_burst_cannot_exceed_one_second_of_media_time(tmp_path) -> None:
    environment = _minimum_environment(tmp_path)
    environment["ANIMA_PCM_BYTES_PER_SECOND"] = "32000"
    environment["ANIMA_PCM_BURST_BYTES"] = "32001"

    with pytest.raises(ValueError, match="PCM burst"):
        RuntimeSettings.from_environment(environment, root=tmp_path)


def test_anonymous_realtime_requires_explicit_development_opt_in(tmp_path) -> None:
    environment = _minimum_environment(tmp_path)
    environment["ANIMA_REALTIME_ALLOW_ANONYMOUS"] = "true"

    settings = RuntimeSettings.from_environment(environment, root=tmp_path)

    assert settings.realtime_allow_anonymous is True


def test_cloud_audio_needs_no_local_models_and_hides_server_key(tmp_path) -> None:
    environment = _minimum_environment(tmp_path)
    environment.pop("ANIMA_TTS_MODEL_DIR")
    environment.update(
        {
            "ANIMA_TTS_PROVIDER": "openai-compatible",
            "ANIMA_ASR_PROVIDER": "openai-compatible",
            "ANIMA_AUDIO_API_KEY": "server-audio-secret",
            "ANIMA_AUDIO_BASE_URL": "https://audio.example/v1",
        }
    )
    settings = RuntimeSettings.from_environment(environment, root=tmp_path)
    assert settings.tts_model_dir is None
    assert settings.asr_model_dir is None
    assert settings.tts_streaming_enabled is False
    assert settings.capabilities()["asr"] == "openai-compatible"
    assert "server-audio-secret" not in repr(settings)


def test_cloud_audio_read_timeout_matches_adapter_limit(tmp_path) -> None:
    environment = _minimum_environment(tmp_path)
    environment["ANIMA_AUDIO_READ_TIMEOUT_SECONDS"] = "121"

    with pytest.raises(ValueError, match="ANIMA_AUDIO_READ_TIMEOUT_SECONDS"):
        RuntimeSettings.from_environment(environment, root=tmp_path)


def test_cloud_tts_streaming_requires_explicit_validated_binding_opt_in(tmp_path) -> None:
    environment = _minimum_environment(tmp_path)
    environment.pop("ANIMA_TTS_MODEL_DIR")
    environment.update(
        {
            "ANIMA_TTS_PROVIDER": "openai-compatible",
            "ANIMA_AUDIO_API_KEY": "server-audio-secret",
            "ANIMA_TTS_STREAMING_ENABLED": "true",
        }
    )
    settings = RuntimeSettings.from_environment(environment, root=tmp_path)
    assert settings.tts_streaming_enabled is True


def test_streaming_flag_cannot_be_applied_to_unvalidated_local_binding(tmp_path) -> None:
    environment = _minimum_environment(tmp_path)
    environment["ANIMA_TTS_STREAMING_ENABLED"] = "true"
    with pytest.raises(ValueError, match="openai-compatible"):
        RuntimeSettings.from_environment(environment, root=tmp_path)


def test_cloud_audio_rejects_missing_key(tmp_path) -> None:
    environment = _minimum_environment(tmp_path)
    environment.pop("ANIMA_TTS_MODEL_DIR")
    environment["ANIMA_TTS_PROVIDER"] = "openai-compatible"
    with pytest.raises(ValueError, match="ANIMA_AUDIO_API_KEY"):
        RuntimeSettings.from_environment(environment, root=tmp_path)


def _toc_environment(tmp_path: Path) -> dict[str, str]:
    environment = _minimum_environment(tmp_path)
    environment.update(
        {
            "ANIMA_TOC_ENABLED": "true",
            "ANIMA_OIDC_ISSUER": "https://identity.example",
            "ANIMA_OIDC_AUDIENCE": "anima",
            "ANIMA_OIDC_JWKS_URL": "https://identity.example/.well-known/jwks.json",
            "ANIMA_OIDC_AUTHORIZATION_ENDPOINT": "https://identity.example/authorize",
            "ANIMA_OIDC_TOKEN_ENDPOINT": "https://identity.example/token",
            "ANIMA_OIDC_CLIENT_ID": "anima-web",
            "ANIMA_OIDC_REDIRECT_URI": "https://anima.example/auth/callback",
            "ANIMA_AUTH_DATABASE": str(tmp_path / "auth.sqlite3"),
            "ANIMA_LOGIN_FERNET_KEY": "secret-fernet-material",
        }
    )
    return environment


def test_enabled_toc_fails_closed_when_any_required_setting_is_missing(tmp_path) -> None:
    environment = _minimum_environment(tmp_path)
    environment["ANIMA_TOC_ENABLED"] = "true"

    with pytest.raises(ValueError, match="ANIMA_OIDC_ISSUER") as rejected:
        RuntimeSettings.from_environment(environment, root=tmp_path)

    assert "ANIMA_AUTH_DATABASE" in str(rejected.value)
    assert "ANIMA_LOGIN_FERNET_KEY" in str(rejected.value)


def test_enabled_toc_settings_are_complete_and_hide_login_key(tmp_path) -> None:
    environment = _toc_environment(tmp_path)
    environment["ANIMA_LOGIN_FERNET_KEY"] = "do-not-print-this-key"

    settings = RuntimeSettings.from_environment(environment, root=tmp_path)

    assert settings.toc.enabled is True
    assert settings.toc.auth_database == (tmp_path / "auth.sqlite3").resolve()
    assert settings.realtime_allow_anonymous is False
    assert "do-not-print-this-key" not in repr(settings)


def test_toc_cannot_enable_anonymous_realtime(tmp_path) -> None:
    environment = _toc_environment(tmp_path)
    environment["ANIMA_REALTIME_ALLOW_ANONYMOUS"] = "true"

    with pytest.raises(ValueError, match="must be false"):
        RuntimeSettings.from_environment(environment, root=tmp_path)


def test_settings_keep_legacy_model_mount_names_during_migration(tmp_path) -> None:
    environment = {
        "DEEPSEEK_API_KEY": "legacy-secret",
        "VEYRASOUL_TTS_MODEL_DIR": str(tmp_path / "tts"),
        "VEYRASOUL_ASR_MODEL_DIR": str(tmp_path / "asr"),
        "VEYRASOUL_VISION_REFRESH_SECONDS": "5",
        "ANIMA_ADMISSION_REQUIRED": "false",
    }

    settings = RuntimeSettings.from_environment(environment, root=tmp_path)

    assert settings.tts_model_dir == tmp_path / "tts"
    assert settings.asr_model_dir == tmp_path / "asr"
    assert settings.vision_refresh_seconds == 5.0
    assert "legacy-secret" not in repr(settings)


def test_selected_provider_requires_its_assets(tmp_path) -> None:
    environment = _minimum_environment(tmp_path)
    environment["ANIMA_ASR_PROVIDER"] = "sherpa"

    with pytest.raises(ValueError, match="ANIMA_ASR_MODEL_DIR"):
        RuntimeSettings.from_environment(environment, root=tmp_path)


def test_external_plain_http_llm_endpoint_is_rejected(tmp_path) -> None:
    environment = _minimum_environment(tmp_path)
    environment["ANIMA_LLM_BASE_URL"] = "http://api.example.test"

    with pytest.raises(ValueError, match="must use HTTPS"):
        RuntimeSettings.from_environment(environment, root=tmp_path)


def test_loopback_http_llm_endpoint_is_allowed_for_development(tmp_path) -> None:
    environment = _minimum_environment(tmp_path)
    environment["ANIMA_LLM_BASE_URL"] = "http://127.0.0.1:9000/"

    settings = RuntimeSettings.from_environment(environment, root=tmp_path)

    assert settings.llm_base_url == "http://127.0.0.1:9000"


@pytest.mark.parametrize(
    "url",
    (
        "https://user:password@example.com",
        "https://example.com?token=secret",
        "https://example.com#secret",
    ),
)
def test_llm_url_rejects_embedded_secret_material(tmp_path, url: str) -> None:
    environment = _minimum_environment(tmp_path)
    environment["ANIMA_LLM_BASE_URL"] = url

    with pytest.raises(ValueError, match="credentials, query, or fragment"):
        RuntimeSettings.from_environment(environment, root=tmp_path)


@pytest.mark.parametrize(
    "url",
    (
        "http://camera-collector.example.com",
        "https://camera-collector.example.com",
        "http://user:password@127.0.0.1:8767",
    ),
)
def test_local_vision_provider_is_pinned_to_loopback(tmp_path, url: str) -> None:
    environment = _minimum_environment(tmp_path)
    environment["ANIMA_VISION_PROVIDER"] = "local-vlm"
    environment["ANIMA_VISION_URL"] = url

    with pytest.raises(ValueError, match="loopback"):
        RuntimeSettings.from_environment(environment, root=tmp_path)


def test_short_telemetry_hmac_key_is_rejected(tmp_path) -> None:
    environment = _minimum_environment(tmp_path)
    environment["ANIMA_TELEMETRY_HMAC_KEY"] = "too-short"

    with pytest.raises(ValueError, match="at least 32 bytes"):
        RuntimeSettings.from_environment(environment, root=tmp_path)


def test_required_public_admission_is_fail_closed_and_hides_secret(tmp_path) -> None:
    environment = _minimum_environment(tmp_path)
    environment["ANIMA_ADMISSION_REQUIRED"] = "true"
    with pytest.raises(ValueError, match="admission secret"):
        RuntimeSettings.from_environment(environment, root=tmp_path)

    environment["ANIMA_ADMISSION_SECRET"] = "a" * 32
    environment["ANIMA_TURNSTILE_SITE_KEY"] = "unit-test-site-key"
    environment["ANIMA_TURNSTILE_SECRET"] = "unit-test-turnstile-secret"
    settings = RuntimeSettings.from_environment(environment, root=tmp_path)
    assert settings.admission.required is True
    assert settings.admission.allowed_origins == ("https://anima.veyralux.org",)
    assert "a" * 32 not in repr(settings)


def test_public_admission_is_fail_closed_by_default(tmp_path) -> None:
    environment = _minimum_environment(tmp_path)
    environment.pop("ANIMA_ADMISSION_REQUIRED")

    with pytest.raises(ValueError, match="admission secret"):
        RuntimeSettings.from_environment(environment, root=tmp_path)


def test_allowed_origins_must_be_exact_origins(tmp_path) -> None:
    environment = _minimum_environment(tmp_path)
    environment.update(
        {
            "ANIMA_ADMISSION_REQUIRED": "true",
            "ANIMA_ADMISSION_SECRET": "a" * 32,
            "ANIMA_TURNSTILE_SITE_KEY": "unit-test-site-key",
            "ANIMA_TURNSTILE_SECRET": "unit-test-turnstile-secret",
            "ANIMA_ALLOWED_ORIGINS": "https://anima.veyralux.org/path",
        }
    )

    with pytest.raises(ValueError, match="exact HTTP"):
        RuntimeSettings.from_environment(environment, root=tmp_path)
