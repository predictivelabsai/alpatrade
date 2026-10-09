"""Account-scoped portfolio dashboard data and persisted advisor reports."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from typing import Any

from alpaca.trading.requests import GetPortfolioHistoryRequest

from agents.report_agent import ReportAgent
from engine.auth import get_alpaca_keys, get_user_accounts
from engine.brokers.alpaca import AlpacaAPI
from engine.reporting.cash_flows import adjusted_pnl, fetch_flows, net_flows

logger = logging.getLogger(__name__)

# Live rows use this prefix so they never collide with paper UUIDs in user_accounts.
# Trading tools still read get_user_accounts() only — never these ids.
LIVE_ACCOUNT_PREFIX = "live:"


def is_live_dashboard_id(account_id: str | None) -> bool:
    return bool(account_id) and str(account_id).startswith(LIVE_ACCOUNT_PREFIX)


def live_dashboard_id(account_number: str) -> str:
    return f"{LIVE_ACCOUNT_PREFIX}{account_number}"


def _list_live_accounts(user_id: str) -> list[dict]:
    """Display-safe live links; isolated for tests to monkeypatch."""
    from engine.live_accounts import list_live_accounts
    return list_live_accounts(user_id)


def _catalog(user_id: str) -> tuple[list[dict], list[dict]]:
    """Paper accounts (user_accounts) plus synthetic live dropdown rows."""
    paper = []
    for row in get_user_accounts(user_id):
        item = dict(row)
        item["kind"] = "paper"
        paper.append(item)
    live: list[dict] = []
    try:
        for row in _list_live_accounts(user_id):
            num = str(row.get("account_number") or "").strip()
            if not num:
                continue
            label = (row.get("label") or "Alpaca live").strip()
            live.append({
                "account_id": live_dashboard_id(num),
                "account_name": f"{label} · {num} (LIVE)",
                "account_number": num,
                "kind": "live",
                "is_active": True,
            })
    except Exception as exc:  # noqa: BLE001 — table missing / DB down
        logger.warning("live account list unavailable: %s", type(exc).__name__)
    return paper, live


# Canonical dashboard periods (UI + API). Legacy aliases map in normalize_period.
DASHBOARD_PERIODS = ("mtd", "ytd")
DEFAULT_PERIOD = "mtd"
_PERIOD_ALIASES = {
    "mtd": "mtd",
    "ytd": "ytd",
    "monthly": "mtd",  # legacy
    "daily": "mtd",
    "weekly": "mtd",
    "month": "mtd",
    "year": "ytd",
}


def normalize_period(period: str | None) -> str:
    """Map UI/query values to mtd|ytd; unknown → MTD default."""
    key = (period or "").strip().lower()
    return _PERIOD_ALIASES.get(key, DEFAULT_PERIOD)


def period_label(period: str) -> str:
    """Short display label for KPIs and tabs."""
    return {"mtd": "MTD", "ytd": "YTD"}.get(normalize_period(period), "MTD")


def period_bounds(period: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return UTC bounds for month-to-date or year-to-date."""
    now = now or datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc)
    period = normalize_period(period)
    if period == "ytd":
        start_date = now.date().replace(month=1, day=1)
    else:  # mtd
        start_date = now.date().replace(day=1)
    return datetime.combine(start_date, time.min, tzinfo=timezone.utc), now


def period_annualized(period: str, period_pct, now: datetime | None = None) -> dict:
    """Annualised period return: simple r*252/d and compounded, d = NYSE days elapsed."""
    from zoneinfo import ZoneInfo
    from engine.reporting.annualize import annualize, trading_days_between
    start, end = period_bounds(period, now)
    end_dt = end.astimezone(ZoneInfo("America/New_York"))
    end_et = end_dt.date()
    if end_dt.hour < 16:  # today's session not closed yet (ET) — count completed days only
        end_et -= timedelta(days=1)
    return annualize(period_pct, trading_days_between(start.date(), end_et))


