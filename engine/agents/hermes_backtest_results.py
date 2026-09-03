"""Owned, read-only Hermes backtest trade analytics from PostgreSQL."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from sqlalchemy import text

from engine.db.pool import DatabasePool


def load_owned_backtest_trades(user_id: str, run_id: str | None = None) -> dict[str, Any] | None:
    """Load a user's completed Hermes backtest and its trades from alpatrade only."""
    with DatabasePool().get_session() as session:
        job = session.execute(text("""
            SELECT run_id, job_id, completed_at
            FROM alpatrade.hermes_jobs
            WHERE user_id = CAST(:user_id AS UUID)
              AND kind = 'backtest' AND status = 'completed'
              AND (:run_id IS NULL OR run_id = :run_id)
            ORDER BY completed_at DESC NULLS LAST, created_at DESC
            LIMIT 1
        """), {"user_id": user_id, "run_id": run_id}).mappings().first()
        if not job:
            return None
        rows = session.execute(text("""
            SELECT symbol, entry_time, exit_time, entry_price, exit_price,
                   shares, pnl, pnl_pct, reason
            FROM alpatrade.trades
            WHERE user_id = CAST(:user_id AS UUID)
              AND run_id = :run_id AND trade_type = 'backtest'
            ORDER BY entry_time ASC, id ASC
        """), {"user_id": user_id, "run_id": job["run_id"]}).mappings().all()
    return {"run_id": str(job["run_id"]), "job_id": str(job["job_id"]),
            "trades": [dict(row) for row in rows]}


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _return_pct(trade: dict[str, Any]) -> float:
    if trade.get("pnl_pct") is not None:
        return _number(trade["pnl_pct"])
    basis = _number(trade.get("entry_price")) * _number(trade.get("shares"))
    return (_number(trade.get("pnl")) / basis * 100) if basis else 0.0


def _holding_hours(trade: dict[str, Any]) -> float | None:
    start, end = trade.get("entry_time"), trade.get("exit_time")
    if isinstance(start, datetime) and isinstance(end, datetime):
        return max(0.0, (end - start).total_seconds() / 3600)
    return None


def _date(value: Any) -> str:
    return value.strftime("%Y-%m-%d") if hasattr(value, "strftime") else "—"


def _money(value: Any) -> str:
    number = _number(value)
    return f"{'+' if number >= 0 else '-'}${abs(number):,.2f}"


def _percent(value: Any) -> str:
    number = _number(value)
    return f"{number:+.2f}%"


def render_trade_analysis(
    result: dict[str, Any],
    view: Literal["all", "best", "worst", "holding"],
    *,
    row_limit: int = 50,
) -> str:
    """Render compact Markdown focused on realized P&L and return."""
    trades = list(result.get("trades") or [])
    heading = {
        "all": "Hermes backtest trades",
        "best": "Most profitable Hermes backtest trade",
        "worst": "Least profitable Hermes backtest trade",
        "holding": "Hermes backtest holding period",
    }[view]
    if not trades:
        return (f"## {heading}\n\nNo saved backtest trades were found for run "
                f"`{result['run_id']}`.")

    returns = [_return_pct(trade) for trade in trades]
    pnl_values = [_number(trade.get("pnl")) for trade in trades]
    holding = [hours for trade in trades if (hours := _holding_hours(trade)) is not None]
    wins = sum(1 for pnl in pnl_values if pnl > 0)
    avg_hours = sum(holding) / len(holding) if holding else None
    avg_hold = f"{avg_hours / 24:.1f} days" if avg_hours is not None else "n/a"
    summary = (
        "| Trades | Total P&L | Average return | Win rate | Average hold |\n"
        "|---:|---:|---:|---:|---:|\n"
        f"| {len(trades)} | {_money(sum(pnl_values))} | "
        f"{_percent(sum(returns) / len(returns))} | "
        f"{wins / len(trades) * 100:.1f}% | {avg_hold} |"
    )
    if view == "holding":
        return f"## {heading}\n\nRun `{result['run_id']}`\n\n{summary}"

    if view == "best":
        selected = [max(trades, key=lambda trade: _number(trade.get("pnl")))]
    elif view == "worst":
        selected = [min(trades, key=lambda trade: _number(trade.get("pnl")))]
    else:
        selected = trades[:row_limit]

    lines = [
        f"## {heading}", "", f"Run `{result['run_id']}` — database results", "",
        summary, "", "| # | Symbol | Entry | Exit | P&L | Return |",
        "|---:|---|---|---|---:|---:|",
    ]
    for index, trade in enumerate(selected, 1):
        lines.append(
            f"| {index} | {trade.get('symbol') or '—'} | {_date(trade.get('entry_time'))} "
            f"| {_date(trade.get('exit_time'))} | {_money(trade.get('pnl'))} "
            f"| {_percent(_return_pct(trade))} |"
        )
    if view == "all" and len(trades) > len(selected):
        lines.extend(["", f"Showing {len(selected)} of {len(trades)} trades."])
    return "\n".join(lines)


def owned_trade_analysis(user_id: str, view: str, run_id: str | None = None) -> str:
    result = load_owned_backtest_trades(user_id, run_id)
    if not result:
        return "## Hermes backtest trades\n\nNo completed Hermes backtest was found."
    return render_trade_analysis(result, view)  # type: ignore[arg-type]
