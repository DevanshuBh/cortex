"""The tenant comes only from a verified token."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from cortex.api import auth
from cortex.config import get_settings

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _Jwks:
    def get_signing_key_from_jwt(self, _token: str) -> Any:
        return jwt.PyJWK.from_dict(
            {**jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True), "alg": "RS256", "kid": "k1"}
        )


@pytest.fixture(autouse=True)
def fake_jwks(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(auth, "_jwks_client", lambda _url: _Jwks())
    yield


def token(key: Any = KEY, **overrides: Any) -> str:
    s = get_settings()
    now = int(time.time())
    claims = {"sub": "u1", "iss": s.oidc_issuer, "aud": s.oidc_audience, "iat": now, "exp": now + 300,
              "tenant_id": "acme", "realm_access": {"roles": ["member"]}, **overrides}
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"})


@pytest.fixture
def client() -> TestClient:
    from cortex.api.main import app

    return TestClient(app)


def test_tenant_comes_from_the_token_not_a_header(client: TestClient) -> None:
    r = client.get("/v1/me", headers={"Authorization": f"Bearer {token()}", "X-Tenant-Id": "someone-else"})
    assert r.status_code == 200
    assert r.json()["tenant_id"] == "acme"


@pytest.mark.parametrize(
    ("bad", "status"),
    [
        ({"tenant_id": None}, 403),
        ({"aud": "another-api"}, 401),
        ({"iss": "https://evil.example/realms/cortex"}, 401),
        ({"exp": int(time.time()) - 10}, 401),
    ],
)
def test_bad_tokens_are_rejected(client: TestClient, bad: dict[str, Any], status: int) -> None:
    r = client.get("/v1/me", headers={"Authorization": f"Bearer {token(**bad)}"})
    assert r.status_code == status
    assert r.headers["content-type"].startswith("application/problem+json")


def test_token_signed_by_another_key_is_rejected(client: TestClient) -> None:
    r = client.get("/v1/me", headers={"Authorization": f"Bearer {token(key=OTHER_KEY)}"})
    assert r.status_code == 401


def test_missing_token(client: TestClient) -> None:
    assert client.get("/v1/me").status_code == 401


def test_admin_role_from_realm_roles() -> None:
    p = auth.principal_from_claims({"sub": "u", "tenant_id": "t", "realm_access": {"roles": ["admin"]}})
    assert p.is_admin and p.tenant_id == "t"