def _strategy_run(user_id: str, mode: str, tag_key: str, tag_val: str | None) -> dict:
    """Most recent non-test runner run for ``mode`` (prefer one tagged with this account)."""
    import json
    from sqlalchemy import text
    from engine.db.pool import DatabasePool
    with DatabasePool().get_session() as session:
        rows = session.execute(text("""
            SELECT run_id, config, started_at
            FROM alpatrade.runs
            WHERE user_id = CAST(:uid AS UUID) AND mode = :mode
              AND COALESCE((config->>'test')::boolean, FALSE) = FALSE
            ORDER BY started_at DESC LIMIT 20
        """), {"uid": user_id, "mode": mode}).mappings().all()
    rows = [dict(r) for r in rows]
    for r in rows:
        if isinstance(r.get("config"), str):
            r["config"] = json.loads(r["config"])
    tagged = [r for r in rows if tag_val and
              str((r.get("config") or {}).get(tag_key) or "") == str(tag_val)]
    if mode == "live":
        return (tagged or rows or [{}])[0]
    return (tagged or [{}])[0]  # paper: only trust a run tagged with this account


def _first_equity_since(user_id: str, selected: dict, start) -> tuple[Any, float | None]:
    """(date, equity) of the first positive daily equity on/after ``start``."""
    from datetime import date as _date
    end = datetime.now(timezone.utc)
    acct = str(selected.get("account_id") or "")
    if is_live_dashboard_id(acct):
        from engine.brokers.alpaca_live_readonly import LiveReadOnlyClient
        from engine.live_accounts import get_live_account_credentials
        creds = get_live_account_credentials(user_id, acct[len(LIVE_ACCOUNT_PREFIX):])
        client = LiveReadOnlyClient(creds["api_key"], creds["secret_key"],
                                    expected_account_number=creds["account_number"])
        raw = client.get_portfolio_history(start.isoformat(), end.date().isoformat(), "1D")
        ts, eq = raw.get("timestamp") or [], raw.get("equity") or []
    else:
        client, _env = _client(user_id, acct)
        h = _history(client, datetime.combine(start, time.min, tzinfo=timezone.utc), end)
        ts = [int(datetime.fromisoformat(t).timestamp()) for t in h["timestamps"]]
        eq = h["equity"]
    for t, e in zip(ts, eq):
        if e is not None and float(e) > 0:
            d = datetime.fromtimestamp(int(t), timezone.utc).date()
            if d >= start:
                return d, float(e)
    return None, None


def _deposits_since(user_id: str, selected: dict, start) -> float:
    """Net deposits booked after ``start`` (date) for the selected account; 0.0 if unknown."""
    acct = str(selected.get("account_id") or "")
    try:
        if is_live_dashboard_id(acct):
            from engine.brokers.alpaca_live_readonly import LiveReadOnlyClient
            from engine.live_accounts import get_live_account_credentials
            creds = get_live_account_credentials(user_id, acct[len(LIVE_ACCOUNT_PREFIX):])
            client = LiveReadOnlyClient(creds["api_key"], creds["secret_key"],
                                        expected_account_number=creds["account_number"])
        else:
            client, _env = _client(user_id, acct)
        return net_flows(fetch_flows(client, start - timedelta(days=1)) or [], start,
                         datetime.now(timezone.utc).date())
    except Exception as exc:  # noqa: BLE001
        logger.warning("since-start cash flows failed: %s", type(exc).__name__)
        return 0.0


