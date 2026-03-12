"""Clerk authentication middleware for FastAPI.

Verifies Clerk session JWTs using JWKS (RS256). The `sub` claim is the
Clerk user ID (e.g. user_3ASljZWeTNVAOMGP62n87Eq0GG9).

Usage:
    from middleware.auth import require_auth
    @router.get("/protected")
    async def protected(user=Depends(require_auth)):
        user_id = user["sub"]  # Clerk user ID
"""

import base64
import logging
from typing import Any, Dict, Optional

import httpx
import jwt as pyjwt
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import get_settings

logger = logging.getLogger("falconconnect.auth.clerk")

security = HTTPBearer(auto_error=False)

# Simple in-process JWKS cache (keys rarely rotate)
_jwks_cache: Optional[Dict] = None


def _get_clerk_jwks_url() -> str:
    """Derive the public JWKS URL from the publishable key.

    The publishable key encodes the Clerk Frontend API domain in base64.
    E.g. pk_live_Y2xlcmsuZmFsY29ubmVjdC5vcmck decodes to clerk.falconnect.org
    This endpoint serves JWKS without requiring authentication, unlike
    api.clerk.com/v1/jwks which needs a Bearer token.
    """
    settings = get_settings()
    pk = settings.clerk_publishable_key
    if pk:
        # Strip pk_live_ or pk_test_ prefix, decode base64 to get domain
        try:
            encoded = pk.split("_", 2)[2]  # after pk_live_ or pk_test_
            domain = base64.b64decode(encoded + "==").decode("utf-8").rstrip("\x00$")
            url = f"https://{domain}/.well-known/jwks.json"
            logger.info("Using Clerk JWKS URL: %s", url)
            return url
        except Exception as e:
            logger.warning("Failed to derive JWKS URL from publishable key: %s", e)

    # Fallback: use api.clerk.com with secret key auth (handled in _get_jwks)
    return "https://api.clerk.com/v1/jwks"


async def _get_jwks() -> Dict:
    global _jwks_cache
    if _jwks_cache:
        return _jwks_cache

    jwks_url = _get_clerk_jwks_url()
    headers = {}

    # api.clerk.com/v1/jwks requires Bearer auth; the Frontend API URL does not
    if "api.clerk.com" in jwks_url:
        settings = get_settings()
        if settings.clerk_secret_key:
            headers["Authorization"] = f"Bearer {settings.clerk_secret_key}"

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(jwks_url, headers=headers)
        resp.raise_for_status()
        _jwks_cache = resp.json()
    return _jwks_cache


async def _verify_clerk_token(token: str) -> Dict[str, Any]:
    """Verify a Clerk session JWT using JWKS. Returns decoded claims."""
    try:
        jwks = await _get_jwks()
        header = pyjwt.get_unverified_header(token)
        kid = header.get("kid")

        signing_key = None
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                signing_key = pyjwt.algorithms.RSAAlgorithm.from_jwk(key)
                break

        if not signing_key:
            # JWKS may have rotated — bust cache and retry once
            global _jwks_cache
            _jwks_cache = None
            jwks = await _get_jwks()
            for key in jwks.get("keys", []):
                if key.get("kid") == kid:
                    signing_key = pyjwt.algorithms.RSAAlgorithm.from_jwk(key)
                    break

        if not signing_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token signing key not found — session may have expired.",
            )

        claims = pyjwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
        return claims

    except pyjwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token expired. Please sign in again.",
        )
    except pyjwt.InvalidTokenError as e:
        logger.warning("Invalid Clerk token: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session token.",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Auth error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed.",
        )


async def require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
) -> Dict[str, Any]:
    """FastAPI dependency — require a valid Clerk session token.

    Returns decoded JWT claims. Use `user["sub"]` for the Clerk user ID.

    If CLERK_SECRET_KEY is not set (dev mode), bypasses auth entirely.
    """
    settings = get_settings()

    if not settings.clerk_secret_key:
        import os
        dev_user_id = os.environ.get("CLERK_ADMIN_USER_ID", "user_3ASrwDOrSTaDxCus6f1B5lnDsgz")
        logger.warning("CLERK_SECRET_KEY not set — auth DISABLED (dev mode, user_id=%s).", dev_user_id)
        return {
            "sub": dev_user_id,
            "user_id": dev_user_id,
            "auth_mode": "disabled",
        }

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await _verify_clerk_token(credentials.credentials)
