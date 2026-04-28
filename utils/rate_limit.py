"""Shared slowapi rate-limiter.

Import `limiter` from this module in any router to apply rate limits, and
ensure `main.py` registers `app.state.limiter = limiter` + the exception
handler so FastAPI knows about it.

Key function prefers Cloudflare's CF-Connecting-IP, then X-Forwarded-For,
then falls back to the TCP peer address. falconverify sits behind
Cloudflare Pages, so raw peer IPs would collapse to edge addresses
without this.
"""

import base64
import json

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _client_ip(request: Request) -> str:
    cf = request.headers.get("CF-Connecting-IP")
    if cf:
        return cf.strip()
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return get_remote_address(request)


def user_or_ip_key(request: Request) -> str:
    """Key by Clerk user_id when an Authorization bearer is present, else IP.

    Used for billed-action endpoints (Twilio conference/caller-ID verify) so
    one authenticated account can't exhaust the IP-shared quota for everyone.
    JWT body is decoded WITHOUT verification — `require_auth` still does the
    real verification at request time. This is just for keying.
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        parts = token.split(".")
        if len(parts) >= 2:
            try:
                payload = parts[1] + "=" * (-len(parts[1]) % 4)
                decoded = json.loads(base64.urlsafe_b64decode(payload))
                sub = decoded.get("sub")
                if sub:
                    return f"user:{sub}"
            except Exception:
                pass
    return f"ip:{_client_ip(request)}"


limiter = Limiter(key_func=_client_ip)
