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

logger = logging.getLogger(__name__)


def period_bounds(period: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return UTC bounds for the current calendar day, week, or month."""
    now = now or datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc)
    if period == "weekly":
        start_date = now.date() - timedelta(days=now.weekday())
    elif period == "monthly":
        start_date = now.date().replace(day=1)
    else:
        start_date = now.date()
    return datetime.combine(start_date, time.min, tzinfo=timezone.utc), now


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


def _one_account(user_id: str, account: dict, period: str) -> dict[str, Any]:
    start, end = period_bounds(period)
    client, environment = _client(user_id, account["account_id"])
    live = client._dashboard_account  # type: ignore[attr-defined]
    positions = client.get_positions()
    if not isinstance(positions, list):
        positions = []
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
    period_pnl = equity - baseline
    return {
        "account_id": account["account_id"],
        "account_name": account["account_name"],
        "environment": environment,
        "equity": equity,
        "portfolio_value": _number(live.get("portfolio_value")),
        "cash": _number(live.get("cash")),
        "buying_power": _number(live.get("buying_power")),
        "period_pnl": period_pnl,
        "period_pct": period_pnl / baseline * 100 if baseline else 0,
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
    baseline = equity - period_pnl
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
        "period_pct": period_pnl / baseline * 100 if baseline else 0,
        "unrealized_pnl": sum(a["unrealized_pnl"] for a in accounts),
        "history": {"timestamps": timestamps, "equity": equity_series, "pnl": [], "pnl_pct": []},
        "contributors": sorted(contributors.values(), key=lambda row: row["pnl"], reverse=True),
        "positions": [],
        "period": period,
    }


def dashboard_data(user_id: str, account_id: str | None, period: str) -> dict[str, Any]:
    """Build the dashboard, enforcing ownership for every requested account."""
    period = period if period in {"daily", "weekly", "monthly"} else "daily"
    accounts = get_user_accounts(user_id)
    if not accounts:
        return {"needs_account": True, "accounts": [], "period": period}
    requested = account_id if account_id == "all" or any(
        a["account_id"] == account_id for a in accounts
    ) else None
    loaded, errors = [], {}

    def _attempt(req: str | None) -> None:
        for account in accounts:
            if req not in (None, "all") and account["account_id"] != req:
                continue
            try:
                loaded.append(_one_account(user_id, account, period))
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
                "period": period}
    selected = _aggregate(loaded, period) if requested == "all" else max(
        loaded, key=lambda row: (bool(row["history"]["equity"]), row["equity"])
    )
    ranking_account = None if selected["account_id"] == "all" else selected["account_id"]
    reporter = ReportAgent()
    advisor_history: list[dict[str, Any]] = []
    latest_advisors: list[dict[str, Any]] = []
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
    return {
        **selected,
        "needs_account": False,
        "accounts": accounts,
        "errors": list(errors.values()),
        "period": period,
        "paper_rankings": reporter.top_strategies(
            trade_type="paper", limit=8, user_id=user_id, account_id=ranking_account),
        "backtest_rankings": reporter.top_strategies(
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
