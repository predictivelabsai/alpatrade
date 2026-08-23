"""Short-lived user delegation for the isolated Hermes service.

Hermes never receives ``DATABASE_URL`` or AlpaTrade's general service key.  A
logged-in web request mints this narrowly scoped token; the API combines it
with a dedicated service secret before allowing only ``/v2/hermes/*`` routes.
"""
from __future__ import annotations

import os
import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

ISSUER = "alpatrade-web"
AUDIENCE = "alpatrade-hermes-broker"


def create_hermes_delegation(user_id: str, thread_id: str, *, minutes: int = 30) -> str:
    """Create a short-lived token tied to one authenticated AlpaTrade user."""
    secret = os.getenv("JWT_SECRET", "")
    if not secret:
        raise RuntimeError("JWT_SECRET is not configured")
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "thread_id": str(thread_id),
        "scope": "hermes:alpatrade",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
    }
    body = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{body}.{encoded_signature}"


def decode_hermes_delegation(token: str) -> dict[str, Any]:
    """Validate a Hermes delegation token and return its claims."""
    secret = os.getenv("JWT_SECRET", "")
    if not secret:
        raise ValueError("JWT_SECRET is not configured")
    try:
        body, encoded_signature = token.split(".", 1)
        expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
        supplied = base64.urlsafe_b64decode(encoded_signature + "=" * (-len(encoded_signature) % 4))
        if not hmac.compare_digest(expected, supplied):
            raise ValueError("invalid Hermes delegation signature")
        claims = json.loads(
            base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode()
        )
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid Hermes delegation") from exc
    if claims.get("iss") != ISSUER or claims.get("aud") != AUDIENCE:
        raise ValueError("invalid Hermes delegation issuer or audience")
    if int(claims.get("exp", 0)) <= int(time.time()):
        raise ValueError("expired Hermes delegation")
    if claims.get("scope") != "hermes:alpatrade":
        raise ValueError("invalid Hermes delegation scope")
    return claims


def hermes_system_instructions(user_id: str, thread_id: str) -> str:
    """Return per-request broker instructions for the remote Hermes agent."""
    token = create_hermes_delegation(user_id, thread_id)
    return f"""

HERMES ALPATRADE BROKER (mandatory security boundary)
- You have no direct database access. Never request or search for DATABASE_URL.
- AlpaTrade operations are allowed only at the internal container URL
  http://api:5001/v2/hermes/*. Never use the public api.alpatrade.chat host.
- Send both headers on every broker request:
  X-Hermes-Key: $ALPATRADE_HERMES_API_KEY
  X-Hermes-Delegation: {token}
- The delegation expires in 30 minutes and represents only the logged-in user.
- Backtests, candidate storage, run inspection, and PAPER trading are allowed.
- Live trading is forbidden. Never call non-Hermes AlpaTrade API routes.
- When asked to backtest, use POST /v2/hermes/backtests. When asked to paper
  trade saved parameters, use POST /v2/hermes/candidates/<candidate_id>/paper.
- These routes enqueue background jobs. Report job_id/run_id immediately and
  end the turn; never poll or wait in the same response.
- Never fall back to /v2/backtest, /v2/paper, auth routes, or test accounts.
"""
