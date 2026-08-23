"""Hermes-only portfolio construction, monitoring advice, and delivery."""
from __future__ import annotations

import html
import json
import math
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text

from engine.db.pool import DatabasePool


VALID_CHANNELS = {"in_app", "email", "both", "none"}
GAIN_COLOR = "#18864b"
LOSS_COLOR = "#c53b3b"
WATCH_COLOR = "#b7791f"
INFO_COLOR = "#315f85"


def assess_performance_drift(
    validation_sharpe: Any, trades: list[dict], *, minimum_exits: int = 20,
    ratio: float = 0.5,
) -> dict:
    """Return a conservative drift decision from closed paper-trade returns."""
    closed = [trade for trade in trades if trade.get("pnl_pct") is not None]
    daily: dict[str, float] = {}
    for trade in closed:
        timestamp = str(trade.get("exit_time") or trade.get("timestamp") or "")
        day = timestamp[:10]
        if day:
            daily[day] = daily.get(day, 0.0) + float(trade.get("pnl_pct") or 0)
    observed = None
    if len(closed) >= minimum_exits and len(daily) >= 5:
        returns = list(daily.values())
        deviation = statistics.stdev(returns)
        observed = ((statistics.mean(returns) / deviation) * math.sqrt(252)
                    if deviation > 0 else 0.0)
    try:
        expected = float(validation_sharpe)
    except (TypeError, ValueError):
        expected = None
    threshold = expected * ratio if expected is not None else None
    drift = bool(observed is not None and threshold is not None and observed < threshold)
    return {"drift": drift, "paper_sharpe": observed,
            "validation_sharpe": expected, "threshold": threshold,
            "closed_trades": len(closed), "observed_days": len(daily),
            "minimum_exits": minimum_exits}


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


def _trade_time(trade: dict) -> str:
    return str(trade.get("exit_time") or trade.get("timestamp") or
               trade.get("entry_time") or trade.get("created_at") or "")


def _is_closed(trade: dict) -> bool:
    return trade.get("pnl") is not None and bool(
        trade.get("exit_time") or trade.get("exit_price") is not None
    )


def _group_fills(trades: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str], dict] = {}
    for trade in trades:
        if _is_closed(trade):
            continue
        symbol = str(trade.get("symbol") or "").upper()
        side = str(trade.get("side") or trade.get("direction") or "buy").lower()
        if not symbol:
            continue
        qty = abs(float(trade.get("qty") or trade.get("shares") or 0))
        price = float(trade.get("price") or trade.get("entry_price") or 0)
        group = groups.setdefault((symbol, side), {
            "symbol": symbol, "side": side, "fills": 0,
            "quantity": 0.0, "notional": 0.0,
        })
        group["fills"] += 1
        group["quantity"] += qty
        group["notional"] += qty * price
    result = []
    for group in groups.values():
        quantity = group["quantity"]
        group["average_price"] = group.pop("notional") / quantity if quantity else 0.0
        result.append(group)
    return sorted(result, key=lambda item: (item["symbol"], item["side"]))


def reconcile_positions(positions: list[dict], trades: list[dict], *, tolerance: float = 1e-6) -> dict:
    """Verify broker quantities cover this run's persisted open quantities."""
    expected: dict[str, float] = {}
    for trade in trades:
        if _is_closed(trade):
            continue
        symbol = str(trade.get("symbol") or "").upper()
        if not symbol:
            continue
        qty = abs(float(trade.get("qty") or trade.get("shares") or 0))
        direction = str(trade.get("side") or trade.get("direction") or "buy").lower()
        expected[symbol] = expected.get(symbol, 0.0) + (-qty if direction == "sell" else qty)
    actual = {
        str(item.get("symbol") or "").upper(): float(item.get("qty") or 0)
        for item in positions if item.get("symbol")
    }
    # Broker positions are account-wide and may belong to another paper run;
    # only compare symbols this Hermes run expects to own.
    symbols = sorted(expected)
    differences = [
        {"symbol": symbol, "expected_qty": expected.get(symbol, 0.0),
         "broker_qty": actual.get(symbol, 0.0),
         "difference": actual.get(symbol, 0.0) - expected.get(symbol, 0.0)}
        for symbol in symbols
        if actual.get(symbol, 0.0) + tolerance < expected.get(symbol, 0.0)
    ]
    return {"ok": not differences, "differences": differences,
            "expected_symbols": len(expected), "broker_symbols": len(actual)}


