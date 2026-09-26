"""Strictly read-only Alpaca LIVE client for the web "Live account" view.

Why a separate client instead of :class:`engine.brokers.alpaca.AlpacaAPI`?
``AlpacaAPI`` wraps the full trading SDK (submit/cancel/close). The live view
must never be able to do any of that, so this module talks to Alpaca over plain
HTTPS with an explicit allow-list:

* only the ``GET`` verb (there is no code path that issues anything else);
* only ``/v2/account``, ``/v2/positions``, ``/v2/orders`` (open/closed listing),
  ``/v2/account/activities/FILL``, ``/v2/account/portfolio/history`` and
  ``/v2/calendar`` — each with an explicit per-path query allow-list;
* only the fixed live host ``https://api.alpaca.markets`` (not configurable);
* the account number Alpaca returns must match the linked one, otherwise the
  snapshot is refused (guards against a mis-linked key pair).

Alpaca does not offer read-only API keys for trading accounts, so these
guarantees are enforced in code (and covered by ``tests/test_live_account.py``).
Credentials are never logged and never included in error messages.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

LIVE_BASE_URL = "https://api.alpaca.markets"

# path -> the exact query parameters that path is allowed to carry (the plain
# snapshot reads). Extra read-only queries are validated by ALLOWED_QUERIES below.
ALLOWED_GETS: dict[str, dict[str, str]] = {
    "/v2/account": {},
    "/v2/positions": {},
    "/v2/orders": {"status": "open"},
    "/v2/account/activities/FILL": {},
    "/v2/account/portfolio/history": {},
    "/v2/calendar": {},
}

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}(T[0-9:.]+(Z|[+-]\d{2}:\d{2})?)?$")
_INT = re.compile(r"^\d{1,4}$")
_TOKEN = re.compile(r"^[A-Za-z0-9:._-]{1,64}$")

# path -> {param: validator}. Every key of a request must be listed; values must
# match. Anything else is refused before a request is made.
ALLOWED_QUERIES: dict[str, dict[str, Any]] = {
    "/v2/account": {},
    "/v2/positions": {},
    "/v2/orders": {"status": {"open", "closed"}, "after": _TS, "until": _TS,
                   "limit": _INT, "direction": {"asc", "desc"}, "nested": {"false"}},
    "/v2/account/activities/FILL": {"date": _DATE, "after": _TS, "until": _TS,
                                    "direction": {"asc", "desc"}, "page_size": _INT,
                                    "page_token": _TOKEN},
    "/v2/account/portfolio/history": {"period": {"1D", "1W", "1M", "3M", "6M", "1A", "all"},
                                      "timeframe": {"1Min", "5Min", "15Min", "1H", "1D"},
                                      "start": _TS, "end": _TS,
                                      "intraday_reporting": {"market_hours", "extended_hours",
                                                             "continuous"}},
    "/v2/calendar": {"start": _DATE, "end": _DATE},
}


def _query_allowed(path: str, params: dict) -> bool:
    spec = ALLOWED_QUERIES.get(path)
    if spec is None:
        return False
    if path == "/v2/orders" and params.get("status") not in ("open", "closed"):
        return False  # status is mandatory: never an unfiltered/all listing
    for key, value in params.items():
        rule = spec.get(key)
        if rule is None or not isinstance(value, str):
            return False
        if isinstance(rule, set):
            if value not in rule:
                return False
        elif not rule.match(value):
            return False
    return True


_TIMEOUT = 10


class LiveReadOnlyError(RuntimeError):
    """A read failed; the message is safe to show (no credentials)."""


class LiveAccountMismatch(LiveReadOnlyError):
    """The keys belong to a different account than the linked account number."""


class LiveReadOnlyClient:
    """GET-only view of one Alpaca live account."""

    def __init__(self, api_key: str, secret_key: str,
                 expected_account_number: Optional[str] = None,
                 http: Any = None):
        if not api_key or not secret_key:
            raise LiveReadOnlyError("Live account credentials are not configured.")
        self._headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key,
                         "Accept": "application/json"}
        self.expected_account_number = (str(expected_account_number).strip()
                                        if expected_account_number else None)
        self._http = http or requests

    def __repr__(self) -> str:  # never leak keys through repr/logging
        return f"LiveReadOnlyClient(account={self.expected_account_number or '?'})"

    # -- the only network primitive ------------------------------------------
    def _get(self, path: str, params: Optional[dict] = None):
        params = dict(params or {})
        if path not in ALLOWED_GETS:
            raise LiveReadOnlyError(f"Path not allowed for the read-only live view: {path}")
        if not _query_allowed(path, params):
            raise LiveReadOnlyError(f"Query not allowed for {path}")
        try:
            resp = self._http.get(LIVE_BASE_URL + path, headers=self._headers,
                                  params=params or None, timeout=_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 — network error; never echo headers
            raise LiveReadOnlyError(f"Alpaca live API unreachable ({type(exc).__name__}).") from None
        status = getattr(resp, "status_code", 0)
        if status == 401 or status == 403:
            raise LiveReadOnlyError(
                "Alpaca rejected the linked live keys (unauthorized). They were probably "
                "regenerated; re-link them with scripts/link_live_account.py.")
        if status != 200:
            raise LiveReadOnlyError(f"Alpaca live API returned HTTP {status} for {path}.")
        try:
            return resp.json()
        except Exception:  # noqa: BLE001
            raise LiveReadOnlyError(f"Alpaca live API returned invalid JSON for {path}.") from None

    # -- public reads ----------------------------------------------------------
    def get_account(self) -> dict:
        data = self._get("/v2/account")
        if not isinstance(data, dict):
            raise LiveReadOnlyError("Unexpected account payload from Alpaca.")
        if self.expected_account_number:
            got = str(data.get("account_number") or "").strip()
            if got != self.expected_account_number:
                raise LiveAccountMismatch(
                    "The linked keys do not belong to the linked live account; refusing to display.")
        return data

    def get_positions(self) -> list[dict]:
        data = self._get("/v2/positions")
        return data if isinstance(data, list) else []

    def get_open_orders(self) -> list[dict]:
        data = self._get("/v2/orders", ALLOWED_GETS["/v2/orders"])
        return data if isinstance(data, list) else []

    def get_order_history(self, after: str, until: str, limit: int = 500) -> list[dict]:
        """Closed (filled/canceled/expired) orders submitted in [after, until]."""
        data = self._get("/v2/orders", {"status": "closed", "after": after, "until": until,
                                        "limit": str(int(limit)), "direction": "asc"})
        return data if isinstance(data, list) else []

    def get_fills(self, day: Optional[str] = None, after: Optional[str] = None,
                  until: Optional[str] = None, max_pages: int = 20) -> list[dict]:
        """FILL account activities (oldest first) for one ET ``day`` or a range."""
        base: dict[str, str] = {"direction": "asc", "page_size": "100"}
        if day:
            base["date"] = day
        if after:
            base["after"] = after
        if until:
            base["until"] = until
        out: list[dict] = []
        token = None
        for _ in range(max_pages):
            params = dict(base, **({"page_token": token} if token else {}))
            page = self._get("/v2/account/activities/FILL", params)
            if not isinstance(page, list) or not page:
                break
            out.extend(page)
            if len(page) < 100:
                break
            token = str(page[-1].get("id") or "")
            if not token:
                break
        return out

    def get_portfolio_history(self, start: str, end: str, timeframe: str = "1D") -> dict:
        data = self._get("/v2/account/portfolio/history",
                         {"start": start, "end": end, "timeframe": timeframe})
        return data if isinstance(data, dict) else {}

    def get_calendar(self, start: str, end: str) -> list[dict]:
        data = self._get("/v2/calendar", {"start": start, "end": end})
        return data if isinstance(data, list) else []

    def snapshot(self) -> dict:
        """Account (verified first), positions and open orders."""
        account = self.get_account()
        return {"account": account, "positions": self.get_positions(),
                "orders": self.get_open_orders()}


def summarize_account(account: dict) -> dict:
    """Portfolio summary numbers from a /v2/account payload."""
    def f(key):
        try:
            return float(account.get(key))
        except (TypeError, ValueError):
            return None
    equity, last_equity = f("equity"), f("last_equity")
    day_pl = (equity - last_equity) if equity is not None and last_equity is not None else None
    day_pl_pct = (day_pl / last_equity * 100) if day_pl is not None and last_equity else None
    return {
        "account_number": str(account.get("account_number") or ""),
        "status": str(account.get("status") or ""),
        "currency": str(account.get("currency") or "USD"),
        "equity": equity, "last_equity": last_equity, "cash": f("cash"),
        "buying_power": f("buying_power"), "long_market_value": f("long_market_value"),
        "day_pl": day_pl, "day_pl_pct": day_pl_pct,
    }