def since_start_annualized(user_id: str, selected: dict, now: datetime | None = None) -> dict:
    """Annualised return normalised since the strategy start.

    Live: start = the live runner run's start date / start_equity (same baseline as the
    LIVE email's "Since start"). Paper: the paper runner run tagged with this account,
    else the account's first portfolio-history equity. Returns ``annualize()`` output
    plus ``return_pct`` / ``start_date`` / ``basis='since_start'``.
    """
    from datetime import date as _date
    from zoneinfo import ZoneInfo
    from engine.reporting.annualize import annualize, trading_days_between
    from engine.reporting.live_perf import _parse_started
    acct = str(selected.get("account_id") or "")
    live = is_live_dashboard_id(acct)
    run: dict = {}
    try:
        run = (_strategy_run(user_id, "live", "account_number", acct[len(LIVE_ACCOUNT_PREFIX):])
               if live else _strategy_run(user_id, "paper", "account_id", acct))
    except Exception as exc:  # noqa: BLE001
        logger.warning("strategy run lookup failed: %s", type(exc).__name__)
    cfg = run.get("config") or {}
    start = _parse_started(cfg, run) if run.get("run_id") else None
    start_eq = None
    try:
        start_eq = float(cfg.get("start_equity")) if cfg.get("start_equity") else None
    except (TypeError, ValueError):
        start_eq = None
    if start_eq is None:
        try:
            d0, e0 = _first_equity_since(user_id, selected, start or _date(2015, 1, 1))
            start, start_eq = start or d0, e0
        except Exception as exc:  # noqa: BLE001
            logger.warning("since-start history failed: %s", type(exc).__name__)
    equity = _number(selected.get("equity"))
    dep = _deposits_since(user_id, selected, start) if start and start_eq else 0.0
    ret = adjusted_pnl(equity, start_eq, dep)[1] if start_eq and equity else None
    now = now or datetime.now(timezone.utc)
    end_dt = now.astimezone(ZoneInfo("America/New_York"))
    end_et = end_dt.date()
    if end_dt.hour < 16:
        end_et -= timedelta(days=1)
    days = trading_days_between(start, end_et) if start else 0
    return {**annualize(ret, days), "return_pct": ret, "basis": "since_start",
            "start_date": start.isoformat() if start else None}

def _friendly_error(raw: str) -> str:
    """Translate raw Alpaca API errors into user-facing guidance."""
    if "unauthorized" in raw.lower():
        return (
            "Alpaca rejected the stored API keys for this account (unauthorized). "
            "The keys were most likely regenerated or revoked — create new paper "
            "keys in your Alpaca dashboard, then re-enter them under Settings."
        )
    return raw


def _client(user_id: str, account_id: str) -> tuple[AlpacaAPI, str]:
    keys = get_alpaca_keys(user_id, account_id)
    if not keys:
        raise ValueError("Account credentials are unavailable.")
    # Alpaca uses separate paper/live hosts with otherwise identical keys. Probe
    # without mutating either account and retain the first successful endpoint.
    errors = []
    for paper in (True, False):
        client = AlpacaAPI(*keys, paper=paper)
        account = client.get_account()
        if isinstance(account, dict) and "error" not in account:
            client._dashboard_account = account  # type: ignore[attr-defined]
            return client, "paper" if paper else "live"
        errors.append(str(account.get("error", "unknown")) if isinstance(account, dict) else str(account))
    # Paper and live share the keys, so both probes usually fail identically.
    messages = list(dict.fromkeys(_friendly_error(e) for e in errors))
    raise ValueError("Could not read this Alpaca account: " + " ".join(messages))


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _history(client: AlpacaAPI, start: datetime, end: datetime) -> dict[str, list]:
    request = GetPortfolioHistoryRequest(
        start=start,
        end=end,
        timeframe="1H" if start.date() == end.date() else "1D",
        extended_hours=True,
        pnl_reset="per_day",
    )
    raw = client.trading_client.get_portfolio_history(request)
    if isinstance(raw, dict):
        data = raw
    elif hasattr(raw, "model_dump"):
        data = raw.model_dump()
    else:
        data = raw.dict()
    timestamps = data.get("timestamp") or []
    equity = data.get("equity") or []
    pnl = data.get("profit_loss") or []
    pnl_pct = data.get("profit_loss_pct") or []
    return {
        "timestamps": [
            datetime.fromtimestamp(int(v), tz=timezone.utc).isoformat() for v in timestamps
        ],
        "equity": [_number(v) for v in equity],
        "pnl": [_number(v) for v in pnl],
        "pnl_pct": [_number(v) for v in pnl_pct],
    }


