"""Fail-closed production composition for authenticated ToC services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fastapi import APIRouter

from veyrasoul.auth import (
    AuthConfig,
    AuthRepository,
    AuthService,
    HttpSessionBoundary,
    IssuedSession,
    OidcVerifier,
    SessionCookieConfig,
    VerifiedOidcIdentity,
)
from veyrasoul.identity import UserId
from veyrasoul.auth.login import (
    AuthorizationCodeExchanger,
    LoginAttemptStore,
    LoginFlowConfig,
    OidcLoginFlow,
)
from veyrasoul.personalization import (
    CatalogError,
    IdentityService,
    ObjectNotFoundError,
)

from .toc_api import (
    DocumentIngestorFactory,
    ProviderCatalogProvider,
    create_toc_router,
)


class TocConfigurationError(RuntimeError):
    """A required production authentication dependency is absent."""


@dataclass(frozen=True, slots=True)
class TocComposition:
    auth_service: AuthService
    identity_service: IdentityService
    session_boundary: HttpSessionBoundary
    cookie_config: SessionCookieConfig
    sign_in: Callable[[str, str], IssuedSession]
    router: APIRouter

    @property
    def access_cookie_name(self) -> str:
        """The sole cookie name passed to AppServices realtime authentication."""

        return self.cookie_config.access_cookie_name


def create_toc_composition(
    *,
    oidc_verifier: OidcVerifier | None,
    auth_repository: AuthRepository | None,
    identity_service: IdentityService | None,
    document_ingestor_factory: DocumentIngestorFactory | None,
    provider_catalog_provider: ProviderCatalogProvider | None = None,
    auth_config: AuthConfig | None = None,
    cookie_config: SessionCookieConfig | None = None,
) -> TocComposition:
    """Build the production ToC boundary or reject incomplete configuration."""

    missing = [
        name
        for name, dependency in (
            ("oidc_verifier", oidc_verifier),
            ("auth_repository", auth_repository),
            ("identity_service", identity_service),
            ("document_ingestor_factory", document_ingestor_factory),
        )
        if dependency is None
    ]
    if missing:
        raise TocConfigurationError(
            f"ToC 认证未完整配置：{', '.join(missing)}"
        )
    assert oidc_verifier is not None
    assert auth_repository is not None
    assert identity_service is not None
    assert document_ingestor_factory is not None

    auth_service = AuthService(
        oidc_verifier, auth_repository, auth_config or AuthConfig()
    )
    resolved_cookie_config = cookie_config or SessionCookieConfig()
    session_boundary = HttpSessionBoundary(
        auth_service, resolved_cookie_config
    )
    workflow = _ProvisioningWorkflow(auth_service, identity_service)

    router = create_toc_router(
        principal_dependency=session_boundary.read_principal,
        mutation_principal_dependency=session_boundary.mutation_principal,
        identity_service_provider=lambda: identity_service,
        document_ingestor_factory=document_ingestor_factory,
        provider_catalog_provider=provider_catalog_provider,
    )
    return TocComposition(
        auth_service=auth_service,
        identity_service=identity_service,
        session_boundary=session_boundary,
        cookie_config=resolved_cookie_config,
        sign_in=workflow.sign_in,
        router=router,
    )


def create_toc_oidc_login_flow(
    composition: TocComposition,
    config: LoginFlowConfig,
    store: LoginAttemptStore,
    exchanger: AuthorizationCodeExchanger,
    *,
    clock_ms: Callable[[], int] | None = None,
) -> OidcLoginFlow:
    """Bind OIDC callback completion to the catalog-provisioning workflow."""

    return OidcLoginFlow(
        config,
        store,
        exchanger,
        composition.sign_in,
        clock_ms=clock_ms,
    )


class _ProvisioningWorkflow:
    def __init__(
        self, auth_service: AuthService, identity_service: IdentityService
    ) -> None:
        self.auth_service = auth_service
        self.identity_service = identity_service

    def sign_in(self, id_token: str, expected_nonce: str) -> IssuedSession:
        return self.auth_service.sign_in_with_provisioning(
            id_token, expected_nonce, self._ensure_catalog_user
        )

    def _ensure_catalog_user(
        self, user_id: UserId, identity: VerifiedOidcIdentity
    ) -> None:
        try:
            self.identity_service.get_user(user_id)
            return
        except ObjectNotFoundError:
            pass
        try:
            self.identity_service.create_user(user_id, _display_name(identity))
        except CatalogError:
            # Concurrent first login may win the unique insert. A successful
            # scoped re-read proves it was exactly the mapped user.
            self.identity_service.get_user(user_id)


def _display_name(identity: VerifiedOidcIdentity) -> str:
    normalized = " ".join((identity.display_name or "Anima 用户").strip().split())
    return (normalized or "Anima 用户")[:80]
