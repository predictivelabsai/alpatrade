#!/usr/bin/env python3
"""Daily paper-trading PnL + trade report — emailed after market close.

Pulls the live Alpaca **paper** account (equity, day change, open positions with
unrealised P&L) and the day's paper trades from the `alpatrade.trades` table, renders an
HTML digest, and emails it via Postmark. Designed to be fired nightly by
engine.autonomy.schedule.

The digest reports the strategy that is actually running (name, status, universe and
every tuned parameter from `alpatrade.runs.config`) and, for each trade, explains what
triggered it by reading the trade against those parameters — e.g. a buy is shown as the
observed dip against the configured dip threshold, an exit as the realised move against
the configured take-profit/stop-loss.

Usage:
  python scripts/daily_pnl_report.py                        # print HTML, no send (env account, lite)
  python scripts/daily_pnl_report.py --date 2026-08-03      # re-render a past day
  python scripts/daily_pnl_report.py --send                 # email to PNL_REPORT_TO / TO_EMAIL
  python scripts/daily_pnl_report.py --send --to kaljuvee@gmail.com
  # Full per-account report (MTD/YTD, agent benchmark, live runs) for one tenant:
  python scripts/daily_pnl_report.py --user <uuid> --account <uuid> --send --to owner@example.com
"""
from __future__ import annotations

import argparse
import html as _html
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # noqa: BLE001
    pass


# Pretty labels + units for the strategy parameters surfaced in the digest.
_PARAM_LABELS = {
    "dip_threshold": ("Dip threshold", "pct"),
    "take_profit_threshold": ("Take profit", "pct"),
    "stop_loss_threshold": ("Stop loss", "pct"),
    "hold_days": ("Max hold", "days"),
    "min_hold_days": ("Min hold", "days"),
    "capital_per_trade": ("Capital per trade", "usd"),
    "lookback_days": ("Lookback", "days"),
    "momentum_threshold": ("Momentum threshold", "pct"),
    "vix_threshold": ("VIX threshold", "num"),
}

_STRATEGY_LABELS = {
    "buy_the_dip": "Buy the Dip",
    "momentum": "Momentum",
    "vix": "VIX Fear Index",
    "box_wedge": "Box-Wedge",
}


def recipients(override: str | None = None) -> list[str]:
    """Explicit operator recipients only; never use a hard-coded distribution list."""
    raw = override or os.getenv("PNL_REPORT_TO") or os.getenv("TO_EMAIL") or ""
    return [e.strip() for e in raw.split(",") if e.strip()]


def report_targets() -> list[dict]:
    """Active user/account/email targets; decrypted keys stay in process memory only."""
    try:
        from sqlalchemy import text
        from engine.auth import get_alpaca_keys
        from engine.db.pool import DatabasePool
        with DatabasePool().get_session() as session:
            rows = session.execute(text("""
                SELECT u.user_id, u.email, ua.account_id, ua.account_name
                FROM alpatrade.users u
                JOIN alpatrade.user_accounts ua ON ua.user_id = u.user_id
                WHERE ua.is_active = TRUE AND u.email IS NOT NULL
                  AND ua.alpaca_api_key_enc IS NOT NULL
                  AND ua.alpaca_secret_key_enc IS NOT NULL
                ORDER BY u.user_id, ua.created_at
            """)).fetchall()
        targets = []
        for user_id, email, account_id, account_name in rows:
            keys = get_alpaca_keys(str(user_id), str(account_id))
            if keys:
                targets.append({"user_id": str(user_id), "account_id": str(account_id),
                                "email": email, "account_name": account_name, "keys": keys})
        return targets
    except Exception:  # noqa: BLE001
        return []


def claim_report_delivery(user_id: str, account_id: str, day: str) -> bool:
    """Atomically reserve one daily delivery across all Coolify processes."""
    try:
        from sqlalchemy import text
        from engine.db.pool import DatabasePool
        with DatabasePool().get_session() as session:
            row = session.execute(text("""
                INSERT INTO alpatrade.report_deliveries
                    (user_id, account_id, report_date, report_kind)
                VALUES (:uid, :aid, CAST(:day AS DATE), 'daily_paper')
                ON CONFLICT (user_id, account_id, report_date, report_kind) DO UPDATE
                    SET status = 'sending', created_at = NOW()
                    WHERE alpatrade.report_deliveries.status = 'failed'
                       OR (alpatrade.report_deliveries.status = 'sending'
                           AND alpatrade.report_deliveries.created_at < NOW() - INTERVAL '2 hours')
                RETURNING delivery_id
            """), {"uid": user_id, "aid": account_id, "day": day}).fetchone()
            return bool(row)
    except Exception:  # noqa: BLE001
        return False


def finish_report_delivery(user_id: str, account_id: str, day: str,
                           sent: bool) -> None:
    try:
        from sqlalchemy import text
        from engine.db.pool import DatabasePool
        with DatabasePool().get_session() as session:
            session.execute(text("""
                UPDATE alpatrade.report_deliveries
                SET status = :status, sent_at = CASE WHEN :sent THEN NOW() ELSE NULL END
                WHERE user_id = :uid AND account_id = :aid
                  AND report_date = CAST(:day AS DATE) AND report_kind = 'daily_paper'
            """), {"uid": user_id, "aid": account_id, "day": day,
                    "status": "sent" if sent else "failed", "sent": sent})
    except Exception:  # noqa: BLE001
        pass


