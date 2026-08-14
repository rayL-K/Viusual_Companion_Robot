from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

import veyrasoul.gateway.toc_api as toc_api
from veyrasoul.auth import AuthPrincipal
from veyrasoul.gateway.toc_api import (
    MAX_JSON_BYTES,
    RequestTooLargeError,
    _classify_error,
    _json_object,
    create_toc_router,
)
from veyrasoul.identity import AnimaId, UserId
from veyrasoul.memory.ingestion import IngestedDocument
from veyrasoul.personalization import (
    DataLayout,
    IdentityService,
    ResourceQuotaConfig,
    ResourceBusyError,
    SqliteIdentityRepository,
)
from veyrasoul.providers import AvailableProvider, Capability, Locality


@dataclass
class FakeIngestor:
    owner: UserId
    anima: AnimaId
    deleted: list[str]

    def ingest(
        self,
        *,
        document_id: str,
        title: str,
        text: str,
        source: str,
        metadata: dict[str, object] | None = None,
    ) -> IngestedDocument:
        del title, source, metadata
        return IngestedDocument(document_id, f"hash-{len(text)}", ("chunk-1",))

    def delete(self, document_id: str) -> bool:
        self.deleted.append(document_id)
        return True


def api(
    tmp_path,
    quota: ResourceQuotaConfig | None = None,
    provider_catalog: tuple[AvailableProvider, ...] | None = None,
) -> tuple[TestClient, dict[str, UserId], list[tuple[UserId, AnimaId]]]:
    layout = DataLayout(tmp_path / "data", tmp_path / "legacy.db")
    service = IdentityService(
        SqliteIdentityRepository(
            layout.identity_database(), quota or ResourceQuotaConfig()
        ),
        layout,
        "默认人设",
    )
    alice = UserId.parse("alice")
    bob = UserId.parse("bob")
    service.create_user(alice, "Alice")
    service.create_user(bob, "Bob")
    service.create_anima(alice, AnimaId.parse("rabbit"), "月兔")
    service.create_anima(bob, AnimaId.parse("fox"), "小狐")
    current = {"user": alice}
    factory_calls: list[tuple[UserId, AnimaId]] = []
    auth_counts = {"read": 0, "mutation": 0}

    def make_principal() -> AuthPrincipal:
        return AuthPrincipal(
            user_id=current["user"],
            session_id="session-1",
            authenticated_at_ms=1,
            expires_at_ms=9_999_999_999_999,
            oidc_issuer="https://issuer.example",
        )

    def principal() -> AuthPrincipal:
        auth_counts["read"] += 1
        return make_principal()

    def mutation_principal() -> AuthPrincipal:
        auth_counts["mutation"] += 1
        return make_principal()

    def ingestor_factory(owner: UserId, anima: AnimaId) -> FakeIngestor:
        factory_calls.append((owner, anima))
        return FakeIngestor(owner, anima, [])

    app = FastAPI()
    app.include_router(
        create_toc_router(
            principal_dependency=principal,
            mutation_principal_dependency=mutation_principal,
            identity_service_provider=lambda: service,
            document_ingestor_factory=ingestor_factory,
            provider_catalog_provider=lambda: provider_catalog or (),
        )
    )
    app.state.auth_counts = auth_counts
    return TestClient(app), current, factory_calls


