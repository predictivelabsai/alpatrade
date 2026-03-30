"""Shared equity curve chart generator — used by agui_app, web_app, and core.py."""

import json
from typing import Optional


def show_equity_curve(run_id: str = "", trade_type: str = "",
                      strategy: str = "", user_id: Optional[str] = None) -> str:
    """Generate equity curve chart data as markdown with __CHART_DATA__ marker.

    Args:
        run_id: Full or prefix run UUID.
        trade_type: Filter by 'paper' or 'backtest'.
        strategy: Filter by strategy slug prefix.
        user_id: Optional user filter.

    Returns:
        Markdown string with chart data marker, or error message.
    """
    try:
        from utils.db.db_pool import DatabasePool
        from sqlalchemy import text

        pool = DatabasePool()
        with pool.get_session() as session:
            rid = run_id.strip() if run_id else ""

            if not rid:
                where = ["1=1"]
                bind = {}
                if trade_type:
                    where.append("mode = :mode")
                    bind["mode"] = trade_type
                if strategy:
                    where.append("strategy_slug LIKE :slug")
                    bind["slug"] = strategy + "%"
                if user_id:
                    where.append("user_id = :user_id")
                    bind["user_id"] = user_id
                row = session.execute(
                    text(f"SELECT run_id FROM alpatrade.runs WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT 1"),
                    bind,
                ).fetchone()
                if not row:
                    return "No run found matching filters."
                rid = str(row[0])
            elif len(rid) < 36:
                row = session.execute(
                    text("SELECT run_id FROM alpatrade.runs WHERE CAST(run_id AS TEXT) LIKE :prefix ORDER BY created_at DESC LIMIT 1"),
                    {"prefix": f"{rid}%"},
                ).fetchone()
                if not row:
                    return f"No run found matching prefix `{rid}`"
                rid = str(row[0])

            run_row = session.execute(
                text("SELECT config FROM alpatrade.runs WHERE run_id = :rid"),
                {"rid": rid},
            ).fetchone()
            initial_capital = 10000.0
            if run_row and run_row[0]:
                cfg = run_row[0] if isinstance(run_row[0], dict) else json.loads(run_row[0])
                initial_capital = float(cfg.get("initial_capital", 10000))

            trades = session.execute(
                text("""
                    SELECT exit_time, capital_after
                    FROM alpatrade.trades
                    WHERE run_id = :rid AND exit_time IS NOT NULL AND capital_after IS NOT NULL
                    ORDER BY exit_time ASC
                """),
                {"rid": rid},
            ).fetchall()

        if not trades:
            return f"No trade data with equity info for run `{rid[:8]}`"

        dates = [t[0].isoformat() if hasattr(t[0], 'isoformat') else str(t[0]) for t in trades]
        equity = [round(float(t[1]), 2) for t in trades]

        chart_data = json.dumps({
            "type": "equity_curve",
            "run_id": rid,
            "dates": dates,
            "equity": equity,
            "initial_capital": initial_capital,
        })
        short = rid[:8]
        final_eq = equity[-1] if equity else initial_capital
        pnl = final_eq - initial_capital
        pct = (pnl / initial_capital * 100) if initial_capital else 0
        sign = "+" if pnl >= 0 else ""
        label = f"**Equity Curve** — `{short}` ({sign}${pnl:.0f} / {sign}{pct:.1f}%)"
        return f"{label}\n\n__CHART_DATA__{chart_data}__END_CHART__"
    except Exception as e:
        return f"Error generating equity curve: {e}"
