from types import SimpleNamespace

from veyrasoul.gateway.__main__ import (
    WS_MAX_MESSAGE_BYTES,
    _release_digest,
    _server_options,
)


def test_release_digest_binds_health_to_manifest(tmp_path) -> None:
    assert _release_digest(tmp_path) == "development"
    (tmp_path / ".release.sha256").write_text("abc  file\n", encoding="utf-8")

    digest = _release_digest(tmp_path)

    assert len(digest) == 64
    assert digest != "development"


def test_uvicorn_transport_limits_bound_pre_application_websocket_memory() -> None:
    settings = SimpleNamespace(host="127.0.0.1", port=8875, log_level="info")

    options = _server_options(settings)  # type: ignore[arg-type]

    assert options["ws"] == "websockets-sansio"
    assert options["ws_max_size"] == WS_MAX_MESSAGE_BYTES == 1_600_000
    assert options["ws_max_queue"] == 2
    assert options["ws_per_message_deflate"] is False
    assert options["limit_concurrency"] == 64
    assert options["access_log"] is False
