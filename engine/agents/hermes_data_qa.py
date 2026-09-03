"""Safe natural-language analytics over an owned Hermes run.

User language selects a read-only query shape. Identifiers, ownership filters,
schema, and parameters remain fixed by AlpaTrade; Hermes gets no DB credential.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import text

from engine.db.pool import DatabasePool


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
        return max((end - start).total_seconds() / 3600, 0.0)
    return None


def _money(value: float) -> str:
    return f"{'+' if value >= 0 else '-'}${abs(value):,.2f}"


def _percent(value: float) -> str:
    return f"{value:+.2f}%"


def _load_owned_run_trades(
    user_id: str, trade_type: str, run_id: str | None = None,
) -> dict[str, Any] | None:
    """Load only rows tied to the user's Hermes job in `alpatrade`."""
    with DatabasePool().get_session() as session:
        job = session.execute(text("""
            SELECT run_id, job_id, status
            FROM alpatrade.hermes_jobs
            WHERE user_id = CAST(:user_id AS UUID)
              AND kind = :kind
              AND (:run_id IS NULL OR run_id = :run_id)
            ORDER BY created_at DESC
            LIMIT 1
        """), {
            "user_id": user_id, "kind": trade_type, "run_id": run_id,
        }).mappings().first()
        if not job:
            return None
        rows = session.execute(text("""
            SELECT symbol, entry_time, exit_time, entry_price, exit_price,
                   shares, pnl, pnl_pct, reason
            FROM alpatrade.trades
            WHERE user_id = CAST(:user_id AS UUID)
              AND run_id = :run_id AND trade_type = :trade_type
            ORDER BY entry_time ASC, id ASC
        """), {
            "user_id": user_id, "run_id": job["run_id"],
            "trade_type": trade_type,
        }).mappings().all()
    return {"run_id": str(job["run_id"]), "job_id": str(job["job_id"]),
            "status": job["status"], "trades": [dict(row) for row in rows]}


def is_trade_data_question(question: str) -> bool:
    """Recognize read-only questions handled by safe SQL templates."""
    lowered = question.lower()
    data_terms = (
        "pnl", "p&l", "profit", "loss", "return", "win rate", "holding",
        "how many trades", "trade count", "trades by", "performance by",
    )
    return ("backtest" in lowered or "paper" in lowered) and any(
        term in lowered for term in data_terms
    )


def render_trade_question(result: dict[str, Any], question: str, trade_type: str) -> str:
    """Answer supported analytics questions from owned database rows."""
    trades = list(result.get("trades") or [])
    title = f"Hermes {trade_type} data answer"
    if not trades:
        return (f"## {title}\n\nRun `{result['run_id']}` has no saved {trade_type} "
                "trades yet. A running paper job may be waiting for a signal.")

    closed = [trade for trade in trades if trade.get("exit_time") is not None]
    analyzed = closed
    lowered = question.lower()
    pnl = [_number(trade.get("pnl")) for trade in analyzed]
    returns = [_return_pct(trade) for trade in analyzed]
    holds = [hours for trade in analyzed
             if (hours := _holding_hours(trade)) is not None]
    wins = sum(value > 0 for value in pnl)
    avg_hold = f"{sum(holds) / len(holds) / 24:.1f} days" if holds else "n/a"
    total_pnl = _money(sum(pnl)) if closed else "N/A"
    average_return = _percent(sum(returns) / len(returns)) if returns else "N/A"
    win_rate = f"{wins / len(pnl) * 100:.1f}%" if pnl else "N/A"
    summary = (
        "| Run | Saved trades | Closed trades | Total P&L | Average return | Win rate | Average hold |\n"
        "|---|---:|---:|---:|---:|---:|---:|\n"
        f"| `{result['run_id']}` | {len(trades)} | {len(closed)} | {total_pnl} | "
        f"{average_return} | {win_rate} | {avg_hold} |"
    )

    if not closed:
        return (
            f"## {title}\n\n{summary}\n\nNo completed exits are saved, so realized "
            "P&L, return, win rate, and holding-period statistics are not available yet."
        )

    if "symbol" in lowered or "ticker" in lowered or " by " in lowered:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for trade in analyzed:
            grouped[str(trade.get("symbol") or "—")].append(trade)
        lines = [summary, "", "| Symbol | Trades | Total P&L | Average return |",
                 "|---|---:|---:|---:|"]
        ranked = sorted(grouped.items(), key=lambda item: sum(
            _number(trade.get("pnl")) for trade in item[1]
        ), reverse=True)
        for symbol, items in ranked:
            item_returns = [_return_pct(item) for item in items]
            lines.append(
                f"| {symbol} | {len(items)} | "
                f"{_money(sum(_number(item.get('pnl')) for item in items))} | "
                f"{_percent(sum(item_returns) / len(item_returns))} |"
            )
        return f"## {title}\n\n" + "\n".join(lines)

    if any(term in lowered for term in ("most profitable", "best trade")):
        selected = max(analyzed, key=lambda trade: _number(trade.get("pnl")))
    elif any(term in lowered for term in
             ("least profitable", "worst trade", "biggest loss")):
        selected = min(analyzed, key=lambda trade: _number(trade.get("pnl")))
    else:
        return f"## {title}\n\n{summary}"

    return (
        f"## {title}\n\n{summary}\n\n"
        "| Symbol | Entry | Exit | P&L | Return | Reason |\n"
        "|---|---:|---:|---:|---:|---|\n"
        f"| {selected.get('symbol') or '—'} | ${_number(selected.get('entry_price')):,.2f} | "
        f"${_number(selected.get('exit_price')):,.2f} | {_money(_number(selected.get('pnl')))} | "
        f"{_percent(_return_pct(selected))} | {selected.get('reason') or '—'} |"
    )


def answer_owned_trade_question(
    user_id: str, question: str, run_id: str | None = None,
) -> str:
    """Plan and execute an owned, parameterized read-only trade query."""
    trade_type = "paper" if "paper" in question.lower() else "backtest"
    result = _load_owned_run_trades(user_id, trade_type, run_id)
    if not result:
        return f"## Hermes {trade_type} data answer\n\nNo owned Hermes {trade_type} run was found."
    return render_trade_question(result, question, trade_type)