def build_performance_report(
    *, date: str, positions: list[dict], trades: list[dict], advice: list[dict],
    job_id: str, run_id: str, candidate_id: str,
) -> dict:
    """Create one internally consistent Hermes daily-report data model."""
    closed = [trade for trade in trades if _is_closed(trade)]
    closed_today = [trade for trade in closed if _trade_time(trade).startswith(date)]
    entries_today = [trade for trade in trades
                     if not _is_closed(trade) and _trade_time(trade).startswith(date)]
    realized_today = sum(float(trade.get("pnl") or 0) for trade in closed_today)
    realized_session = sum(float(trade.get("pnl") or 0) for trade in closed)
    unrealized = sum(float(position.get("unrealized_pl") or 0) for position in positions)
    wins = sum(1 for trade in closed if float(trade.get("pnl") or 0) > 0)
    losses = sum(1 for trade in closed if float(trade.get("pnl") or 0) < 0)
    win_rate = wins / len(closed) * 100 if closed else 0.0
    stop_exits = [trade for trade in closed_today
                  if "STOP_LOSS" in str(trade.get("reason") or "").upper()]
    grouped_entries = _group_fills(entries_today)
    repeated = [group for group in grouped_entries if group["fills"] > 1]
    reconciliation = reconcile_positions(positions, trades)

    best_positions = sorted(
        positions, key=lambda item: float(item.get("unrealized_pl") or 0), reverse=True
    )
    if realized_today < 0 or len(stop_exits) >= 2 or any(
        group["fills"] >= 4 for group in repeated
    ):
        status, color = "RED", LOSS_COLOR
        reasons = []
        if realized_today < 0:
            reasons.append(f"Completed exits lost ${abs(realized_today):,.2f} today.")
        if stop_exits:
            reasons.append(f"{len(stop_exits)} stop-loss exit(s) were executed.")
        if repeated:
            symbols = ", ".join(group["symbol"] for group in repeated)
            reasons.append(f"Repeated entry fills were detected for {symbols}.")
        decision = "Pause and review before allowing further entries."
        commands = [
            f"/hermes pause paper job {job_id}",
            f"/hermes analyze paper job {job_id}",
            "/hermes run a 6-month buy_the_dip backtest for the same symbols, "
            "run the supported parameter grid, and maximize Sharpe",
        ]
    elif realized_today > 0 and not stop_exits:
        status, color = "GREEN", GAIN_COLOR
        contributors = [str(item.get("symbol")) for item in best_positions
                        if float(item.get("unrealized_pl") or 0) > 0][:3]
        reasons = [f"Completed exits gained ${realized_today:,.2f} today."]
        if contributors:
            reasons.append(
                "Largest account-wide open-position contributors: " +
                ", ".join(contributors) + "."
            )
        decision = "Keep the approved configuration running and collect more paper evidence."
        commands = [
            "/hermes show my recent advice",
            f"/hermes analyze paper job {job_id}",
            "/hermes run a 6-month buy_the_dip backtest for the same symbols and "
            "maximize Sharpe without changing my running paper job",
        ]
    else:
        status, color = "AMBER", WATCH_COLOR
        reasons = ["There is not yet enough positive realized evidence to classify the day as green."]
        if unrealized:
            direction = "gain" if unrealized > 0 else "loss"
            reasons.append(f"Open positions currently show an unrealized {direction} of ${abs(unrealized):,.2f}.")
        decision = "Continue cautiously, review concentration, and test robustness over a longer period."
        commands = [
            f"/hermes analyze paper job {job_id}",
            "/hermes run the same buy_the_dip parameter grid over 6 months and maximize Sharpe",
        ]

    if not reconciliation["ok"]:
        symbols = ", ".join(item["symbol"] for item in reconciliation["differences"][:6])
        status, color = "RED", LOSS_COLOR
        reasons.append(f"DB-to-broker position mismatch detected for {symbols}.")
        decision = "Pause new entries and reconcile the paper account before continuing."
        commands = [
            f"/hermes pause paper job {job_id}",
            f"/hermes analyze paper job {job_id}",
        ]

    return {
        "date": date, "status": status, "status_color": color,
        "realized_today": realized_today, "realized_session": realized_session,
        "unrealized": unrealized, "combined_current": realized_session + unrealized,
        "wins": wins, "losses": losses, "completed_exits": len(closed),
        "win_rate": win_rate, "positions": positions, "closed_today": closed_today,
        "grouped_entries": grouped_entries, "advice": advice,
        "reconciliation": reconciliation,
        "reasons": reasons, "decision": decision, "commands": commands,
        "job_id": job_id, "run_id": run_id, "candidate_id": candidate_id,
        "validated": abs(realized_today - sum(float(item.get("pnl") or 0)
                                                for item in closed_today)) < 0.005,
    }


