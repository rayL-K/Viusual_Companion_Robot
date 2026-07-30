"""Authenticated ToC REST API, isolated from the realtime gateway.

The router deliberately accepts dependencies from the composition root.  It
does not know how bearer tokens are verified, where the identity catalog
lives, or which embedding provider backs document ingestion.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Mapping, TypeAlias

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from veyrasoul.auth import AuthPrincipal
from veyrasoul.identity import AnimaId, InvalidIdentity, UserId
from veyrasoul.memory.ingestion import DocumentIngestor
from veyrasoul.personalization.catalog_model import (
    Anima,
    CatalogError,
    LifecycleConflictError,
    ObjectNotFoundError,
    ResourceBusyError,
    ResourceQuotaError,
    RevisionConflictError,
    User,
)
from veyrasoul.personalization.model import ProfileConflictError, ProfileValidationError
from veyrasoul.personalization.service import IdentityService


MAX_JSON_BYTES = 2_100_000
_ETAG_REVISION = re.compile(r'^(?:W/)?"([1-9][0-9]*)"$|^([1-9][0-9]*)$')


IdentityServiceProvider: TypeAlias = Callable[[], IdentityService]
DocumentIngestorFactory: TypeAlias = Callable[[UserId, AnimaId], DocumentIngestor]
PrincipalDependency: TypeAlias = Callable[..., AuthPrincipal]


def create_toc_router(
    *,
    principal_dependency: PrincipalDependency,
    mutation_principal_dependency: PrincipalDependency,
    identity_service_provider: IdentityServiceProvider,
    document_ingestor_factory: DocumentIngestorFactory,
) -> APIRouter:
    """Build a mountable router without importing the gateway composition root.

    ``principal_dependency`` authenticates safe reads.  Every state-changing
    route uses the separately required ``mutation_principal_dependency`` so a
    cookie-backed composition root cannot accidentally omit CSRF validation.
    There is intentionally no mutation fallback.
    """

    router = APIRouter(prefix="/v2", tags=["toc"])
    @router.get("/me")
    async def get_me(principal: AuthPrincipal = Depends(principal_dependency)) -> Response:
        return await _execute(
            lambda: _user_wire(identity_service_provider().get_user(principal.user_id))
        )

    @router.patch("/me")
    async def patch_me(
        request: Request,
        principal: AuthPrincipal = Depends(mutation_principal_dependency),
    ) -> Response:
        try:
            body = await _json_object(request)
            expected = _expected_revision(request, body)
            _only_fields(body, {"displayName", "expectedRevision"})
            name = _required_string(body, "displayName")
            return await _execute(
                lambda: _user_wire(
                    identity_service_provider().rename_user(principal.user_id, name, expected)
                )
            )
        except Exception as exc:
            return _error_response(exc)

    @router.get("/animas")
    async def list_animas(principal: AuthPrincipal = Depends(principal_dependency)) -> Response:
        return await _execute(
            lambda: {
                "items": [
                    _anima_wire(anima)
                    for anima in identity_service_provider().list_animas(principal.user_id)
                ]
            }
        )

    @router.post("/animas", status_code=201)
    async def create_anima(
        request: Request,
        principal: AuthPrincipal = Depends(mutation_principal_dependency),
    ) -> Response:
        try:
            body = await _json_object(request)
            _only_fields(body, {"id", "displayName"})
            anima_id = AnimaId.parse(_required_string(body, "id"))
            name = _required_string(body, "displayName")
            return await _execute(
                lambda: _anima_wire(
                    identity_service_provider().create_anima(principal.user_id, anima_id, name)
                ),
                success_status=201,
            )
        except Exception as exc:
            return _error_response(exc)

    @router.get("/animas/{anima_id}")
    async def get_anima(anima_id: str, principal: AuthPrincipal = Depends(principal_dependency)) -> Response:
        return await _execute(
            lambda: _anima_wire(
                identity_service_provider().get_anima(
                    principal.user_id, AnimaId.parse(anima_id)
                )
            )
        )

    @router.patch("/animas/{anima_id}")
    async def patch_anima(
        anima_id: str,
        request: Request,
        principal: AuthPrincipal = Depends(mutation_principal_dependency),
    ) -> Response:
        try:
            body = await _json_object(request)
            expected = _expected_revision(request, body)
            _only_fields(body, {"displayName", "expectedRevision"})
            name = _required_string(body, "displayName")
            return await _execute(
                lambda: _anima_wire(
                    identity_service_provider().rename_anima(
                        principal.user_id, AnimaId.parse(anima_id), name, expected
                    )
                )
            )
        except Exception as exc:
            return _error_response(exc)

    @router.delete("/animas/{anima_id}")
    async def delete_anima(
        anima_id: str,
        request: Request,
        principal: AuthPrincipal = Depends(mutation_principal_dependency),
    ) -> Response:
        try:
            body = await _optional_json_object(request)
            expected = _expected_revision(request, body)
            _only_fields(body, {"expectedRevision"})
            return await _execute(
                lambda: _anima_wire(
                    identity_service_provider().request_anima_deletion(
                        principal.user_id, AnimaId.parse(anima_id), expected
                    )
                )
            )
        except Exception as exc:
            return _error_response(exc)

    @router.get("/animas/{anima_id}/settings")
    async def get_settings(anima_id: str, principal: AuthPrincipal = Depends(principal_dependency)) -> Response:
        try:
            parsed_anima_id = AnimaId.parse(anima_id)

            def operation() -> dict[str, object]:
                service = identity_service_provider()
                with service.active_anima_lease(
                    principal.user_id, parsed_anima_id
                ):
                    return service.profile_store(
                        principal.user_id, parsed_anima_id
                    ).get().to_wire()

            return await _execute(operation)
        except Exception as exc:
            return _error_response(exc)

    @router.patch("/animas/{anima_id}/settings")
    async def patch_settings(
        anima_id: str,
        request: Request,
        principal: AuthPrincipal = Depends(mutation_principal_dependency),
    ) -> Response:
        try:
            body = await _json_object(request)
            body["expectedRevision"] = _expected_revision(request, body)
            parsed_anima_id = AnimaId.parse(anima_id)

            def operation() -> dict[str, object]:
                service = identity_service_provider()
                with service.active_anima_lease(
                    principal.user_id, parsed_anima_id
                ):
                    return service.profile_store(
                        principal.user_id, parsed_anima_id
                    ).update(body).to_wire()

            return await _execute(operation)
        except Exception as exc:
            return _error_response(exc)

    @router.post("/animas/{anima_id}/documents", status_code=201)
    async def ingest_document(
        anima_id: str,
        request: Request,
        principal: AuthPrincipal = Depends(mutation_principal_dependency),
    ) -> Response:
        try:
            body = await _json_object(request)
            _only_fields(body, {"id", "title", "text", "source", "metadata"})
            metadata = body.get("metadata")
            if metadata is not None and not isinstance(metadata, dict):
                raise ApiInputError("metadata 必须是 JSON 对象")
            parsed_anima_id = AnimaId.parse(anima_id)

            def operation() -> Any:
                service = identity_service_provider()
                with service.active_anima_lease(
                    principal.user_id, parsed_anima_id
                ):
                    document_id = _required_string(body, "id")
                    text = _required_string(body, "text")
                    size_bytes = len(text.encode("utf-8"))
                    if size_bytes > service.repository.quota.max_document_bytes:
                        raise DocumentTooLargeError
                    reservation = service.reserve_document_usage(
                        principal.user_id,
                        parsed_anima_id,
                        document_id,
                        size_bytes,
                    )
                    try:
                        result = document_ingestor_factory(
                            principal.user_id, parsed_anima_id
                        ).ingest(
                            document_id=document_id,
                            title=_required_string(body, "title"),
                            text=text,
                            source=_required_string(body, "source"),
                            metadata=metadata,
                        )
                        service.commit_document_usage(reservation)
                        return result
                    except BaseException:
                        service.rollback_document_usage(reservation)
                        raise

            ingested = await run_in_threadpool(operation)
            return JSONResponse(
                {
                    "id": ingested.document_id,
                    "contentHash": ingested.content_hash,
                    "chunkIds": list(ingested.chunk_ids),
                    "unchanged": ingested.unchanged,
                },
                status_code=200 if ingested.unchanged else 201,
            )
        except Exception as exc:
            return _error_response(exc)

    @router.delete("/animas/{anima_id}/documents/{document_id}")
    async def delete_document(
        anima_id: str,
        document_id: str,
        principal: AuthPrincipal = Depends(mutation_principal_dependency),
    ) -> Response:
        try:
            parsed_anima_id = AnimaId.parse(anima_id)

            def operation() -> bool:
                service = identity_service_provider()
                with service.active_anima_lease(
                    principal.user_id, parsed_anima_id
                ):
                    deleted = document_ingestor_factory(
                        principal.user_id, parsed_anima_id
                    ).delete(document_id)
                    service.release_document_usage(
                        principal.user_id, parsed_anima_id, document_id
                    )
                    return deleted

            deleted = await run_in_threadpool(operation)
            return JSONResponse({"id": document_id, "deleted": deleted})
        except Exception as exc:
            return _error_response(exc)

    return router


class ApiInputError(ValueError):
    """Malformed API input with a stable public error representation."""


async def _json_object(request: Request) -> dict[str, Any]:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            parsed_content_length = int(content_length)
        except ValueError as exc:
            raise ApiInputError("Content-Length 无效") from exc
        if parsed_content_length > MAX_JSON_BYTES:
            raise RequestTooLargeError
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_JSON_BYTES:
            raise RequestTooLargeError
        raw.extend(chunk)
    try:
        value = json.loads(bytes(raw))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiInputError("请求体必须是有效的 JSON") from exc
    if not isinstance(value, dict):
        raise ApiInputError("请求体必须是 JSON 对象")
    return value


async def _optional_json_object(request: Request) -> dict[str, Any]:
    if not request.headers.get("content-length"):
        return {}
    return await _json_object(request)


class RequestTooLargeError(ValueError):
    pass


class DocumentTooLargeError(ValueError):
    pass


def _expected_revision(request: Request, body: Mapping[str, Any]) -> int:
    body_revision = body.get("expectedRevision")
    header = request.headers.get("if-match")
    header_revision: int | None = None
    if header is not None:
        match = _ETAG_REVISION.fullmatch(header.strip())
        if match is None:
            raise ApiInputError('If-Match 必须是正整数 ETag，例如 "3"')
        header_revision = int(match.group(1) or match.group(2))
    if body_revision is not None and (
        isinstance(body_revision, bool)
        or not isinstance(body_revision, int)
        or body_revision < 1
    ):
        raise ApiInputError("expectedRevision 必须是正整数")
    if header_revision is not None and body_revision is not None:
        if header_revision != body_revision:
            raise ApiInputError("If-Match 与 expectedRevision 不一致")
    revision = header_revision if header_revision is not None else body_revision
    if revision is None:
        raise PreconditionRequiredError
    return int(revision)


class PreconditionRequiredError(ValueError):
    pass


def _only_fields(body: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = set(body) - allowed
    if unknown:
        raise ApiInputError(f"不支持的字段：{', '.join(sorted(unknown))}")


def _required_string(body: Mapping[str, Any], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ApiInputError(f"{key} 必须是非空字符串")
    return value


async def _execute(
    operation: Callable[[], dict[str, object]], *, success_status: int = 200
) -> Response:
    try:
        payload = await run_in_threadpool(operation)
        return JSONResponse(payload, status_code=success_status)
    except Exception as exc:
        return _error_response(exc)


def _error_response(exc: Exception) -> JSONResponse:
    status, code, message = _classify_error(exc)
    return JSONResponse(
        {"error": {"code": code, "message": message}},
        status_code=status,
    )


def _classify_error(exc: Exception) -> tuple[int, str, str]:
    if isinstance(exc, RequestTooLargeError):
        return 413, "request_too_large", "请求体超过大小限制"
    if isinstance(exc, DocumentTooLargeError):
        return 413, "document_too_large", "文档超过字节大小限制"
    if isinstance(exc, PreconditionRequiredError):
        return 428, "revision_required", "更新请求必须提供 If-Match 或 expectedRevision"
    if isinstance(exc, ObjectNotFoundError):
        return 404, "not_found", str(exc)
    if isinstance(exc, (RevisionConflictError, ProfileConflictError)):
        return 412, "revision_conflict", str(exc)
    if isinstance(exc, LifecycleConflictError):
        return 409, "lifecycle_conflict", str(exc)
    if isinstance(exc, ResourceBusyError):
        return 409, "resource_busy", str(exc)
    if isinstance(exc, ResourceQuotaError):
        return 429, "resource_quota_exceeded", str(exc)
    if isinstance(exc, (ApiInputError, InvalidIdentity, ProfileValidationError, ValueError)):
        return 400, "invalid_request", str(exc)
    if isinstance(exc, CatalogError):
        return 409, "catalog_conflict", str(exc)
    return 500, "internal_error", "服务器暂时无法完成请求"


def _user_wire(user: User) -> dict[str, object]:
    return {
        "id": user.id.value,
        "displayName": user.display_name,
        "state": user.state,
        "revision": user.revision,
        "createdAtMs": user.created_at_ms,
        "updatedAtMs": user.updated_at_ms,
    }


def _anima_wire(anima: Anima) -> dict[str, object]:
    return {
        "id": anima.id.value,
        "displayName": anima.display_name,
        "state": anima.state,
        "revision": anima.revision,
        "createdAtMs": anima.created_at_ms,
        "updatedAtMs": anima.updated_at_ms,
    }