def _period_deposits(client: Any, history: dict, start: datetime, end: datetime) -> tuple[float, bool]:
    """Net deposits booked after the baseline point's ET date through ``end`` (P&L excludes them)."""
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    stamps = history.get("timestamps") or []
    try:
        base_day = datetime.fromisoformat(stamps[0]).astimezone(et).date() if stamps else None
    except ValueError:
        base_day = None
    if base_day is not None and len(stamps) == 1 and base_day >= end.astimezone(et).date():
        base_day = None  # no real history: baseline is last_equity (prior close) -> today's flows
    since = (base_day or start.astimezone(et).date()) - timedelta(days=1)
    rows = fetch_flows(client, since)
    if rows is None:
        return 0.0, False
    through = end.astimezone(et).date()
    after = base_day if base_day is not None else through - timedelta(days=1)
    return net_flows(rows, after, through), True


def _one_account(user_id: str, account: dict, period: str) -> dict[str, Any]:
    start, end = period_bounds(period)
    client, environment = _client(user_id, account["account_id"])
    live = client._dashboard_account  # type: ignore[attr-defined]
    positions = client.get_positions()
    if not isinstance(positions, list):
        positions = []
    positions = [p for p in positions
                 if str(p.get("symbol") or "").upper() not in {"BNBX"}]
    try:
        history = _history(client, start, end)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Portfolio history unavailable for %s: %s", account["account_id"], exc)
        history = {"timestamps": [end.isoformat()], "equity": [_number(live.get("equity"))],
                   "pnl": [], "pnl_pct": []}
    contributors = sorted(
        ({
            "symbol": p.get("symbol", "?"),
            "pnl": _number(p.get("unrealized_pl")),
            "pnl_pct": _number(p.get("unrealized_plpc")) * 100,
            "market_value": _number(p.get("market_value")),
        } for p in positions),
        key=lambda row: row["pnl"],
        reverse=True,
    )
    equity = _number(live.get("equity"))
    baseline = history["equity"][0] if history["equity"] else _number(live.get("last_equity"))
    deposits, flows_ok = _period_deposits(client, history, start, end)
    period_pnl, period_pct = adjusted_pnl(equity, baseline, deposits)
    return {
        "account_id": account["account_id"],
        "account_name": account["account_name"],
        "environment": environment,
        "equity": equity,
        "portfolio_value": _number(live.get("portfolio_value")),
        "cash": _number(live.get("cash")),
        "buying_power": _number(live.get("buying_power")),
        "period_pnl": period_pnl or 0.0,
        "period_pct": period_pct or 0.0,
        "net_deposits": deposits, "cash_flows_ok": flows_ok,
        "unrealized_pnl": sum(row["pnl"] for row in contributors),
        "history": history,
        "contributors": contributors,
        "positions": positions,
    }


