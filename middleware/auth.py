"""Clerk authentication middleware for FastAPI.

Verifies Clerk session JWTs using JWKS (RS256). The `sub` claim is the
Clerk user ID (e.g. user_3ASljZWeTNVAOMGP62n87Eq0GG9).

Usage:
    from middleware.auth import require_auth
    @router.get("/protected")
    async def protected(user=Depends(require_auth)):
        user_id = user["sub"]  # Clerk user ID
"""

import logging
from typing import Any, Dict, Optional

import httpx
import jwt as pyjwt
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import get_settings

logger = logging.getLogger("falconconnect.auth.clerk")

security = HTTPBearer(auto_error=False)

# Clerk JWKS endpoint — no auth needed to fetch public keys
CLERK_JWKS_URL = "https://api.clerk.com/v1/jwks"

# Simple in-process JWKS cache (keys rarely rotate)
_jwks_cache: Optional[Dict] = None


async def _get_jwks() -> Dict:
    global _jwks_cache
    if _jwks_cache:
        return _jwks_cache
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(CLERK_JWKS_URL)
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
        logger.warning("CLERK_SECRET_KEY not set — auth DISABLED (dev mode).")
        return {
            "sub": "user_3ASljZWeTNVAOMGP62n87Eq0GG9",  # Seb's Clerk ID
            "auth_mode": "disabled",
        }

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await _verify_clerk_token(credentials.credentials)