def test_me_and_anima_crud_use_authenticated_actor(tmp_path) -> None:
    client, current, _ = api(tmp_path)

    assert client.get("/v2/me").json()["id"] == "alice"
    created = client.post(
        "/v2/animas", json={"id": "owl", "displayName": "小鸮"}
    )
    assert created.status_code == 201
    assert [item["id"] for item in client.get("/v2/animas").json()["items"]] == [
        "rabbit",
        "owl",
    ]

    updated = client.patch(
        "/v2/animas/owl",
        headers={"If-Match": '"1"'},
        json={"displayName": "夜鸮"},
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2

    current["user"] = UserId.parse("bob")
    hidden = client.get("/v2/animas/owl")
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "not_found"


def test_revision_preconditions_are_strict_and_errors_are_uniform(tmp_path) -> None:
    client, _, _ = api(tmp_path)

    missing = client.patch("/v2/animas/rabbit", json={"displayName": "新名字"})
    assert missing.status_code == 428
    assert missing.json() == {
        "error": {
            "code": "revision_required",
            "message": "更新请求必须提供 If-Match 或 expectedRevision",
        }
    }

    disagreement = client.patch(
        "/v2/animas/rabbit",
        headers={"If-Match": '"1"'},
        json={"displayName": "新名字", "expectedRevision": 2},
    )
    assert disagreement.status_code == 400
    assert disagreement.json()["error"]["code"] == "invalid_request"

    first = client.patch(
        "/v2/animas/rabbit",
        headers={"If-Match": '"1"'},
        json={"displayName": "新名字"},
    )
    assert first.status_code == 200
    stale = client.patch(
        "/v2/animas/rabbit",
        headers={"If-Match": '"1"'},
        json={"displayName": "旧编辑器"},
    )
    assert stale.status_code == 412
    assert stale.json()["error"]["code"] == "revision_conflict"


def test_settings_preserve_profile_revision_contract(tmp_path) -> None:
    client, _, _ = api(tmp_path)

    settings = client.get("/v2/animas/rabbit/settings")
    assert settings.status_code == 200
    assert settings.json()["revision"] == 1

    changed = client.patch(
        "/v2/animas/rabbit/settings",
        headers={"If-Match": '"1"'},
        json={"maxReplyChars": 320, "voiceId": "warm.zh"},
    )
    assert changed.status_code == 200
    assert changed.json()["maxReplyChars"] == 320
    assert changed.json()["revision"] == 2

    stale = client.patch(
        "/v2/animas/rabbit/settings",
        json={"expectedRevision": 1, "replyDelayMs": 100},
    )
    assert stale.status_code == 412


def test_provider_catalog_exposes_only_injected_runtime_bindings(tmp_path) -> None:
    available = (
        AvailableProvider(
            Capability.LLM,
            "dialogue-fast",
            Locality.CLOUD,
            ("dialogue-v2",),
        ),
        AvailableProvider(
            Capability.TTS,
            "voice-warm",
            Locality.LOCAL,
            ("acoustic-v1",),
            ("warm.zh",),
        ),
    )
    client, _, _ = api(tmp_path, provider_catalog=available)

    response = client.get("/v2/providers")
    assert response.status_code == 200
    assert response.json() == {
        "revision": 1,
        "items": [item.as_dict() for item in available],
    }
    assert "apiKey" not in response.text
    assert "baseUrl" not in response.text


def test_provider_catalog_is_empty_when_composition_does_not_inject_bindings(
    tmp_path,
) -> None:
    client, _, _ = api(tmp_path)

    assert client.get("/v2/providers").json() == {"revision": 1, "items": []}


def test_settings_provider_selection_is_allowlisted_and_owner_scoped(tmp_path) -> None:
    client, current, _ = api(tmp_path)

    changed = client.patch(
        "/v2/animas/rabbit/settings",
        headers={"If-Match": '"1"'},
        json={
            "providers": {
                "llm": {
                    "provider": "deepseek",
                    "config": {"model": "deepseek-chat"},
                },
                "tts": {
                    "provider": "sherpa",
                    "config": {"model": "matcha", "voice": "warm.zh"},
                },
                "asr": {"provider": "sherpa", "config": {"model": "zipformer"}},
                "vision": {"provider": "local-vlm", "config": {"model": "qwen-vl"}},
            }
        },
    )
    assert changed.status_code == 200
    assert changed.json()["providers"]["tts"]["config"] == {
        "model": "matcha",
        "voice": "warm.zh",
    }

    current["user"] = UserId.parse("bob")
    hidden = client.get("/v2/animas/rabbit/settings")
    assert hidden.status_code == 404
    stolen = client.patch(
        "/v2/animas/rabbit/settings",
        headers={"If-Match": '"2"'},
        json={"providers": {"llm": "deepseek"}},
    )
    assert stolen.status_code == 404


@pytest.mark.parametrize(
    "providers",
    [
        {"llm": "unregistered"},
        {"llm": {"provider": "deepseek", "config": {"api_key": "secret"}}},
        {"vision": {"provider": "local-vlm", "config": {"base_url": "https://evil"}}},
    ],
)
def test_settings_reject_invalid_or_secret_provider_selection(tmp_path, providers) -> None:
    client, _, _ = api(tmp_path)

    response = client.patch(
        "/v2/animas/rabbit/settings",
        headers={"If-Match": '"1"'},
        json={"providers": providers},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_documents_are_owner_scoped_and_size_limited(tmp_path) -> None:
    client, current, calls = api(tmp_path)

    ingested = client.post(
        "/v2/animas/rabbit/documents",
        json={
            "id": "manual",
            "title": "手册",
            "text": "可信知识正文",
            "source": "user-upload",
            "metadata": {"language": "zh"},
        },
    )
    assert ingested.status_code == 201
    assert ingested.json()["chunkIds"] == ["chunk-1"]
    assert calls == [(UserId.parse("alice"), AnimaId.parse("rabbit"))]

    deleted = client.delete("/v2/animas/rabbit/documents/manual")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    current["user"] = UserId.parse("bob")
    forbidden_as_missing = client.post(
        "/v2/animas/rabbit/documents",
        json={
            "id": "stolen",
            "title": "越权",
            "text": "不能写入",
            "source": "test",
        },
    )
    assert forbidden_as_missing.status_code == 404
    assert calls[-1] == (UserId.parse("alice"), AnimaId.parse("rabbit"))

    oversized = client.post(
        "/v2/animas/fox/documents",
        content=b"{" + b"x" * MAX_JSON_BYTES + b"}",
        headers={"content-type": "application/json"},
    )
    assert oversized.status_code == 413
    assert oversized.json()["error"]["code"] == "request_too_large"


def test_chunked_json_body_stops_when_limit_is_crossed() -> None:
    delivered = 0
    chunks = [
        b"{" + b"x" * (MAX_JSON_BYTES - 6),
        b"xxxxxxxxxx",
        b"}",
    ]

    async def receive():
        nonlocal delivered
        chunk = chunks[delivered]
        delivered += 1
        return {
            "type": "http.request",
            "body": chunk,
            "more_body": delivered < len(chunks),
        }

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "server": ("test", 80),
            "client": ("test", 1),
            "scheme": "http",
        },
        receive,
    )
    with pytest.raises(RequestTooLargeError):
        asyncio.run(_json_object(request))
    assert delivered == 2