def _f(v, d=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _e(v) -> str:
    """HTML-escape a value for interpolation into the digest."""
    return _html.escape(str(v if v is not None else ""))


def gather(day: str | None = None, keys: tuple[str, str] | None = None,
           user_id: str | None = None, account_id: str | None = None,
           framework: str | None = None) -> dict:
    if (user_id is None) != (account_id is None):
        raise ValueError("user_id and account_id must be supplied together")
    from engine.brokers.alpaca import AlpacaAPI
    api = AlpacaAPI(*keys, paper=True) if keys else AlpacaAPI(paper=True)
    acct = api.get_account() or {}
    positions = api.get_positions() or []
    equity = _f(acct.get("equity"))
    last_equity = _f(acct.get("last_equity")) or equity
    day_pnl = equity - last_equity
    day_pct = (equity / last_equity - 1) * 100 if last_equity else 0.0
    unreal = sum(_f(p.get("unrealized_pl")) for p in positions)
    # Backdated (--date in the past): the live account can't describe a past day, so
    # take that day's equity + its day-over-day change from Alpaca portfolio history.
    # (Positions still can't be reconstructed — the stale notice flags that.)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    backdated_equity = None
    if day and day != today:
        hist_pair = _historical_equity(api, day)
        if hist_pair:
            hist_equity, hist_prev = hist_pair
            backdated_equity, equity, last_equity = hist_equity, hist_equity, hist_prev
            day_pnl = equity - last_equity
            day_pct = (equity / last_equity - 1) * 100 if last_equity else 0.0
    trades = gather_trades(day, user_id=user_id, account_id=account_id,
                           framework=framework)
    runs = gather_runs([t.get("run_id") for t in trades], user_id=user_id,
                       account_id=account_id)
    data = {
        "equity": equity, "last_equity": last_equity, "day_pnl": day_pnl, "day_pct": day_pct,
        "cash": _f(acct.get("cash")), "buying_power": _f(acct.get("buying_power")),
        "unrealized_pl": unreal, "daytrade_count": acct.get("daytrade_count"),
        "positions": positions,
        "trades": trades,
        "runs": runs,
        "active_runs": active_runs(user_id=user_id, account_id=account_id,
                                   framework=framework),
        "agent_performance": agent_performance(user_id, account_id, framework),
        "framework_filter": framework,
        "day": day or today,
        "backdated": bool(day and day != today),
        "backdated_equity_ok": backdated_equity is not None,
    }
    data["periods"] = (save_equity_snapshot(user_id, account_id, data["day"], data, api)
                       if user_id and account_id and data["day"] == today else {})
    data["benchmark"] = _benchmark_returns(data["day"], data["periods"])
    data["account_stats"] = (account_stats(user_id, account_id, data["day"])
                             if user_id and account_id else {})
    return data


def account_stats(user_id: str, account_id: str, day: str) -> dict:
    """Cumulative realized P&L (from paper trades) plus annualized Sharpe and max
    drawdown derived from the persisted daily equity-snapshot curve.

    Sharpe/drawdown need a few days of history; they are omitted below 5 snapshot
    days. Best-effort ({} on any failure)."""
    try:
        import statistics
        from sqlalchemy import text
        from engine.db.pool import DatabasePool
        with DatabasePool().get_session() as session:
            eq = session.execute(text("""
                SELECT equity, net_cash_flow
                FROM alpatrade.account_equity_snapshots
                WHERE user_id = :uid AND account_id = :aid
                  AND trading_date <= CAST(:day AS DATE)
                ORDER BY trading_date
            """), {"uid": user_id, "aid": account_id, "day": day}).fetchall()
            realized = session.execute(text("""
                SELECT COALESCE(SUM(pnl), 0)
                FROM alpatrade.trades
                WHERE user_id = :uid AND account_id = :aid
                  AND trade_type = 'paper' AND pnl IS NOT NULL
            """), {"uid": user_id, "aid": account_id}).scalar()
        stats: dict = {"realized_pnl": float(realized or 0)}
        equities = [float(r[0]) for r in eq]
        flows = [float(r[1] or 0) for r in eq]
        if len(equities) >= 5:
            rets = [(equities[i] - flows[i] - equities[i - 1]) / equities[i - 1]
                    for i in range(1, len(equities)) if equities[i - 1] > 0]
            if len(rets) >= 2:
                sd = statistics.stdev(rets)
                stats["sharpe"] = (statistics.fmean(rets) / sd * (252 ** 0.5)) if sd > 0 else None
            peak, mdd = equities[0], 0.0
            for e in equities:
                peak = max(peak, e)
                if peak > 0:
                    mdd = min(mdd, e / peak - 1)
            stats["max_drawdown"] = mdd * 100
            stats["snapshot_days"] = len(equities)
        return stats
    except Exception:  # noqa: BLE001
        return {}


def _historical_equity(api, day: str):
    """(equity at end of `day`, prior trading day's equity) from Alpaca history.

    Lets a back-dated report show that day's real equity/day-change instead of the
    live account. Returns None on any failure."""
    try:
        import pandas as pd
        from datetime import datetime as _dt, timedelta
        target = _dt.strptime(day, "%Y-%m-%d")
        hist = api.get_portfolio_history(start=target - timedelta(days=10),
                                         end=target + timedelta(days=1), timeframe="1D")
        eq = hist.get("equity") if isinstance(hist, dict) else None
        ts = hist.get("timestamps") if isinstance(hist, dict) else None
        if not eq or not ts:
            return None
        upto = [float(e) for t, e in zip(ts, eq)
                if pd.Timestamp(t).date() <= target.date()]
        if not upto:
            return None
        return (upto[-1], upto[-2] if len(upto) >= 2 else upto[-1])
    except Exception:  # noqa: BLE001
        return None


def _benchmark_returns(day: str, periods: dict, symbol: str = "SPY") -> dict:
    """SPY buy-and-hold % over the same MTD/YTD windows, for a market comparison.

    Uses daily closes from the configured market-data feed; best-effort ({} on any
    failure) so the benchmark can never fail the report.
    """
    if not periods:
        return {}
    try:
        import pandas as pd
        from datetime import datetime as _dt, timedelta
        from engine.feeds.market_data import get_historical_data
        end = _dt.strptime(day, "%Y-%m-%d")
        df = get_historical_data(symbol, end.replace(month=1, day=1) - timedelta(days=7),
                                 end + timedelta(days=1), timeframe="day")
        if df is None or df.empty or "Close" not in df:
            return {}
        closes = df["Close"].dropna()
        if closes.empty:
            return {}
        current = float(closes.iloc[-1])
        idx = pd.to_datetime(closes.index)

        def _ret(start) -> float | None:
            sub = closes[idx >= pd.Timestamp(start)]
            base = float(sub.iloc[0]) if len(sub) else 0.0
            return (current / base - 1) * 100 if base else None

        out = {}
        if periods.get("mtd"):
            out["mtd"] = _ret(end.replace(day=1))
        if periods.get("ytd"):
            out["ytd"] = _ret(end.replace(month=1, day=1))
        return out
    except Exception:  # noqa: BLE001
        return {}


def gather_trades(day: str | None = None, limit: int = 100,
                  user_id: str | None = None,
                  account_id: str | None = None,
                  framework: str | None = None) -> list[dict]:
    """Paper trades booked on `day` (default: today UTC) — [] on any failure.

    Trades are matched by `created_at` falling on that UTC date, so the report reflects
    what was actually booked during the trading day regardless of entry/exit fill times.
    """
    try:
        from sqlalchemy import text
        from engine.db.pool import DatabasePool
        pool = DatabasePool()
        target = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with pool.get_session() as session:
            where = [
                "t.trade_type = 'paper'",
                "t.created_at >= CAST(:day AS DATE)",
                "t.created_at < CAST(:day AS DATE) + INTERVAL '1 day'",
            ]
            params = {"day": target, "lim": limit}
            if user_id:
                where.append("t.user_id = :user_id")
                params["user_id"] = user_id
            if account_id:
                where.append("t.account_id = :account_id")
                params["account_id"] = account_id
            if framework:
                where.append("COALESCE(r.agent_framework, r.config->>'agent_framework', 'legacy') = :framework")
                params["framework"] = framework
            result = session.execute(
                text(
                    "SELECT t.symbol, t.direction, t.shares, t.entry_price, t.exit_price, "
                    "       t.pnl, t.pnl_pct, t.reason, t.created_at, t.entry_time, t.exit_time, "
                    "       t.run_id, t.dip_pct, t.target_price, t.stop_price, t.hit_target, t.hit_stop "
                    "FROM alpatrade.trades t JOIN alpatrade.runs r ON r.run_id = t.run_id "
                    f"WHERE {' AND '.join(where)} "
                    "ORDER BY t.created_at DESC LIMIT :lim"
                ),
                params,
            )
            cols = result.keys()
            return [dict(zip(cols, row)) for row in result.fetchall()]
    except Exception:  # noqa: BLE001 — report must never fail the email send
        return []


def gather_runs(run_ids, user_id: str | None = None,
                account_id: str | None = None) -> dict[str, dict]:
    """Strategy metadata (name, status, config/params) keyed by run_id."""
    ids = sorted({r for r in (run_ids or []) if r})
    if not ids:
        return {}
    try:
        from sqlalchemy import text
        from engine.db.pool import DatabasePool
        pool = DatabasePool()
        with pool.get_session() as session:
            where = ["run_id = ANY(:ids)"]
            params = {"ids": ids}
            if user_id:
                where.append("user_id = :user_id")
                params["user_id"] = user_id
            if account_id:
                where.append("account_id = :account_id")
                params["account_id"] = account_id
            result = session.execute(text(
                "SELECT run_id, mode, strategy, strategy_slug, status, config, "
                "started_at, completed_at, agent_name, agent_framework, heartbeat_at "
                f"FROM alpatrade.runs WHERE {' AND '.join(where)}"
            ), params)
            cols = result.keys()
            return {row[0]: dict(zip(cols, row)) for row in result.fetchall()}
    except Exception:  # noqa: BLE001
        return {}


def active_runs(limit: int = 25, user_id: str | None = None,
                account_id: str | None = None,
                framework: str | None = None) -> list[dict]:
    """Heartbeat-verified paper runs for exactly one tenant/account."""
    if not user_id or not account_id:
        return []
    try:
        from sqlalchemy import text
        from engine.db.pool import DatabasePool
        pool = DatabasePool()
        with pool.get_session() as session:
            where = ["r.mode IN ('paper', 'full')", "r.status = 'running'",
                     "r.user_id = :user_id", "r.account_id = :account_id",
                     "(r.heartbeat_at >= NOW() - INTERVAL '10 minutes' OR EXISTS ("
                     "SELECT 1 FROM alpatrade.hermes_jobs h WHERE h.run_id = r.run_id "
                     "AND h.status IN ('running', 'paused') "
                     "AND h.heartbeat_at >= NOW() - INTERVAL '10 minutes'))"]
            params = {"lim": limit, "user_id": user_id, "account_id": account_id}
            if framework:
                where.append("COALESCE(r.agent_framework, r.config->>'agent_framework', 'legacy') = :framework")
                params["framework"] = framework
            result = session.execute(text(
                "SELECT r.run_id, r.mode, r.strategy, r.strategy_slug, r.status, r.config, "
                "r.started_at, r.completed_at, r.agent_name, r.agent_framework, r.heartbeat_at "
                f"FROM alpatrade.runs r WHERE {' AND '.join(where)} "
                "ORDER BY r.started_at DESC LIMIT :lim"
            ), params)
            cols = result.keys()
            return [dict(zip(cols, row)) for row in result.fetchall()]
    except Exception:  # noqa: BLE001
        return []


def reconcile_stale_runs(user_id: str, account_id: str) -> int:
    """Close paper/full rows whose worker has not heartbeated within the grace period."""
    try:
        from sqlalchemy import text
        from engine.db.pool import DatabasePool
        with DatabasePool().get_session() as session:
            result = session.execute(text("""
                UPDATE alpatrade.runs
                SET status = 'stale', completed_at = COALESCE(completed_at, NOW())
                WHERE user_id = :uid AND account_id = :aid
                  AND mode IN ('paper', 'full') AND status = 'running'
                  AND started_at < NOW() - INTERVAL '15 minutes'
                  AND (heartbeat_at IS NULL OR heartbeat_at < NOW() - INTERVAL '10 minutes')
                  AND NOT EXISTS (
                      SELECT 1 FROM alpatrade.hermes_jobs h
                      WHERE h.run_id = alpatrade.runs.run_id
                        AND h.status IN ('running', 'paused')
                        AND h.heartbeat_at >= NOW() - INTERVAL '10 minutes'
                  )
            """), {"uid": user_id, "aid": account_id})
            return int(result.rowcount or 0)
    except Exception:  # noqa: BLE001
        return 0


def agent_performance(user_id: str | None, account_id: str | None,
                      framework: str | None = None) -> list[dict]:
    """Realized paper results grouped by attributed agent for comparison."""
    if not user_id or not account_id:
        return []
    try:
        from sqlalchemy import text
        from engine.db.pool import DatabasePool
        where = ["t.trade_type = 'paper'", "t.user_id = :user_id",
                 "t.account_id = :account_id", "t.pnl IS NOT NULL",
                 "t.created_at >= DATE_TRUNC('year', NOW())"]
        params = {"user_id": user_id, "account_id": account_id}
        if framework:
            where.append("COALESCE(r.agent_framework, r.config->>'agent_framework', 'legacy') = :framework")
            params["framework"] = framework
        with DatabasePool().get_session() as session:
            result = session.execute(text(f"""
                SELECT COALESCE(r.agent_framework, r.config->>'agent_framework', 'legacy') framework,
                       COALESCE(r.agent_name, r.config->>'agent_name', 'Legacy / unattributed') agent_name,
                       COUNT(*) FILTER (WHERE t.created_at >= DATE_TRUNC('month', NOW())) mtd_exits,
                       COALESCE(SUM(t.pnl) FILTER (WHERE t.created_at >= DATE_TRUNC('month', NOW())), 0) mtd_pnl,
                       COUNT(*) ytd_exits, COALESCE(SUM(t.pnl), 0) ytd_pnl,
                       COALESCE(100.0 * COUNT(*) FILTER (WHERE t.pnl > 0) / NULLIF(COUNT(*), 0), 0) win_rate,
                       COUNT(DISTINCT t.run_id) run_count
                FROM alpatrade.trades t JOIN alpatrade.runs r ON r.run_id = t.run_id
                WHERE {' AND '.join(where)}
                GROUP BY 1, 2 ORDER BY ytd_pnl DESC
            """), params)
            cols = result.keys()
            return [dict(zip(cols, row)) for row in result.fetchall()]
    except Exception:  # noqa: BLE001
        return []


def save_equity_snapshot(user_id: str, account_id: str, day: str,
                         data: dict, api=None) -> dict:
    """Upsert today's account snapshot and derive account-level MTD/YTD returns.

    Hybrid baseline: persisted snapshots are preferred (cash-flow aware via
    net_cash_flow), but when snapshots don't yet reach a window's start the
    baseline is seeded from Alpaca's portfolio history so MTD/YTD are correct
    *retroactively* rather than blank until snapshots accumulate. Each window
    carries a ``source`` of ``'snapshot'`` or ``'alpaca'``.
    """
    try:
        from datetime import timedelta, datetime as _dt, time as _time
        from sqlalchemy import text
        from engine.db.pool import DatabasePool
        # External cash flow (deposits/withdrawals/resets) for the day, so the
        # MTD/YTD math can subtract it out. Best-effort — 0.0 when unavailable.
        net_flow = api.get_cash_flows(day) if api is not None else 0.0
        with DatabasePool().get_session() as session:
            session.execute(text("""
                INSERT INTO alpatrade.account_equity_snapshots
                    (user_id, account_id, trading_date, equity, cash, buying_power,
                     unrealized_pnl, net_cash_flow)
                VALUES (:uid, :aid, CAST(:day AS DATE), :equity, :cash, :buying_power,
                        :unrealized, :net_flow)
                ON CONFLICT (user_id, account_id, trading_date) DO UPDATE SET
                    equity = EXCLUDED.equity, cash = EXCLUDED.cash,
                    buying_power = EXCLUDED.buying_power,
                    unrealized_pnl = EXCLUDED.unrealized_pnl,
                    net_cash_flow = EXCLUDED.net_cash_flow, captured_at = NOW()
            """), {"uid": user_id, "aid": account_id, "day": day,
                    "equity": data["equity"], "cash": data["cash"],
                    "buying_power": data["buying_power"],
                    "unrealized": data["unrealized_pl"], "net_flow": net_flow})
            rows = session.execute(text("""
                SELECT trading_date, equity, net_cash_flow
                FROM alpatrade.account_equity_snapshots
                WHERE user_id = :uid AND account_id = :aid
                  AND trading_date >= DATE_TRUNC('year', CAST(:day AS DATE))
                  AND trading_date <= CAST(:day AS DATE)
                ORDER BY trading_date
            """), {"uid": user_id, "aid": account_id, "day": day}).fetchall()
        if not rows:
            return {}
        current = float(data.get("equity") or rows[-1][1])
        day_date = rows[-1][0]
        month_start = day_date.replace(day=1)
        year_start = day_date.replace(month=1, day=1)
        month_rows = [r for r in rows
                      if r[0].year == day_date.year and r[0].month == day_date.month]

        def _alpaca_baseline(start_date):
            if api is None:
                return None
            try:
                s = _dt.combine(start_date, _time.min, tzinfo=timezone.utc)
                e = _dt.combine(day_date, _time.max, tzinfo=timezone.utc)
                hist = api.get_portfolio_history(start=s, end=e, timeframe="1D")
                eq = hist.get("equity") if isinstance(hist, dict) else None
                return float(eq[0]) if eq else None
            except Exception:  # noqa: BLE001
                return None

        def window(subset, start_date) -> dict | None:
            flows = sum(float(r[2] or 0) for r in subset)
            # Snapshots "cover" the window only if the earliest one lands on/near
            # the window start (allow a weekend/holiday gap).
            snap_covers = bool(subset) and subset[0][0] <= start_date + timedelta(days=4)
            if snap_covers:
                baseline, source = float(subset[0][1]) - float(subset[0][2] or 0), "snapshot"
            else:
                baseline, source = _alpaca_baseline(start_date), "alpaca"
                if baseline is None and subset:  # last resort: earliest snapshot
                    baseline, source = float(subset[0][1]) - float(subset[0][2] or 0), "snapshot"
            if not baseline:
                return None
            pnl = current - baseline - flows
            return {"pnl": pnl, "pct": (pnl / baseline * 100) if baseline else 0.0,
                    "days": len(subset), "source": source}
        return {"mtd": window(month_rows, month_start), "ytd": window(rows, year_start)}
    except Exception:  # noqa: BLE001
        return {}


def _params_of(run: dict | None) -> dict:
    cfg = (run or {}).get("config") or {}
    if not isinstance(cfg, dict):
        return {}
    params = cfg.get("params")
    return params if isinstance(params, dict) else {}


def _fmt_param(key: str, value) -> tuple[str, str]:
    label, unit = _PARAM_LABELS.get(key, (key.replace("_", " ").capitalize(), "num"))
    if unit == "pct":
        return label, f"{_f(value):.2f}%"
    if unit == "usd":
        return label, f"${_f(value):,.0f}"
    if unit == "days":
        n = _f(value)
        return label, f"{n:.0f} day{'' if n == 1 else 's'}"
    return label, str(value)


def _held_days(t: dict) -> int | None:
    entry, exit_t = t.get("entry_time"), t.get("exit_time")
    if not entry:
        return None
    end = exit_t or datetime.now(timezone.utc)
    try:
        return max((end - entry).days, 0)
    except Exception:  # noqa: BLE001 — mixed tz-awareness shouldn't break the email
        return None


def _explain(t: dict, run: dict | None) -> str:
    """Explain *why* a trade happened, reading it against the strategy's parameters.

    Falls back to the raw `reason` string when there's nothing richer to say, so a
    strategy that stores its own reason text still renders sensibly.
    """
    params = _params_of(run)
    raw = (t.get("reason") or "").strip()
    code = raw.split("(")[0].strip().upper()
    pnl_pct = t.get("pnl_pct")
    dip = t.get("dip_pct")
    exit_p = _f(t.get("exit_price"))
    held = _held_days(t)
    bits: list[str] = []

    is_entry = not exit_p and t.get("pnl") is None
    if is_entry:
        if dip is not None:
            trigger = params.get("dip_threshold")
            bits.append(f"Dip -{_f(dip):.2f}%" +
                        (f" past -{_f(trigger):.2f}% trigger" if trigger is not None else ""))
        elif raw:
            bits.append(raw)
        else:
            bits.append("Entry signal")
        cap = params.get("capital_per_trade")
        if cap:
            bits.append(f"sized ${_f(cap):,.0f}/trade")
    elif code == "TAKE_PROFIT":
        tp = params.get("take_profit_threshold")
        bits.append(f"Take-profit {_f(pnl_pct):+.2f}%" +
                    (f" reached {_f(tp):.2f}% target" if tp is not None else ""))
    elif code in ("STOP_LOSS", "STOPLOSS"):
        sl = params.get("stop_loss_threshold")
        bits.append(f"Stop-loss {_f(pnl_pct):+.2f}%" +
                    (f" breached -{_f(sl):.2f}% limit" if sl is not None else ""))
    elif code in ("HOLD_DAYS", "MAX_HOLD", "TIME_EXIT", "TIMEOUT"):
        hd = params.get("hold_days")
        bits.append("Max hold reached" + (f" ({_f(hd):.0f}d)" if hd is not None else "") +
                    (f", exited {_f(pnl_pct):+.2f}%" if pnl_pct is not None else ""))
    elif raw:
        bits.append(raw)
    else:
        bits.append("—")

    if held is not None and not is_entry:
        mh = params.get("min_hold_days")
        bits.append(f"held {held}d" + (f" (min {_f(mh):.0f}d)" if mh is not None else ""))

    strategy = (run or {}).get("strategy")
    if strategy:
        bits.append(_STRATEGY_LABELS.get(strategy, strategy))
    return " · ".join(b for b in bits if b)


def _render_strategy(d: dict) -> str:
    """The 'what is running, and how is it tuned' block."""
    runs = list(d.get("active_runs") or [])
    seen = {r.get("run_id") for r in runs}
    # Include any run that produced today's trades but is no longer marked running.
    for rid, run in (d.get("runs") or {}).items():
        if rid not in seen:
            runs.append(run)
            seen.add(rid)
    if not runs:
        return ("<h3>Strategy &amp; agent</h3>"
                "<p style='color:#7A867E;font-size:13px'>No running paper strategy found.</p>")

    traded = {t.get("run_id") for t in d.get("trades", [])}

    # Stale paper runs are never marked completed, so several identical `running` rows
    # pile up. Collapse them by configuration and keep the one that actually traded
    # (else the newest), noting how many duplicates it stands for.
    groups: dict[tuple, list[dict]] = {}
    for run in runs:
        cfg = run.get("config") if isinstance(run.get("config"), dict) else {}
        key = (run.get("strategy"), repr(sorted(_params_of(run).items())),
               repr(cfg.get("symbols")))
        groups.setdefault(key, []).append(run)
    deduped: list[tuple[dict, int]] = []
    for members in groups.values():
        pick = next((m for m in members if m.get("run_id") in traded), members[0])
        deduped.append((pick, len(members) - 1))

    blocks = ""
    for run, dupes in deduped:
        rid = run.get("run_id") or ""
        strategy = run.get("strategy") or "unknown"
        name = _STRATEGY_LABELS.get(strategy, strategy)
        status = (run.get("status") or "").lower()
        badge_bg = "#E4EFE7" if status == "running" else "#EFEDE4"
        badge_fg = "#1F5D43" if status == "running" else "#415046"
        started = run.get("started_at")
        started_s = started.strftime("%b %d, %Y %H:%M UTC") if hasattr(started, "strftime") else "—"
        cfg = run.get("config") if isinstance(run.get("config"), dict) else {}
        symbols = cfg.get("symbols") or []
        params = _params_of(run)
        slug = run.get("strategy_slug")
        framework = (run.get("agent_framework") or cfg.get("agent_framework") or "legacy")
        agent_name = (run.get("agent_name") or cfg.get("agent_name") or
                      ("AlpaTrade AI" if framework in ("deepagents", "langgraph") else "Legacy"))

        param_cells = "".join(
            f"<tr><td style='padding:2px 14px 2px 0;color:#415046'>{_e(lbl)}</td>"
            f"<td><b>{_e(val)}</b></td></tr>"
            for lbl, val in (_fmt_param(k, v) for k, v in sorted(params.items()))
        ) or "<tr><td style='color:#7A867E'>No parameters recorded for this run.</td></tr>"

        note = ("<span style='color:#1F5D43;font-size:12px'>&nbsp;· traded today</span>"
                if rid in traded else "")
        dupe_note = (f"<div style='color:#7A867E;font-size:11px;margin-bottom:.35rem'>"
                     f"+{dupes} older run{'' if dupes == 1 else 's'} with identical configuration "
                     f"still marked running</div>" if dupes else "")
        blocks += f"""
  <div style="border:1px solid #DDD9CB;border-radius:6px;padding:10px 12px;margin:.4rem 0">
    <div style="font-size:15px"><b>{_e(name)}</b>
      <span style="background:{badge_bg};color:{badge_fg};font-size:11px;padding:2px 7px;
        border-radius:10px;margin-left:6px">{_e(status or 'unknown')}</span>{note}</div>
    <div style="color:#7A867E;font-size:12px;margin:.25rem 0">
      {_e(agent_name)} / {_e(framework)} · run <code>{_e(rid[:8])}</code> · {_e(run.get('mode') or 'paper')} · started {_e(started_s)}
      {('· slug <code>' + _e(slug) + '</code>') if slug else ''}</div>
    {dupe_note}
    <div style="font-size:12px;color:#415046;margin-bottom:.35rem">
      Universe: {_e(', '.join(symbols)) if symbols else '—'}</div>
    <table style="border-collapse:collapse;font-size:13px">{param_cells}</table>
  </div>"""
    return f"<h3>Strategy &amp; agent ({len(deduped)})</h3>{blocks}"


def _stale_notice(d: dict) -> str:
    """Clarify which figures are historical vs live for a back-dated report.

    Equity and the day-over-day change now come from Alpaca portfolio history for
    the requested date, but Alpaca only exposes *current* positions, so those (and
    cash/buying power) remain live. Say exactly which is which.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not d.get("day") or d["day"] == today:
        return ""
    equity_src = ("equity and the day change are Alpaca history for that date"
                  if d.get("backdated_equity_ok")
                  else "equity/day change could not be pulled for that date and show the "
                       "<b>live</b> account")
    return ("<p style='background:#FBF3E2;border-left:3px solid #C79A3B;padding:8px 10px;"
            "font-size:12px;color:#5B4A22;margin:.4rem 0'>Back-dated report for "
            f"{_e(d['day'])}: trades and realised P&amp;L are for that date; {equity_src}; "
            "open positions, cash and buying power are the <b>live</b> account as of now.</p>")


def _render_periods(d: dict) -> str:
    periods = d.get("periods") or {}
    if not periods:
        return ("<p style='color:#7A867E;font-size:12px'>MTD/YTD are unavailable for this "
                "account yet (no equity history).</p>")
    bench = d.get("benchmark") or {}
    cells = []
    for key, label in (("mtd", "Month to date"), ("ytd", "Year to date")):
        value = periods.get(key) or {}
        if not value:
            cells.append(f"<td style='padding:8px 20px 8px 0'><b>{label}</b><br>"
                         "<span style='color:#7A867E'>n/a</span></td>")
            continue
        pnl, pct = _f(value.get("pnl")), _f(value.get("pct"))
        color = "#1F5D43" if pnl >= 0 else "#b0653f"
        # Baseline provenance: persisted snapshots (cash-flow aware) vs a retroactive
        # Alpaca portfolio-history estimate until snapshots reach the window start.
        if value.get("source") == "alpaca":
            note = "est. from Alpaca history"
        else:
            note = f"{int(value.get('days') or 0)} snapshot day(s)"
        # SPY buy-and-hold over the same window, plus excess return vs it.
        spy = bench.get(key)
        spy_line = ""
        if spy is not None:
            excess = pct - spy
            ec = "#1F5D43" if excess >= 0 else "#b0653f"
            spy_line = (f"<br><small style='color:#7A867E'>vs SPY {spy:+.2f}% · "
                        f"<span style='color:{ec}'>{excess:+.2f}% excess</span></small>")
        cells.append(f"<td style='padding:8px 20px 8px 0'><b>{label}</b> "
                     "<span style='font-size:11px;color:#9AA39C'>(arithmetic)</span><br>"
                     f"<span style='color:{color}'>${pnl:+,.2f} ({pct:+.2f}%)</span>"
                     f"{spy_line}<br>"
                     f"<small style='color:#9AA39C'>{note}</small></td>")
    return f"<h3 style='margin:.9rem 0 .2rem'>Performance</h3><table><tr>{''.join(cells)}</tr></table>"


def _render_risk(d: dict) -> str:
    """Cumulative realized P&L + annualized Sharpe / max drawdown from the curve."""
    stats = d.get("account_stats") or {}
    if not stats:
        return ""
    parts = []
    rp = _f(stats.get("realized_pnl"))
    rc = "#1F5D43" if rp >= 0 else "#b0653f"
    parts.append(f"Realized P&amp;L to date <b style='color:{rc}'>${rp:+,.2f}</b>")
    if stats.get("sharpe") is not None:
        parts.append(f"Sharpe (annualized) <b>{_f(stats.get('sharpe')):.2f}</b>")
    if stats.get("max_drawdown") is not None:
        parts.append(f"Max drawdown <b style='color:#b0653f'>{_f(stats.get('max_drawdown')):.2f}%</b>")
    note = (f" · from {int(stats.get('snapshot_days') or 0)} snapshot day(s)"
            if stats.get("snapshot_days") else "")
    return ("<p style='font-size:13px;color:#415046;margin:.3rem 0'>"
            + " &nbsp;·&nbsp; ".join(parts)
            + f"<span style='color:#9AA39C;font-size:11px'>{note}</span></p>")


def _render_agent_benchmark(d: dict) -> str:
    rows = d.get("agent_performance") or []
    if not rows:
        return ("<h3>Agent benchmark</h3><p style='color:#7A867E;font-size:12px'>"
                "No closed, attributed paper trades in the current year.</p>")
    body = ""
    for row in rows:
        mtd, ytd = _f(row.get("mtd_pnl")), _f(row.get("ytd_pnl"))
        body += (f"<tr><td>{_e(row.get('agent_name'))}<br><small>{_e(row.get('framework'))}</small></td>"
                 f"<td style='color:{'#1F5D43' if mtd >= 0 else '#b0653f'}'>${mtd:+,.2f}</td>"
                 f"<td>{int(row.get('mtd_exits') or 0)}</td>"
                 f"<td style='color:{'#1F5D43' if ytd >= 0 else '#b0653f'}'>${ytd:+,.2f}</td>"
                 f"<td>{_f(row.get('win_rate')):.1f}%</td>"
                 f"<td>{int(row.get('run_count') or 0)}</td></tr>")
    return ("<h3>Agent benchmark — realized paper trades only</h3>"
            "<p style='font-size:12px;color:#7A867E'>Account equity is shared and is not assigned "
            "to an agent. This table compares only exits linked to each run.</p>"
            "<table border='1' cellpadding='6' style='border-collapse:collapse;font-size:13px'>"
            "<thead><tr><th>Agent</th><th>MTD P&amp;L</th><th>MTD exits</th>"
            "<th>YTD P&amp;L</th><th>YTD win rate</th><th>Runs</th></tr></thead>"
            f"<tbody>{body}</tbody></table>")


def render(d: dict) -> str:
    sign = "▲" if d["day_pnl"] >= 0 else "▼"
    color = "#1F5D43" if d["day_pnl"] >= 0 else "#b0653f"
    rows = ""
    for p in sorted(d["positions"], key=lambda x: _f(x.get("unrealized_pl")), reverse=True):
        pl = _f(p.get("unrealized_pl"))
        plc = _f(p.get("unrealized_plpc")) * 100
        c = "#1F5D43" if pl >= 0 else "#b0653f"
        rows += (f"<tr><td>{_e(p.get('symbol',''))}</td><td style='text-align:right'>{_f(p.get('qty')):g}</td>"
                 f"<td style='text-align:right'>${_f(p.get('avg_entry_price')):,.2f}</td>"
                 f"<td style='text-align:right'>${_f(p.get('current_price')):,.2f}</td>"
                 f"<td style='text-align:right'>${_f(p.get('market_value')):,.0f}</td>"
                 f"<td style='text-align:right;color:{c}'>${pl:,.0f} ({plc:+.1f}%)</td></tr>")
    if not rows:
        rows = "<tr><td colspan='6' style='color:#7A867E'>No open positions.</td></tr>"
    trade_rows, n_buys, n_sells, realized = _render_trades(d.get("trades", []), d.get("runs") or {})
    day_label = datetime.strptime(d.get("day"), "%Y-%m-%d").strftime("%b %d, %Y") \
        if d.get("day") else datetime.now(timezone.utc).strftime("%b %d, %Y")
    owner = ""
    if d.get("account_name") or d.get("owner_email"):
        owner = ("<p style='background:#EFEDE4;padding:8px 10px'>Account: "
                 f"<b>{_e(d.get('account_name') or 'Paper account')}</b> · owner "
                 f"{_e(d.get('owner_email') or '')}</p>")
    return f"""
<div style="font-family:Inter,Arial,sans-serif;color:#14231B;max-width:760px">
  <h2>AlpaTrade — Daily Paper PnL · {day_label}</h2>
  {owner}
  {_stale_notice(d)}
  <p style="font-size:20px;margin:.2rem 0"><b style="color:{color}">{sign} ${d['day_pnl']:,.2f}
     ({d['day_pct']:+.2f}%)</b>
     <span style="color:#7A867E">today <span style="font-size:12px">(vs prior close)</span></span></p>
  <table style="border-collapse:collapse;margin:.4rem 0">
    <tr><td style="padding:2px 14px 2px 0;color:#415046">Portfolio value</td><td><b>${d['equity']:,.2f}</b></td></tr>
    <tr><td style="padding:2px 14px 2px 0;color:#415046">Cash</td><td>${d['cash']:,.2f}</td></tr>
    <tr><td style="padding:2px 14px 2px 0;color:#415046">Buying power</td><td>${d['buying_power']:,.2f}</td></tr>
    <tr><td style="padding:2px 14px 2px 0;color:#415046">Open unrealised P&amp;L <span style="font-size:11px;color:#7A867E">(since entry)</span></td><td>${d['unrealized_pl']:,.2f}</td></tr>
    <tr><td style="padding:2px 14px 2px 0;color:#415046">Day trades (5d)</td><td>{_e(d['daytrade_count']) or 'None'}</td></tr>
  </table>
  {_render_periods(d)}
  {_render_risk(d)}
  {_render_agent_benchmark(d)}
  {_render_strategy(d)}
  <h3>Open positions ({len(d['positions'])})</h3>
  <table border="1" cellpadding="6" style="border-collapse:collapse;font-size:13px">
    <thead><tr style="background:#EFEDE4"><th>Symbol</th><th>Qty</th><th>Entry</th><th>Price</th><th>Value</th><th>Unrealised P&amp;L</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <h3>Paper trades ({len(d.get('trades', []))})</h3>
  <p style="color:#415046;font-size:13px;margin:.15rem 0 .4rem">{n_buys} buy · {n_sells} sell
     · realised P&amp;L <b style="color:{'#1F5D43' if realized >= 0 else '#b0653f'}">${realized:,.2f}</b></p>
  <table border="1" cellpadding="6" style="border-collapse:collapse;font-size:13px">
    <thead><tr style="background:#EFEDE4"><th>Symbol</th><th>Side</th><th>Qty</th><th>Entry</th><th>Exit</th><th>P&amp;L</th><th>Reasoning</th></tr></thead>
    <tbody>{trade_rows}</tbody>
  </table>
  <p style="color:#7A867E;font-size:12px;margin-top:1rem">Paper trading — simulated, no real money.
  Not financial advice. AlpaTrade holds no funds.</p>
</div>"""


def _render_trades(trades: list[dict], runs: dict[str, dict]) -> tuple[str, int, int, float]:
    """Render the trades <tbody> and return (rows_html, n_buys, n_sells, realized_pnl)."""
    n_buys = n_sells = 0
    realized = 0.0
    rows = ""
    saw_realized = False
    for t in trades:
        sym = t.get("symbol") or ""
        side_raw = (t.get("direction") or "").lower()
        side = side_raw if side_raw in ("buy", "sell") else (
            "buy" if side_raw in ("long", "b") else "sell" if side_raw in ("short", "s") else side_raw
        )
        if side == "buy":
            n_buys += 1
        elif side == "sell":
            n_sells += 1
        qty = _f(t.get("shares"))
        entry = _f(t.get("entry_price"))
        exit_p = _f(t.get("exit_price"))
        pnl = t.get("pnl")
        pnl_val = _f(pnl)
        if pnl is not None:
            saw_realized = True
            realized += pnl_val
        c = "#1F5D43" if pnl_val >= 0 else "#b0653f"
        pnl_cell = (f"${pnl_val:,.2f}" if pnl is not None
                    else ("-" if not exit_p else f"${pnl_val:,.2f}"))
        exit_cell = f"${exit_p:,.2f}" if exit_p else "—"
        reasoning = _e(_explain(t, runs.get(t.get("run_id"))))
        rows += (f"<tr><td>{_e(sym)}</td><td>{_e(side or '—')}</td>"
                 f"<td style='text-align:right'>{qty:g}</td>"
                 f"<td style='text-align:right'>${entry:,.2f}</td>"
                 f"<td style='text-align:right'>{exit_cell}</td>"
                 f"<td style='text-align:right;color:{c}'>{pnl_cell}</td>"
                 f"<td style='font-size:12px;color:#415046'>{reasoning}</td></tr>")
    if not rows:
        rows = "<tr><td colspan='7' style='color:#7A867E'>No paper trades booked.</td></tr>"
    # If no closed trades had a pnl value, don't pretend a $0.00 realised figure.
    if not saw_realized:
        realized = 0.0
    return rows, n_buys, n_sells, realized


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--date", default=None, help="UTC date to report on (YYYY-MM-DD, default today)")
    ap.add_argument("--to", default=None, help="comma-separated recipients (default: PNL_REPORT_TO / list)")
    ap.add_argument("--user", default=None,
                    help="tenant user_id — renders the full per-account report "
                         "(MTD/YTD, agent benchmark, live runs); requires --account")
    ap.add_argument("--account", default=None, help="tenant account_id (requires --user)")
    ap.add_argument("--framework", default=None,
                    help="filter runs/benchmark by agent framework (hermes|deepagents|langgraph|legacy)")
    args = ap.parse_args()

    if args.date:
        datetime.strptime(args.date, "%Y-%m-%d")  # fail fast on a bad date
    if bool(args.user) != bool(args.account):
        print("error: --user and --account must be supplied together")
        return 2

    # Tenant mode: resolve the account's own Alpaca keys (never the env account)
    # so a manual send matches exactly what the scheduler would email that owner.
    keys = None
    if args.user and args.account:
        try:
            from engine.auth import get_alpaca_keys
            keys = get_alpaca_keys(args.user, args.account)
        except Exception as exc:  # noqa: BLE001
            print(f"error: could not resolve Alpaca keys for that account: {exc}")
            return 2
        if not keys:
            print("error: no stored Alpaca keys for that user/account")
            return 2
        reconcile_stale_runs(args.user, args.account)

    to_list = recipients(args.to)
    data = gather(args.date, keys=keys, user_id=args.user,
                  account_id=args.account, framework=args.framework)
    html_out = render(data)
    if not args.send:
        print(html_out)
        n_tr = len(data.get("trades", []))
        n_runs = len(data.get("active_runs", []))
        print(f"\n[dry-run] {data['day']}: day PnL ${data['day_pnl']:,.2f} ({data['day_pct']:+.2f}%), "
              f"equity ${data['equity']:,.2f}, {len(data['positions'])} positions, "
              f"{n_tr} paper trades, {n_runs} running strategy run(s). "
              f"Would email → {', '.join(to_list)}")
        return 0
    from utils.email_util import send_email_to
    day_label = datetime.strptime(data["day"], "%Y-%m-%d").strftime("%b %d, %Y")
    subject = f"AlpaTrade Paper PnL — {day_label} "
    subject += f"({'+' if data['day_pnl'] >= 0 else ''}${data['day_pnl']:,.0f})"
    all_ok = True
    for to in to_list:
        ok = send_email_to(to, subject, html_out)
        all_ok &= ok
        print(f"email → {to}: {'SENT' if ok else 'FAILED (check POSTMARK_API_KEY / FROM_EMAIL)'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
