"""Event-driven, shared-capital simulation over daily bars.

Order of operations per calendar date (keeps signal timing separate from fill timing,
so there is no look-ahead under the default next_open model):

  1. EXITS  — for positions opened on a prior day, check stop, then take-profit
              (conservative intrabar conflict policy), then hold-expiry exit at open.
  2. FILLS  — entries signalled on the previous bar fill at today's open (next_open).
  3. SIGNALS— at today's close, queue new entries for tomorrow's open.
  4. MARK   — value the portfolio at today's close → daily equity point.

Returns realized round trips, the daily equity curve, and the per-fill log.
"""
from __future__ import annotations

from typing import Dict, List

import pandas as pd

from engine.backtest.fills import Friction, fill_price_for_bar, limit_fill, size_shares, stop_fill
from engine.backtest.strategies import BuyTheDip


def simulate(
    symbol_bars: Dict[str, pd.DataFrame],
    strategy: BuyTheDip,
    initial_capital: float,
    fill_model: str = "next_open",
    friction: Friction | None = None,
    fractional: bool = False,
) -> tuple[List[dict], pd.Series, List[dict]]:
    friction = friction or Friction()
    cash = float(initial_capital)
    positions: Dict[str, dict] = {}          # symbol -> open position
    pending: Dict[str, dict] = {}            # symbol -> entry queued at prior close
    round_trips: List[dict] = []
    fills: List[dict] = []

    # Per-symbol date→row-index maps and the global ordered date axis.
    date_index: Dict[str, Dict[pd.Timestamp, int]] = {}
    for sym, df in symbol_bars.items():
        date_index[sym] = {ts: i for i, ts in enumerate(df.index)}
    all_dates = sorted({ts for df in symbol_bars.values() for ts in df.index})

    equity_points: Dict[pd.Timestamp, float] = {}

    for d in all_dates:
        # ---- 1. EXITS -------------------------------------------------------
        for sym in list(positions.keys()):
            df = symbol_bars[sym]
            if d not in date_index[sym]:
                continue
            i = date_index[sym][d]
            if i <= positions[sym]["entry_idx"]:
                continue  # no same-bar exit on the fill bar
            bar = _bar(df, i)
            pos = positions[sym]
            exit_price = None
            reason = None
            held = i - pos["entry_idx"]
            # Minimum hold (PDT-safe swing): suppress TP/SL exits until min_hold_days have
            # elapsed; after that, intrabar TP/SL exits are allowed (0 = current behaviour).
            min_hold = getattr(strategy, "min_hold_days", 0) or 0
            if held >= min_hold:
                # conservative: stop before target
                sp = stop_fill("sell", pos["stop"], bar, friction)
                if sp is not None:
                    exit_price, reason = sp, "stop_loss"
                else:
                    tp = limit_fill("sell", pos["target"], bar, friction)
                    if tp is not None:
                        exit_price, reason = tp, "take_profit"
            if exit_price is None and held >= strategy.hold_days:
                exit_price, reason = friction.sell(bar["o"]), "hold_expiry"
            if exit_price is not None:
                proceeds = pos["shares"] * exit_price
                cash += proceeds
                pnl = (exit_price - pos["entry_price"]) * pos["shares"]
                round_trips.append({
                    "symbol": sym, "shares": pos["shares"],
                    "entry_time": pos["entry_time"], "entry_price": pos["entry_price"],
                    "exit_time": d.isoformat(), "exit_price": exit_price,
                    "target_price": pos["target"], "stop_price": pos["stop"],
                    "hit_target": reason == "take_profit", "hit_stop": reason == "stop_loss",
                    "pnl": pnl, "pnl_pct": (exit_price / pos["entry_price"] - 1) if pos["entry_price"] else 0.0,
                    "fees": 0.0, "reason": reason, "capital_after": cash,
                })
                fills.append({"time": d.isoformat(), "symbol": sym, "side": "sell",
                              "shares": pos["shares"], "price": exit_price, "reason": reason})
                del positions[sym]

        # ---- 2. FILLS (entries queued yesterday fill at today's open) -------
        for sym in list(pending.keys()):
            df = symbol_bars[sym]
            if d not in date_index[sym]:
                continue
            i = date_index[sym][d]
            bar = _bar(df, i)
            sig = pending.pop(sym)
            if sym in positions:
                continue
            fill_price = fill_price_for_bar(fill_model, "buy", bar, friction)
            shares = size_shares(cash, strategy.position_size, sig["signal_close"], fractional)
            if shares <= 0 or shares * fill_price > cash:
                continue
            cash -= shares * fill_price
            target, stop = strategy.brackets(fill_price)
            positions[sym] = {
                "shares": shares, "entry_price": fill_price, "entry_time": d.isoformat(),
                "entry_idx": i, "target": target, "stop": stop,
            }
            fills.append({"time": d.isoformat(), "symbol": sym, "side": "buy",
                          "shares": shares, "price": fill_price, "reason": sig["reason"]})

        # ---- 3. SIGNALS at today's close -----------------------------------
        for sym, df in symbol_bars.items():
            if d not in date_index[sym]:
                continue
            if sym in positions or sym in pending:
                continue
            i = date_index[sym][d]
            sig = strategy.entry(df, i)
            if sig is not None:
                pending[sym] = {"signal_close": float(df["c"].iloc[i]), "reason": sig.reason}

        # ---- 4. MARK to market at close ------------------------------------
        equity = cash
        for sym, pos in positions.items():
            if d in date_index[sym]:
                equity += pos["shares"] * float(symbol_bars[sym]["c"].iloc[date_index[sym][d]])
            else:
                equity += pos["shares"] * pos["entry_price"]
        equity_points[d] = equity

    daily_equity = pd.Series(equity_points).sort_index()
    return round_trips, daily_equity, fills


def equal_weight_buy_hold(symbol_bars: Dict[str, pd.DataFrame], initial_capital: float) -> pd.Series:
    """Benchmark: equal-weight buy-and-hold of the universe, no rebalancing."""
    per_symbol = initial_capital / max(len(symbol_bars), 1)
    series = []
    for sym, df in symbol_bars.items():
        if df.empty:
            continue
        first_close = float(df["c"].iloc[0])
        if first_close <= 0:
            continue
        shares = per_symbol / first_close
        series.append((df["c"] * shares).rename(sym))
    if not series:
        return pd.Series(dtype=float)
    combined = pd.concat(series, axis=1).sort_index().ffill()
    return combined.sum(axis=1)


def _bar(df: pd.DataFrame, i: int) -> dict:
    row = df.iloc[i]
    return {"o": float(row["o"]), "h": float(row["h"]), "l": float(row["l"]),
            "c": float(row["c"]), "v": float(row["v"])}