def test_tenant_resource_quotas_return_stable_http_errors(tmp_path) -> None:
    client, _, calls = api(
        tmp_path,
        ResourceQuotaConfig(
            max_animas_per_user=2,
            max_document_bytes=12,
            max_documents_per_anima=1,
            max_document_bytes_per_user=12,
        ),
    )
    anima_limit = client.post(
        "/v2/animas", json={"id": "second", "displayName": "第二个"}
    )
    assert anima_limit.status_code == 201
    exceeded_animas = client.post(
        "/v2/animas", json={"id": "third", "displayName": "第三个"}
    )
    assert exceeded_animas.status_code == 429
    assert exceeded_animas.json()["error"]["code"] == "resource_quota_exceeded"

    first = client.post(
        "/v2/animas/rabbit/documents",
        json={
            "id": "one",
            "title": "一",
            "text": "123456",
            "source": "test",
        },
    )
    assert first.status_code == 201
    too_many = client.post(
        "/v2/animas/rabbit/documents",
        json={
            "id": "two",
            "title": "二",
            "text": "1",
            "source": "test",
        },
    )
    assert too_many.status_code == 429
    assert too_many.json()["error"]["code"] == "resource_quota_exceeded"

    user_bytes = client.post(
        "/v2/animas/second/documents",
        json={
            "id": "total",
            "title": "总量",
            "text": "1234567",
            "source": "test",
        },
    )
    assert user_bytes.status_code == 429
    assert user_bytes.json()["error"]["code"] == "resource_quota_exceeded"

    too_large = client.post(
        "/v2/animas/second/documents",
        json={
            "id": "large",
            "title": "大",
            "text": "中文中文中文",
            "source": "test",
        },
    )
    assert too_large.status_code == 413
    assert too_large.json()["error"]["code"] == "document_too_large"
    assert calls[-1] == (UserId.parse("alice"), AnimaId.parse("rabbit"))
    assert _classify_error(ResourceBusyError("busy"))[:2] == (
        409,
        "resource_busy",
    )