def _one_live_account(user_id: str, account: dict, period: str) -> dict[str, Any]:
    """Read-only live snapshot shaped like `_one_account` for the dashboard."""
    from engine.brokers.alpaca_live_readonly import (
        LiveReadOnlyClient, LiveReadOnlyError, summarize_account,
    )
    from engine.live_accounts import get_live_account_credentials

    start, end = period_bounds(period)
    creds = get_live_account_credentials(user_id, account.get("account_number"))
    if not creds:
        raise ValueError("Live account credentials are unavailable.")
    client = LiveReadOnlyClient(
        creds["api_key"], creds["secret_key"],
        expected_account_number=creds["account_number"],
    )
    try:
        snap = client.snapshot()
    except LiveReadOnlyError as exc:
        raise ValueError(str(exc)) from exc
    live = summarize_account(snap["account"])
    positions = snap.get("positions") or []
    if not isinstance(positions, list):
        positions = []
    positions = [p for p in positions
                 if str(p.get("symbol") or "").upper() not in {"BNBX"}]
    try:
        hist_raw = client.get_portfolio_history(
            start.date().isoformat(),
            end.date().isoformat(),
            timeframe="1H" if start.date() == end.date() else "1D",
        )
        timestamps = hist_raw.get("timestamp") or []
        equity_hist = hist_raw.get("equity") or []
        history = {
            "timestamps": [
                datetime.fromtimestamp(int(v), tz=timezone.utc).isoformat()
                for v in timestamps
            ],
            "equity": [_number(v) for v in equity_hist],
            "pnl": [_number(v) for v in (hist_raw.get("profit_loss") or [])],
            "pnl_pct": [_number(v) for v in (hist_raw.get("profit_loss_pct") or [])],
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Live portfolio history unavailable for %s: %s",
                       account["account_id"], exc)
        history = {
            "timestamps": [end.isoformat()],
            "equity": [_number(live.get("equity"))],
            "pnl": [], "pnl_pct": [],
        }
    contributors = sorted(
        ({
            "symbol": p.get("symbol", "?"),
            "pnl": _number(p.get("unrealized_pl")),
            "pnl_pct": _number(p.get("unrealized_plpc")) * 100,
            "market_value": _number(p.get("market_value")),
        } for p in positions),
        key=lambda row: row["pnl"],
        reverse=True,
    )
    equity = _number(live.get("equity"))
    baseline = history["equity"][0] if history["equity"] else _number(live.get("last_equity"))
    deposits, flows_ok = _period_deposits(client, history, start, end)
    period_pnl, period_pct = adjusted_pnl(equity, baseline, deposits)
    return {
        "account_id": account["account_id"],
        "account_name": account["account_name"],
        "environment": "live",
        "equity": equity,
        "portfolio_value": equity,
        "cash": _number(live.get("cash")),
        "buying_power": _number(live.get("buying_power")),
        "period_pnl": period_pnl or 0.0,
        "period_pct": period_pct or 0.0,
        "net_deposits": deposits, "cash_flows_ok": flows_ok,
        "unrealized_pnl": sum(row["pnl"] for row in contributors),
        "history": history,
        "contributors": contributors,
        "positions": positions,
    }



def _aggregate(accounts: list[dict[str, Any]], period: str) -> dict[str, Any]:
    by_time: dict[str, float] = defaultdict(float)
    for account in accounts:
        for stamp, equity in zip(account["history"]["timestamps"], account["history"]["equity"]):
            by_time[stamp] += equity
    timestamps = sorted(by_time)
    equity_series = [by_time[stamp] for stamp in timestamps]
    equity = sum(a["equity"] for a in accounts)
    period_pnl = sum(a["period_pnl"] for a in accounts)
    deposits = sum(a.get("net_deposits") or 0.0 for a in accounts)
    baseline = equity - period_pnl - deposits
    contributors: dict[str, dict[str, Any]] = {}
    for account in accounts:
        for row in account["contributors"]:
            item = contributors.setdefault(row["symbol"], {
                "symbol": row["symbol"], "pnl": 0.0, "market_value": 0.0,
            })
            item["pnl"] += row["pnl"]
            item["market_value"] += row["market_value"]
    return {
        "account_id": "all",
        "account_name": "All accounts",
        "environment": "mixed" if len({a["environment"] for a in accounts}) > 1
        else (accounts[0]["environment"] if accounts else ""),
        "equity": equity,
        "portfolio_value": sum(a["portfolio_value"] for a in accounts),
        "cash": sum(a["cash"] for a in accounts),
        "buying_power": sum(a["buying_power"] for a in accounts),
        "period_pnl": period_pnl,
        "period_pct": period_pnl / (baseline + max(0.0, deposits)) * 100 if baseline else 0,
        "net_deposits": deposits,
        "cash_flows_ok": all(a.get("cash_flows_ok", True) for a in accounts),
        "unrealized_pnl": sum(a["unrealized_pnl"] for a in accounts),
        "history": {"timestamps": timestamps, "equity": equity_series, "pnl": [], "pnl_pct": []},
        "contributors": sorted(contributors.values(), key=lambda row: row["pnl"], reverse=True),
        "positions": [],
        "period": period,
    }