def build_advice_alert_email(items: list[dict], context: dict) -> tuple[str, str]:
    """Render coherent immediate alerts with evidence and owner-safe identifiers."""
    losses = [item for item in items if float((item.get("snapshot") or {}).get("pnl") or 0) < 0]
    gains = [item for item in items if float((item.get("snapshot") or {}).get("pnl") or 0) > 0]
    exits = [item for item in items if item.get("action") == "EXIT_EXECUTED"]
    entries = [item for item in items if item.get("action") == "ENTRY_EXECUTED"]
    status = "RED" if losses else "GREEN" if gains else "AMBER" if exits else "INFO"
    color = (LOSS_COLOR if losses else GAIN_COLOR if gains else
             WATCH_COLOR if exits else INFO_COLOR)
    label = f"{len(entries)} entries" if entries else f"{len(exits)} exits" if exits else "portfolio update"
    rows = []
    for item in items:
        snapshot = item.get("snapshot") or {}
        pnl = snapshot.get("pnl")
        pnl_html = ""
        if pnl is not None:
            pnl_value = float(pnl)
            pnl_color = GAIN_COLOR if pnl_value >= 0 else LOSS_COLOR
            pnl_text = (f"+${pnl_value:,.2f}" if pnl_value > 0 else
                        f"-${abs(pnl_value):,.2f}" if pnl_value < 0 else "$0.00")
            pnl_html = f"<div><strong>P&amp;L:</strong> <span style='color:{pnl_color}'>{pnl_text}</span></div>"
        evidence = ""
        qty = snapshot.get("qty") or snapshot.get("shares")
        price = snapshot.get("exit_price") or snapshot.get("price") or snapshot.get("entry_price")
        if qty not in (None, ""):
            evidence += f"<div><strong>Quantity:</strong> {html.escape(str(qty))}</div>"
        if price not in (None, ""):
            evidence += f"<div><strong>Price:</strong> ${float(price):,.2f}</div>"
        if item.get("action") == "ENTRY_EXECUTED":
            evidence = (
                evidence +
                f"<div><strong>Dip observed:</strong> {float(snapshot.get('dip_pct') or 0):.2f}%</div>"
            )
            if snapshot.get("dip_threshold_pct") is not None:
                evidence += (
                    f"<div><strong>Required dip:</strong> "
                    f"{float(snapshot['dip_threshold_pct']):.2f}%</div>"
                )
        rows.append(
            "<div style='border:1px solid #e2e8f0;border-left:4px solid " + color +
            ";padding:12px;margin:10px 0;border-radius:6px'>"
            f"<strong>{html.escape(str(item.get('summary') or 'Hermes update'))}</strong>"
            f"{evidence}{pnl_html}<p>{html.escape(str(item.get('rationale') or ''))}</p></div>"
        )
    subject = f"Hermes Paper Alert — {label} — {status}"
    body = (
        "<div style='font-family:Arial,sans-serif;max-width:680px;margin:auto'>"
        f"<h2>Hermes Paper Alert</h2><div style='color:{color};font-weight:700'>Status: {status}</div>"
        + "".join(rows) +
        f"<p><strong>Job:</strong> {html.escape(str(context.get('job_id') or ''))}<br>"
        f"<strong>Run:</strong> {html.escape(str(context.get('run_id') or ''))}<br>"
        f"<strong>Candidate:</strong> {html.escape(str(context.get('candidate_id') or ''))}</p>"
        "<p style='color:#64748b'>Paper mode only. Hermes reported actions produced by the "
        "approved strategy; the advice layer did not submit an additional order.</p></div>"
    )
    return subject, body