def test_delete_anima_is_revisioned_soft_delete(tmp_path) -> None:
    client, _, _ = api(tmp_path)

    deleted = client.delete(
        "/v2/animas/rabbit", headers={"If-Match": 'W/"1"'}
    )
    assert deleted.status_code == 200
    assert deleted.json()["state"] == "deleting"
    assert deleted.json()["revision"] == 2

    repeated = client.delete(
        "/v2/animas/rabbit", headers={"If-Match": '"2"'}
    )
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "lifecycle_conflict"


def test_deleting_anima_rejects_document_writes_before_factory_call(tmp_path) -> None:
    client, _, calls = api(tmp_path)
    deleting = client.delete(
        "/v2/animas/rabbit", headers={"If-Match": '"1"'}
    )
    assert deleting.status_code == 200
    assert calls == []

    ingest = client.post(
        "/v2/animas/rabbit/documents",
        json={
            "id": "late-write",
            "title": "删除期间写入",
            "text": "不得重建已经开始清理的数据",
            "source": "test",
        },
    )
    assert ingest.status_code == 409
    assert ingest.json()["error"]["code"] == "lifecycle_conflict"
    assert calls == []

    delete = client.delete("/v2/animas/rabbit/documents/existing")
    assert delete.status_code == 409
    assert delete.json()["error"]["code"] == "lifecycle_conflict"
    assert calls == []


def test_reads_and_every_mutation_use_separate_auth_dependencies(
    tmp_path, monkeypatch
) -> None:
    client, _, _ = api(tmp_path)
    counts = client.app.state.auth_counts
    threadpool_dispatches = 0
    original_run_in_threadpool = toc_api.run_in_threadpool

    async def counted_run_in_threadpool(function, *args, **kwargs):
        nonlocal threadpool_dispatches
        threadpool_dispatches += 1
        return await original_run_in_threadpool(function, *args, **kwargs)

    monkeypatch.setattr(toc_api, "run_in_threadpool", counted_run_in_threadpool)

    for path in (
        "/v2/me",
        "/v2/animas",
        "/v2/providers",
        "/v2/animas/rabbit",
        "/v2/animas/rabbit/settings",
    ):
        before = dict(counts)
        assert client.get(path).status_code == 200
        assert counts == {
            "read": before["read"] + 1,
            "mutation": before["mutation"],
        }

    mutation_requests = (
        lambda: client.patch(
            "/v2/me",
            headers={"If-Match": '"1"'},
            json={"displayName": "Alice Updated"},
        ),
        lambda: client.post(
            "/v2/animas", json={"id": "owl", "displayName": "小鸮"}
        ),
        lambda: client.patch(
            "/v2/animas/rabbit",
            headers={"If-Match": '"1"'},
            json={"displayName": "月兔二号"},
        ),
        lambda: client.patch(
            "/v2/animas/rabbit/settings",
            headers={"If-Match": '"1"'},
            json={"maxReplyChars": 240},
        ),
        lambda: client.post(
            "/v2/animas/rabbit/documents",
            json={
                "id": "facts",
                "title": "事实",
                "text": "一条事实",
                "source": "test",
            },
        ),
        lambda: client.delete("/v2/animas/rabbit/documents/facts"),
        lambda: client.delete(
            "/v2/animas/owl", headers={"If-Match": '"1"'}
        ),
    )
    for mutate in mutation_requests:
        before = dict(counts)
        response = mutate()
        assert response.status_code < 400, response.text
        assert counts == {
            "read": before["read"],
            "mutation": before["mutation"] + 1,
        }
    assert threadpool_dispatches == 11
