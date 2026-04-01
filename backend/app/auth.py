from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from jwt.algorithms import RSAAlgorithm

from app.config import Settings, get_settings

AUTH_SESSION_KEY = "admin_auth"
OIDC_STATE_KEY = "oidc_state"
OIDC_NEXT_KEY = "oidc_next"
DISCOVERY_CACHE_TTL_SECONDS = 300
JWKS_CACHE_TTL_SECONDS = 300


@dataclass
class AdminIdentity:
    authenticated: bool
    is_admin: bool
    username: str | None = None
    email: str | None = None


class KeycloakOIDCClient:
    def __init__(self) -> None:
        self._discovery_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._jwks_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def _issuer(self, settings: Settings) -> str:
        base_url = (settings.keycloak_base_url or "").rstrip("/")
        realm = (settings.keycloak_realm or "").strip("/")
        return f"{base_url}/realms/{realm}"

    async def get_discovery(self, settings: Settings) -> dict[str, Any]:
        cache_key = self._issuer(settings)
        cached = self._discovery_cache.get(cache_key)
        now = time.time()
        if cached and cached[0] > now:
            return cached[1]

        url = f"{cache_key}/.well-known/openid-configuration"
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Το Keycloak δεν είναι διαθέσιμο αυτή τη στιγμή.",
                ) from exc

        payload = response.json()
        self._discovery_cache[cache_key] = (now + DISCOVERY_CACHE_TTL_SECONDS, payload)
        return payload

    async def get_jwks(self, settings: Settings) -> dict[str, Any]:
        cache_key = self._issuer(settings)
        cached = self._jwks_cache.get(cache_key)
        now = time.time()
        if cached and cached[0] > now:
            return cached[1]

        discovery = await self.get_discovery(settings)
        jwks_uri = str(discovery.get("jwks_uri") or "").strip()
        if not jwks_uri:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Το Keycloak discovery document δεν περιέχει JWKS endpoint.",
            )

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.get(jwks_uri)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Αποτυχία φόρτωσης public keys από το Keycloak.",
                ) from exc

        payload = response.json()
        self._jwks_cache[cache_key] = (now + JWKS_CACHE_TTL_SECONDS, payload)
        return payload

    async def exchange_code(self, settings: Settings, *, code: str, redirect_uri: str) -> dict[str, Any]:
        discovery = await self.get_discovery(settings)
        token_endpoint = str(discovery.get("token_endpoint") or "").strip()
        if not token_endpoint:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Το Keycloak discovery document δεν περιέχει token endpoint.",
            )

        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": settings.keycloak_client_id or "",
            "client_secret": settings.keycloak_client_secret or "",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.post(token_endpoint, data=payload)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Η ανταλλαγή authorization code με το Keycloak απέτυχε.",
                ) from exc

        return response.json()

    async def build_logout_url(self, settings: Settings, *, next_path: str) -> str:
        discovery = await self.get_discovery(settings)
        logout_endpoint = str(discovery.get("end_session_endpoint") or "").strip()
        if not logout_endpoint:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Το Keycloak discovery document δεν περιέχει logout endpoint.",
            )

        params = {
            "client_id": settings.keycloak_client_id or "",
            "post_logout_redirect_uri": build_absolute_url(settings, next_path),
        }
        return f"{logout_endpoint}?{urlencode(params)}"

    async def verify_access_token(self, settings: Settings, token: str) -> dict[str, Any]:
        jwks = await self.get_jwks(settings)
        keys = jwks.get("keys") or []
        if not isinstance(keys, list):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Μη έγκυρο JWKS payload από το Keycloak.",
            )

        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Μη έγκυρο access token.") from exc

        key_id = header.get("kid")
        key_data = next((item for item in keys if item.get("kid") == key_id), None)
        if not key_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Το access token χρησιμοποιεί άγνωστο signing key.",
            )

        public_key = RSAAlgorithm.from_jwk(json.dumps(key_data))
        try:
            claims = jwt.decode(
                token,
                key=public_key,
                algorithms=["RS256", "RS384", "RS512"],
                issuer=self._issuer(settings),
                options={"verify_aud": False},
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Αποτυχία επαλήθευσης access token από το Keycloak.",
            ) from exc

        if not _token_matches_client(claims, settings.keycloak_client_id or ""):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Το access token δεν εκδόθηκε για το αναμενόμενο client.",
            )

        return claims


def auth_config_missing(settings: Settings) -> list[str]:
    if not settings.auth_enabled:
        return []

    required = {
        "PUBLIC_APP_URL": settings.public_app_url,
        "SESSION_SECRET_KEY": settings.session_secret_key,
        "KEYCLOAK_BASE_URL": settings.keycloak_base_url,
        "KEYCLOAK_REALM": settings.keycloak_realm,
        "KEYCLOAK_CLIENT_ID": settings.keycloak_client_id,
        "KEYCLOAK_CLIENT_SECRET": settings.keycloak_client_secret,
    }
    missing = [name for name, value in required.items() if value is None or str(value).strip() == ""]
    if settings.session_secret_key == "change-me-before-production":
        missing.append("SESSION_SECRET_KEY")
    return sorted(set(missing))


def build_default_home_path(settings: Settings) -> str:
    root_path = (settings.root_path or "").rstrip("/")
    return f"{root_path}/" if root_path else "/"