def analyze_owned_paper_job(job_id: str, user_id: str) -> Optional[dict]:
    """Return a deterministic, owner-scoped paper diagnosis for chat/email actions."""
    with _pool().get_session() as session:
        job = session.execute(text("""
            SELECT job_id, run_id, candidate_id, account_id, status, config
            FROM alpatrade.hermes_jobs
            WHERE job_id = CAST(:job_id AS UUID) AND user_id = CAST(:uid AS UUID)
              AND kind = 'paper'
        """), {"job_id": job_id, "uid": user_id}).mappings().first()
        if not job:
            return None
        trades = [dict(row) for row in session.execute(text("""
            SELECT symbol, direction, shares AS qty, entry_time, exit_time,
                   entry_price, exit_price, pnl, pnl_pct, dip_pct, reason, created_at
            FROM alpatrade.trades
            WHERE run_id = :run_id AND user_id = CAST(:uid AS UUID)
              AND trade_type = 'paper'
            ORDER BY created_at
        """), {"run_id": job["run_id"], "uid": user_id}).mappings().all()]
        active_duplicates = session.execute(text("""
            SELECT COUNT(*) FROM alpatrade.hermes_jobs
            WHERE user_id = CAST(:uid AS UUID) AND kind = 'paper'
              AND status IN ('queued', 'running', 'paused')
              AND job_id <> CAST(:job_id AS UUID)
              AND account_id IS NOT DISTINCT FROM CAST(:account_id AS UUID)
              AND candidate_id IS NOT DISTINCT FROM CAST(:candidate_id AS UUID)
        """), {"uid": user_id, "job_id": job_id,
                "account_id": job["account_id"],
                "candidate_id": job["candidate_id"]}).scalar_one()
        other_account_runs = session.execute(text("""
            SELECT COUNT(*) FROM alpatrade.runs
            WHERE user_id = CAST(:uid AS UUID) AND mode = 'paper' AND status = 'running'
              AND run_id <> :run_id
              AND account_id IS NOT DISTINCT FROM CAST(:account_id AS UUID)
        """), {"uid": user_id, "run_id": job["run_id"],
                "account_id": job["account_id"]}).scalar_one()
    advice = list_owned(user_id, job_id=job_id, limit=30)
    report = build_performance_report(
        date=datetime.now(timezone.utc).date().isoformat(), positions=[], trades=trades,
        advice=advice, job_id=str(job["job_id"]), run_id=str(job["run_id"]),
        candidate_id=str(job["candidate_id"] or ""),
    )
    report.update({
        "job_status": str(job["status"]), "config": dict(job["config"] or {}),
        "active_duplicate_jobs": int(active_duplicates or 0),
        "other_active_account_runs": int(other_account_runs or 0),
    })
    if active_duplicates:
        report["status"] = "RED"
        report["status_color"] = LOSS_COLOR
        report["reasons"].append(
            f"{active_duplicates} additional active Hermes paper job(s) use the same candidate and account."
        )
        report["decision"] = "Pause and review duplicate jobs before further entries."
    if other_account_runs:
        report["status"] = "RED"
        report["status_color"] = LOSS_COLOR
        report["reasons"].append(
            f"{other_account_runs} other running paper run(s) share this Alpaca account."
        )
        report["decision"] = (
            "Pause this Hermes job and review overlapping account-level paper runs."
        )
    return report


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