def dashboard_data(user_id: str, account_id: str | None, period: str) -> dict[str, Any]:
    """Build the dashboard, enforcing ownership for every requested account.

    Paper accounts come from ``user_accounts``. Linked live broker accounts
    (``user_live_broker_accounts``) appear in the same dropdown with ids
    ``live:<account_number>`` and load through the read-only live client.
    ``all`` still aggregates paper only so live money is never mixed in.
    """
    period = normalize_period(period)
    paper, live = _catalog(user_id)
    accounts = paper + live  # dropdown catalog
    if not accounts:
        return {"needs_account": True, "accounts": [], "period": period}
    requested = account_id if account_id == "all" or any(
        a["account_id"] == account_id for a in accounts
    ) else None
    loaded, errors = [], {}

    def _load_one(account: dict) -> dict[str, Any]:
        if account.get("kind") == "live" or is_live_dashboard_id(account.get("account_id")):
            return _one_live_account(user_id, account, period)
        return _one_account(user_id, account, period)

    def _attempt(req: str | None) -> None:
        for account in accounts:
            # "All accounts" = all paper; live stays a separate selection.
            if req == "all" and account.get("kind") == "live":
                continue
            if req not in (None, "all") and account["account_id"] != req:
                continue
            try:
                loaded.append(_load_one(account))
            except Exception as exc:  # noqa: BLE001
                errors[account["account_id"]] = {
                    "account_id": account["account_id"], "message": str(exc),
                }

    _attempt(requested)
    if not loaded and requested not in (None, "all"):
        # The explicitly selected (or session-remembered) account failed to
        # load — fall back to every account so one broken connection can't
        # blank the dashboard.
        _attempt(None)
    if not loaded:
        # Nothing loaded; surface the errors instead of an empty selection.
        return {"needs_account": False, "accounts": accounts, "errors": list(errors.values()),
                "period": period, "has_live": bool(live)}
    selected = _aggregate(loaded, period) if requested == "all" else max(
        loaded, key=lambda row: (bool(row["history"]["equity"]), row["equity"])
    )
    live_selected = is_live_dashboard_id(selected["account_id"])
    ranking_account = (
        None if selected["account_id"] == "all" or live_selected
        else selected["account_id"]
    )
    reporter = ReportAgent()
    advisor_history: list[dict[str, Any]] = []
    latest_advisors: list[dict[str, Any]] = []
    if not live_selected:
        try:
            from engine.reporting.advisor import list_reports_for_user

            advisor_history = list_reports_for_user(
                user_id, account_id=ranking_account,
                limit=100 if ranking_account is None else 20,
            )
            if selected["account_id"] == "all":
                seen_accounts = set()
                for report in advisor_history:
                    if report["account_id"] not in seen_accounts:
                        latest_advisors.append(report)
                        seen_accounts.add(report["account_id"])
            elif advisor_history:
                latest_advisors = advisor_history[:1]
        except Exception as exc:  # noqa: BLE001
            # The dashboard remains available before migration 19 is applied.
            logger.warning("Daily advisor reports unavailable: %s", type(exc).__name__)
    try:
        annualized = since_start_annualized(user_id, selected)
        if annualized.get("simple_pct") is None and selected["account_id"] == "all":
            annualized = {**period_annualized(period, selected.get("period_pct")),
                          "basis": period}
    except Exception:  # noqa: BLE001
        annualized = {"simple_pct": None, "compound_pct": None, "days": 0}
    return {
        **selected,
        "annualized": annualized,
        "needs_account": False,
        "accounts": accounts,
        "has_live": bool(live),
        "errors": list(errors.values()),
        "period": period,
        "paper_rankings": [] if live_selected else reporter.top_strategies(
            trade_type="paper", limit=8, user_id=user_id, account_id=ranking_account),
        "backtest_rankings": [] if live_selected else reporter.top_strategies(
            trade_type="backtest", limit=8, user_id=user_id, account_id=ranking_account),
        "advisor_report": latest_advisors[0] if latest_advisors else None,
        "advisor_reports": latest_advisors,
        "advisor_history": advisor_history,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


def commentary(user_id: str, data: dict[str, Any]) -> str:
    """Return the exact persisted advisor summary used by email and chat."""
    del user_id  # retained for compatibility with existing callers
    report = data.get("advisor_report") or {}
    advisory = report.get("advisory") or {}
    if advisory.get("summary"):
        return str(advisory["summary"])
    return "No post-close daily advisor report has been generated for this paper account yet."
