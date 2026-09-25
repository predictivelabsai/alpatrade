"""Local-development login bypass — ``GET /dev/login?email=...``.

For driving the app with Playwright on a developer machine without SSO or a
password. Triple-gated so it can never activate in production:

1. the route is only *registered* when ``ALPATRADE_DEV_LOGIN=1`` is present in the
   process environment at startup (this variable is not set in Coolify / prod);
2. each request must come from a loopback client address (behind the prod
   reverse proxy the client is the proxy, never 127.0.0.1);
3. the ``Host`` header must be ``localhost`` / ``127.0.0.1`` / ``[::1]``.

It only signs in *existing* users (no account creation) and logs a warning.
"""
from __future__ import annotations

import logging
import os

from starlette.responses import PlainTextResponse, RedirectResponse

logger = logging.getLogger(__name__)

ENV_FLAG = "ALPATRADE_DEV_LOGIN"
_LOOPBACK_CLIENTS = {"127.0.0.1", "::1", "localhost"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}


def enabled() -> bool:
    return os.environ.get(ENV_FLAG) == "1"


def request_is_local(request) -> bool:
    client = getattr(getattr(request, "client", None), "host", "") or ""
    host = (request.headers.get("host") or "").strip().lower()
    hostname = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
    fwd = request.headers.get("x-forwarded-for") or request.headers.get("x-forwarded-host")
    return client in _LOOPBACK_CLIENTS and hostname in _LOCAL_HOSTS and not fwd


def register(app, rt):
    if not enabled():
        return []
    logger.warning("DEV LOGIN BYPASS ENABLED (%s=1) — local development only", ENV_FLAG)

    @rt("/dev/login", methods=["GET"])
    def dev_login(request, session, email: str = "", next: str = "/dashboard"):
        if not enabled() or not request_is_local(request):
            return PlainTextResponse("Not found", status_code=404)
        from engine.auth import get_user_by_email
        user = get_user_by_email(email.strip().lower()) if email else None
        if not user:
            return PlainTextResponse("Unknown user", status_code=404)
        session["user_id"] = user["user_id"]
        logger.warning("dev login as %s", email)
        return RedirectResponse(next if next.startswith("/") and not next.startswith("//")
                                else "/dashboard", status_code=303)

    return ["/dev/login"]
