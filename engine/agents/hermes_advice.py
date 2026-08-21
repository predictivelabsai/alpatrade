"""Hermes-only portfolio construction, monitoring advice, and delivery."""
from __future__ import annotations

import html
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text

from engine.db.pool import DatabasePool


VALID_CHANNELS = {"in_app", "email", "both", "none"}


def _pool() -> DatabasePool:
    return DatabasePool()


def normalize_channel(value: str) -> str:
    channel = (value or "in_app").strip().lower().replace("-", "_")
    if channel not in VALID_CHANNELS:
        raise ValueError("Notification channel must be in_app, email, both, or none")
    return channel


def _percent(value: Any, default: float) -> float:
    """Convert stored strategy fractions to display/execution percentages."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number * 100 if 0 < number <= 1 else number


def _risk_weights(symbols: list[str], budget: float, cap: float) -> tuple[dict, str]:
    """Use inverse recent volatility, with a deterministic equal-weight fallback."""
    volatilities = {}
    try:
        from engine.feeds.market_data import get_historical_data
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=120)
        for symbol in symbols:
            frame = get_historical_data(symbol, start, end)
            if frame is None or frame.empty or "Close" not in frame:
                continue
            closes = frame["Close"]
            if getattr(closes, "ndim", 1) > 1:
                closes = closes.iloc[:, 0]
            returns = closes.astype(float).pct_change().dropna()
            volatility = float(returns.std())
            if volatility > 0:
                volatilities[symbol] = volatility
    except Exception:
        volatilities = {}
    if len(volatilities) != len(symbols):
        equal = min(cap, budget / len(symbols))
        return {symbol: round(equal, 6) for symbol in symbols}, "capped_equal_weight"
    inverse = {symbol: 1 / value for symbol, value in volatilities.items()}
    total = sum(inverse.values())
    weights = {symbol: min(cap, budget * inverse[symbol] / total) for symbol in symbols}
    return {symbol: round(weight, 6) for symbol, weight in weights.items()}, "inverse_120d_volatility"


def construct_portfolio(candidate_id: str, user_id: str, thread_id: str) -> dict:
    """Create and persist an owned, paper-only portfolio recommendation."""
    with _pool().get_session() as session:
        row = session.execute(text("""
            SELECT candidate_id, account_id, strategy, symbols, params, metrics
            FROM alpatrade.strategy_candidates
            WHERE candidate_id = CAST(:candidate_id AS UUID)
              AND user_id = CAST(:uid AS UUID)
        """), {"candidate_id": candidate_id, "uid": user_id}).mappings().first()
    if not row:
        raise ValueError("Candidate was not found under your account")

    symbols = [str(symbol).upper() for symbol in (row["symbols"] or [])]
    if not symbols:
        raise ValueError("Candidate has no symbols to construct a portfolio")
    params = dict(row["params"] or {})
    requested = float(params.get("position_size") or (1 / len(symbols)))
    if requested <= 0:
        requested = 1 / len(symbols)
    per_symbol_cap = min(0.25, requested)
    budget = min(1.0, per_symbol_cap * len(symbols))
    allocations, method = _risk_weights(symbols, budget, per_symbol_cap)
    invested = sum(allocations.values())
    snapshot = {
        "strategy": row["strategy"],
        "allocations": allocations,
        "construction_method": method,
        "cash_reserve": round(max(0.0, 1 - invested), 6),
        "entry": {"dip_threshold_pct": _percent(params.get("dip_threshold"), 3.0)},
        "exit": {
            "take_profit_pct": _percent(
                params.get("take_profit", params.get("take_profit_threshold")), 1.5
            ),
            "stop_loss_pct": _percent(
                params.get("stop_loss", params.get("stop_loss_threshold")), 0.5
            ),
            "max_hold_days": int(params.get("hold_days", 2)),
        },
        "source_metrics": dict(row["metrics"] or {}),
        "paper_only": True,
    }
    allocations_text = ", ".join(
        f"{symbol} {weight:.1%}" for symbol, weight in allocations.items()
    )
    summary = f"Suggested {row['strategy']} portfolio: {allocations_text}; cash {snapshot['cash_reserve']:.1%}."
    rationale = (
        f"Construction method: {method}. Weights obey the candidate position-size limit "
        "and a 25% hard cap. This is advice only until you explicitly start or modify a paper job."
    )
    advice_id = save_advice(
        user_id=user_id, account_id=str(row["account_id"]) if row["account_id"] else None,
        candidate_id=candidate_id, thread_id=thread_id, advice_type="portfolio",
        action="RECOMMEND", severity="info", summary=summary, rationale=rationale,
        snapshot=snapshot,
    )
    return {"advice_id": advice_id, "candidate_id": candidate_id,
            "summary": summary, "rationale": rationale, "snapshot": snapshot}


def position_advice(positions: list[dict], symbols: list[str], params: dict) -> list[dict]:
    """Produce transparent entry/exit observations without placing orders."""
    take_profit = (float(params["take_profit_threshold"])
                   if params.get("take_profit_threshold") is not None
                   else _percent(params.get("take_profit"), 1.5))
    stop_loss = (float(params["stop_loss_threshold"])
                 if params.get("stop_loss_threshold") is not None
                 else _percent(params.get("stop_loss"), 0.5))
    held = set()
    advice: list[dict] = []
    for position in positions:
        symbol = str(position.get("symbol") or "").upper()
        if not symbol:
            continue
        held.add(symbol)
        plpc = position.get("unrealized_plpc")
        pnl_pct = float(plpc) * 100 if plpc not in (None, "") else 0.0
        if pnl_pct >= take_profit:
            action, advice_type, severity = "EXIT", "exit", "action"
            rationale = f"Unrealized return {pnl_pct:.2f}% reached the {take_profit:.2f}% take-profit level."
        elif pnl_pct <= -stop_loss:
            action, advice_type, severity = "EXIT", "exit", "action"
            rationale = f"Unrealized return {pnl_pct:.2f}% crossed the -{stop_loss:.2f}% stop-loss level."
        elif pnl_pct >= take_profit * 0.8 or pnl_pct <= -stop_loss * 0.8:
            action, advice_type, severity = "WATCH_EXIT", "exit", "watch"
            rationale = "Position is within 20% of an approved exit threshold."
        else:
            action, advice_type, severity = "HOLD", "hold", "info"
            rationale = "Neither the approved take-profit nor stop-loss threshold is met."
        advice.append({
            "symbol": symbol, "advice_type": advice_type, "action": action,
            "severity": severity, "summary": f"{symbol}: {action}",
            "rationale": rationale,
            "snapshot": {"unrealized_pct": pnl_pct, "take_profit_pct": take_profit,
                         "stop_loss_pct": stop_loss},
        })
    for symbol in symbols:
        symbol = str(symbol).upper()
        if symbol not in held:
            advice.append({
                "symbol": symbol, "advice_type": "entry", "action": "WATCH_ENTRY",
                "severity": "watch", "summary": f"{symbol}: WATCH_ENTRY",
                "rationale": "No open position. Enter only when the configured dip signal is confirmed.",
                "snapshot": {"dip_threshold_pct": float(params.get("dip_threshold", 3.0))},
            })
    return advice


def save_advice(*, user_id: str, advice_type: str, action: str, severity: str,
                summary: str, rationale: str, snapshot: dict,
                symbol: Optional[str] = None,
                account_id: Optional[str] = None, job_id: Optional[str] = None,
                candidate_id: Optional[str] = None, thread_id: Optional[str] = None) -> str:
    with _pool().get_session() as session:
        advice_id = session.execute(text("""
            INSERT INTO alpatrade.hermes_advice
                (user_id, account_id, job_id, candidate_id, thread_id, advice_type,
                 symbol, action, severity, summary, rationale, snapshot)
            VALUES
                (CAST(:uid AS UUID), CAST(:aid AS UUID), CAST(:job_id AS UUID),
                 CAST(:candidate_id AS UUID), CAST(:thread_id AS UUID), :advice_type,
                 :symbol, :action, :severity, :summary, :rationale, CAST(:snapshot AS JSONB))
            RETURNING advice_id
        """), {
            "uid": user_id, "aid": account_id, "job_id": job_id,
            "candidate_id": candidate_id, "thread_id": thread_id,
            "advice_type": advice_type, "symbol": symbol,
            "action": action, "severity": severity, "summary": summary,
            "rationale": rationale, "snapshot": json.dumps(snapshot, default=str),
        }).scalar_one()
    return str(advice_id)


def list_owned(user_id: str, *, job_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    where = "user_id = CAST(:uid AS UUID)"
    bind: dict[str, Any] = {"uid": user_id, "limit": limit}
    if job_id:
        where += " AND job_id = CAST(:job_id AS UUID)"
        bind["job_id"] = job_id
    with _pool().get_session() as session:
        rows = session.execute(text(f"""
            SELECT advice_id, account_id, job_id, candidate_id, thread_id, advice_type,
                   symbol, action, severity, summary, rationale, snapshot,
                   delivered_in_app, delivered_email, created_at
            FROM alpatrade.hermes_advice WHERE {where}
            ORDER BY created_at DESC LIMIT :limit
        """), bind).mappings().all()
    return [{key: str(value) if key.endswith("_id") and value else value
             for key, value in dict(row).items()} for row in rows]


def advice_email_html(items: list[dict]) -> str:
    if not items:
        return "<p>No new Hermes entry or exit advice.</p>"
    rows = "".join(
        f"<li><strong>{html.escape(str(item.get('summary', '')))}</strong> — "
        f"{html.escape(str(item.get('rationale', '')))}</li>" for item in items
    )
    return f"<h3>Hermes Agent Advice</h3><ul>{rows}</ul><p>Advice is informational; paper orders follow only the approved strategy rules.</p>"


def mark_delivered(advice_ids: list[str], *, in_app: bool = False,
                   email: bool = False) -> None:
    if not advice_ids:
        return
    with _pool().get_session() as session:
        session.execute(text("""
            UPDATE alpatrade.hermes_advice
            SET delivered_in_app = delivered_in_app OR :in_app,
                delivered_email = delivered_email OR :email
            WHERE advice_id = ANY(CAST(:ids AS UUID[]))
        """), {"ids": advice_ids, "in_app": in_app, "email": email})