def sanitize_next_path(settings: Settings, next_path: str | None) -> str:
    default_path = build_default_home_path(settings)
    if not next_path:
        return default_path

    candidate = next_path.strip()
    if not candidate.startswith("/") or candidate.startswith("//"):
        return default_path

    root_path = (settings.root_path or "").rstrip("/")
    if root_path and not (candidate == root_path or candidate.startswith(f"{root_path}/")):
        return default_path

    return candidate


def build_absolute_url(settings: Settings, path: str) -> str:
    if not settings.public_app_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Το PUBLIC_APP_URL λείπει από το backend configuration.",
        )

    return f"{settings.public_app_url.rstrip('/')}{path}"


def build_callback_url(settings: Settings) -> str:
    public_url = (settings.public_app_url or "").rstrip("/")
    if public_url:
        return f"{public_url}/api/auth/callback"

    root_path = (settings.root_path or "").rstrip("/")
    callback_path = f"{root_path}/api/auth/callback" if root_path else "/api/auth/callback"
    return build_absolute_url(settings, callback_path)


def auth_status_payload(request: Request, settings: Settings) -> dict[str, Any]:
    missing = auth_config_missing(settings)
    identity = get_admin_identity(request)
    return {
        "enabled": settings.auth_enabled,
        "configured": len(missing) == 0,
        "authenticated": identity.authenticated if not missing else False,
        "is_admin": identity.is_admin if not missing else False,
        "username": identity.username if not missing else None,
        "email": identity.email if not missing else None,
        "error": (
            f"Λείπουν auth ρυθμίσεις: {', '.join(missing)}."
            if settings.auth_enabled and missing
            else None
        ),
    }


def get_admin_identity(request: Request) -> AdminIdentity:
    payload = request.session.get(AUTH_SESSION_KEY) or {}
    if not isinstance(payload, dict):
        return AdminIdentity(authenticated=False, is_admin=False)

    return AdminIdentity(
        authenticated=bool(payload.get("authenticated")),
        is_admin=bool(payload.get("is_admin")),
        username=_string_or_none(payload.get("username")),
        email=_string_or_none(payload.get("email")),
    )


async def require_admin(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> AdminIdentity:
    if not settings.auth_enabled:
        return AdminIdentity(authenticated=True, is_admin=True, username="local-admin")

    missing = auth_config_missing(settings)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Το Keycloak auth είναι ενεργό αλλά λείπουν ρυθμίσεις: {', '.join(missing)}.",
        )

    identity = get_admin_identity(request)
    if not identity.authenticated:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Απαιτείται admin login.")
    if not identity.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Απαιτείται ρόλος admin.")
    return identity


def build_authorization_url(
    settings: Settings,
    discovery: dict[str, Any],
    *,
    state: str,
    next_path: str,
) -> str:
    authorization_endpoint = str(discovery.get("authorization_endpoint") or "").strip()
    if not authorization_endpoint:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Το Keycloak discovery document δεν περιέχει authorization endpoint.",
        )

    params = {
        "client_id": settings.keycloak_client_id or "",
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": build_callback_url(settings),
        "state": state,
    }
    if next_path:
        params["ui_locales"] = "el"
    return f"{authorization_endpoint}?{urlencode(params)}"


def begin_login(request: Request, settings: Settings, *, next_path: str) -> tuple[str, str]:
    state = secrets.token_urlsafe(24)
    safe_next = sanitize_next_path(settings, next_path)
    request.session[OIDC_STATE_KEY] = state
    request.session[OIDC_NEXT_KEY] = safe_next
    return state, safe_next


def complete_login(request: Request, settings: Settings, claims: dict[str, Any]) -> str:
    roles = _extract_realm_roles(claims)
    request.session[AUTH_SESSION_KEY] = {
        "authenticated": True,
        "is_admin": settings.keycloak_admin_role in roles,
        "username": claims.get("preferred_username") or claims.get("name") or claims.get("email") or claims.get("sub"),
        "email": claims.get("email"),
    }
    next_path = sanitize_next_path(settings, request.session.pop(OIDC_NEXT_KEY, None))
    request.session.pop(OIDC_STATE_KEY, None)
    return next_path


def clear_login_state(request: Request) -> None:
    request.session.pop(OIDC_STATE_KEY, None)
    request.session.pop(OIDC_NEXT_KEY, None)


def clear_auth_session(request: Request) -> None:
    request.session.pop(AUTH_SESSION_KEY, None)
    clear_login_state(request)


def validate_callback_state(request: Request, state: str | None) -> None:
    expected = request.session.get(OIDC_STATE_KEY)
    if not expected or not state or state != expected:
        clear_login_state(request)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Μη έγκυρο Keycloak state.")


def _extract_realm_roles(claims: dict[str, Any]) -> list[str]:
    realm_access = claims.get("realm_access") or {}
    if not isinstance(realm_access, dict):
        return []
    roles = realm_access.get("roles") or []
    if not isinstance(roles, list):
        return []
    return [str(role) for role in roles if isinstance(role, str)]


def _token_matches_client(claims: dict[str, Any], client_id: str) -> bool:
    if not client_id:
        return False

    if claims.get("azp") == client_id:
        return True

    audience = claims.get("aud")
    if isinstance(audience, list):
        return client_id in audience
    if isinstance(audience, str):
        return audience == client_id
    return False


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
