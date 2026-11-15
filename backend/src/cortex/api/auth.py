"""JWT verification. The tenant comes only from the verified token — never from a header or the body."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from cortex.config import get_settings

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: str
    tenant_id: str
    roles: frozenset[str]

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles


@lru_cache
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=300)


def decode_token(token: str) -> dict[str, Any]:
    s = get_settings()
    signing_key = _jwks_client(s.oidc_jwks_url).get_signing_key_from_jwt(token)
    claims: dict[str, Any] = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256", "ES256"],
        audience=s.oidc_audience,
        issuer=s.oidc_issuer,
        options={"require": ["exp", "iat", "sub"]},
    )
    return claims


def principal_from_claims(claims: dict[str, Any]) -> Principal:
    s = get_settings()
    tenant = claims.get(s.tenant_claim)
    if isinstance(tenant, list):  # Keycloak multivalued attributes arrive as lists
        tenant = tenant[0] if len(tenant) == 1 else None
    if not isinstance(tenant, str) or not tenant:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "token has no tenant")
    roles: set[str] = set(claims.get("realm_access", {}).get("roles", []))
    roles |= set(claims.get("roles", []))
    return Principal(user_id=str(claims["sub"]), tenant_id=tenant, roles=frozenset(roles))


def current_principal(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "missing bearer token", headers={"WWW-Authenticate": "Bearer"}
        )
    try:
        claims = decode_token(creds.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, f"invalid token: {exc}", headers={"WWW-Authenticate": "Bearer"}
        ) from exc
    return principal_from_claims(claims)


def require_admin(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
    if not principal.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin role required")
    return principal


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
AdminPrincipal = Annotated[Principal, Depends(require_admin)]
