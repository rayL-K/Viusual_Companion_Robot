from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWK, PyJWKClient

from veyrasoul.auth import AuthenticationError
from veyrasoul.auth.oidc import OidcVerifierConfig, PyJwtOidcVerifier


ISSUER = "https://identity.example/"
AUDIENCE = "anima-web"
NONCE = "browser-login-nonce"


def _key(kid: str):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(
        private_key.public_key(), as_dict=True
    )
    public_jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return private_key, public_jwk


def _claims(**changes):
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "sub": "external-user",
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 300,
        "nonce": NONCE,
    }
    claims.update(changes)
    return claims


def _token(private_key, kid: str, **changes) -> str:
    return jwt.encode(
        _claims(**changes),
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )


class StaticJwksClient:
    def __init__(self, jwk: dict[str, object]) -> None:
        self._key = PyJWK.from_dict(jwk)

    def get_signing_key_from_jwt(self, token: str):
        return self._key


def _verifier(jwk):
    return PyJwtOidcVerifier(
        OidcVerifierConfig(
            issuer=ISSUER,
            audience=AUDIENCE,
            client_id=AUDIENCE,
            jwks_url="https://identity.example/.well-known/jwks.json",
            leeway_seconds=0,
        ),
        jwks_client_factory=lambda *args, **kwargs: StaticJwksClient(jwk),
    )


@pytest.mark.parametrize(
    ("changes", "nonce"),
    [
        ({"iss": "https://attacker.example/"}, NONCE),
        ({"aud": "other-client"}, NONCE),
        ({"exp": int(time.time()) - 1}, NONCE),
        ({}, "wrong-nonce"),
        ({"iat": None}, NONCE),
        ({"iat": int(time.time()) + 600}, NONCE),
    ],
)
def test_oidc_validation_fails_closed(changes, nonce) -> None:
    private_key, jwk = _key("current")
    token = _token(private_key, "current", **changes)

    with pytest.raises(AuthenticationError):
        _verifier(jwk).verify(token, nonce)


def test_forged_none_algorithm_is_rejected_before_key_selection() -> None:
    _, jwk = _key("current")
    token = jwt.encode(
        _claims(),
        key="",
        algorithm="none",
        headers={"kid": "current"},
    )

    with pytest.raises(AuthenticationError, match="算法"):
        _verifier(jwk).verify(token, NONCE)


def test_valid_token_returns_only_verified_identity_fields() -> None:
    private_key, jwk = _key("current")
    token = _token(
        private_key,
        "current",
        name="Alice",
        email="alice@example.test",
        admin=True,
    )

    identity = _verifier(jwk).verify(token, NONCE)

    assert identity.issuer == ISSUER
    assert identity.subject == "external-user"
    assert identity.display_name == "Alice"
    assert not hasattr(identity, "admin")


@pytest.mark.parametrize("azp", [None, "other-client"])
def test_multiple_audiences_require_matching_azp(azp) -> None:
    private_key, jwk = _key("current")
    changes = {"aud": [AUDIENCE, "secondary-api"]}
    if azp is not None:
        changes["azp"] = azp

    with pytest.raises(AuthenticationError, match="azp"):
        _verifier(jwk).verify(
            _token(private_key, "current", **changes), NONCE
        )


def test_multiple_audiences_accept_matching_client_azp() -> None:
    private_key, jwk = _key("current")
    token = _token(
        private_key,
        "current",
        aud=[AUDIENCE, "secondary-api"],
        azp=AUDIENCE,
    )

    assert _verifier(jwk).verify(token, NONCE).subject == "external-user"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("issuer", "https://user@identity.example/"),
        ("issuer", "https://identity.example/?tenant=one"),
        ("issuer", "https://identity.example/#fragment"),
        ("jwks_url", "https://user:pass@identity.example/jwks"),
        ("jwks_url", "https://identity.example/jwks?version=1"),
        ("jwks_url", "https://identity.example/jwks#fragment"),
    ],
)
def test_oidc_urls_reject_userinfo_query_and_fragment(field, value) -> None:
    values = {
        "issuer": ISSUER,
        "audience": AUDIENCE,
        "client_id": AUDIENCE,
        "jwks_url": "https://identity.example/.well-known/jwks.json",
    }
    values[field] = value

    with pytest.raises(ValueError):
        OidcVerifierConfig(**values)


class RotatingJwksClient(PyJWKClient):
    key_sets: list[dict[str, object]] = []
    fetch_count = 0

    def fetch_data(self):
        index = min(type(self).fetch_count, len(type(self).key_sets) - 1)
        type(self).fetch_count += 1
        data = type(self).key_sets[index]
        if self.jwk_set_cache is not None:
            self.jwk_set_cache.put(data)
        return data


def test_jwks_kid_miss_refreshes_rotated_key_set() -> None:
    old_private, old_jwk = _key("old")
    new_private, new_jwk = _key("new")
    RotatingJwksClient.key_sets = [
        {"keys": [old_jwk]},
        {"keys": [old_jwk, new_jwk]},
    ]
    RotatingJwksClient.fetch_count = 0
    verifier = PyJwtOidcVerifier(
        OidcVerifierConfig(
            issuer=ISSUER,
            audience=AUDIENCE,
            client_id=AUDIENCE,
            jwks_url="https://identity.example/.well-known/jwks.json",
        ),
        jwks_client_factory=RotatingJwksClient,
    )

    assert verifier.verify(_token(old_private, "old"), NONCE).subject == "external-user"
    assert verifier.verify(_token(new_private, "new"), NONCE).subject == "external-user"
    assert RotatingJwksClient.fetch_count == 2
