from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from veyrasoul.auth import VerifiedOidcIdentity
from veyrasoul.gateway import __main__ as gateway_main
from veyrasoul.gateway.settings import RuntimeSettings


class _Llm:
    async def stream_reply(self, messages):
        del messages
        yield "你好。"

    async def aclose(self) -> None:
        return None


class _Tts:
    async def warmup(self) -> None:
        return None

    async def synthesize(self, request):
        del request
        return b"RIFF", "audio/wav"


class _Verifier:
    def verify(self, id_token: str, expected_nonce: str) -> VerifiedOidcIdentity:
        assert id_token == "mock-id-token"
        assert expected_nonce
        return VerifiedOidcIdentity(
            issuer="https://identity.example",
            subject="alice-subject",
            display_name="Alice",
        )


def _settings(tmp_path) -> RuntimeSettings:
    persona = tmp_path / "persona.md"
    persona.write_text("温柔、自然、简洁。", encoding="utf-8")
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<main>Anima</main>", encoding="utf-8")
    return RuntimeSettings.from_environment(
        {
            "ANIMA_LLM_API_KEY": "test-key",
            "ANIMA_TTS_MODEL_DIR": str(tmp_path / "tts"),
            "ANIMA_ASR_PROVIDER": "disabled",
            "ANIMA_VISION_PROVIDER": "disabled",
            "ANIMA_ADMISSION_REQUIRED": "false",
            "ANIMA_PERSONA_PATH": str(persona),
            "ANIMA_WEB_DIST": str(web),
            "ANIMA_DATA_ROOT": str(tmp_path / "data"),
            "ANIMA_MEMORY_PATH": str(tmp_path / "legacy.db"),
            "ANIMA_TOC_ENABLED": "true",
            "ANIMA_OIDC_ISSUER": "https://identity.example",
            "ANIMA_OIDC_AUDIENCE": "anima",
            "ANIMA_OIDC_JWKS_URL": "https://identity.example/jwks",
            "ANIMA_OIDC_AUTHORIZATION_ENDPOINT": "https://identity.example/authorize",
            "ANIMA_OIDC_TOKEN_ENDPOINT": "https://identity.example/token",
            "ANIMA_OIDC_CLIENT_ID": "anima-web",
            "ANIMA_OIDC_REDIRECT_URI": "https://anima.example/auth/callback",
            "ANIMA_AUTH_DATABASE": str(tmp_path / "auth.sqlite3"),
            "ANIMA_LOGIN_FERNET_KEY": Fernet.generate_key().decode("ascii"),
        },
        root=tmp_path,
    )


def test_enabled_toc_mounts_auth_rest_and_websocket_on_one_principal(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        gateway_main,
        "DeepSeekStreamClient",
        lambda _config: _Llm(),
    )
    monkeypatch.setattr(
        gateway_main,
        "SherpaTtsSynthesizer",
        lambda _config: _Tts(),
    )
    exchanges: list[str] = []

    def exchange(request: httpx.Request) -> httpx.Response:
        exchanges.append(str(request.url))
        return httpx.Response(200, json={"id_token": "mock-id-token"})

    app = gateway_main.build_app(
        _settings(tmp_path),
        oidc_verifier=_Verifier(),
        oidc_token_transport=httpx.MockTransport(exchange),
    )

    with TestClient(
        app,
        base_url="https://anima.example",
        follow_redirects=False,
    ) as client:
        login = client.get("/auth/login")
        assert login.status_code == 302
        query = parse_qs(urlsplit(login.headers["location"]).query)
        assert query["client_id"] == ["anima-web"]
        assert query["code_challenge_method"] == ["S256"]

        callback = client.get(
            "/auth/callback",
            params={"code": "mock-code", "state": query["state"][0]},
        )
        assert callback.status_code in {200, 303}
        assert exchanges == ["https://identity.example/token"]

        me = client.get("/v2/me")
        assert me.status_code == 200
        user_id = me.json()["id"]
        csrf = client.cookies.get("__Host-anima_csrf")
        assert csrf

        created = client.post(
            "/v2/animas",
            json={"id": "rabbit", "displayName": "月兔"},
            headers={"X-CSRF-Token": csrf},
        )
        assert created.status_code == 201

        access = client.cookies.get("__Host-anima_session")
        assert access
        with client.websocket_connect(
            "/v2/realtime?session=same-principal&anima=rabbit",
            headers={
                "cookie": f"__Host-anima_session={access}",
                "origin": "https://anima.veyralux.org",
            },
        ) as websocket:
            ready = websocket.receive_json()
            assert ready["type"] == "session.ready"
            assert ready["payload"]["userId"] == user_id
            assert ready["payload"]["animaId"] == "rabbit"
            assert ready["payload"]["anonymous"] is False

        # Static mount is last: it serves the SPA without shadowing auth/API routes.
        assert client.get("/").text == "<main>Anima</main>"
        assert client.get("/v2/me").json()["id"] == user_id
