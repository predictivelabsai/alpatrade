"""Cross-sectional valuation grid strategy with publication-lagged EPS.

Daily signals execute at the next session open, including close-based stops.
Each rebalance sells the previous basket and equally allocates the net cash.
The final open is a scheduled liquidation, decided on the penultimate bar.
"""
from __future__ import annotations

import math
from datetime import datetime

import pandas as pd

from engine.feeds.fundamentals import CachedFundamentals, daily_valuation
from utils.fees import calculate_cat_fee, calculate_finra_taf_fee
from utils.paper_strategies import VALUATION_MODES as MODES


def select_symbols(values: dict[str, dict], mode: str, top_n: int = 3) -> list[str]:
    """Select a deterministic basket from positive, finite cross-sectional P/E."""
    if mode not in MODES:
        raise ValueError(f"Unknown valuation mode: {mode}. Choose {', '.join(MODES)}.")
    valid = {s: v for s, v in values.items()
             if math.isfinite(float(v["pe"])) and float(v["pe"]) > 0}
    if mode == "below_median":
        median = pd.Series([v["pe"] for v in valid.values()], dtype=float).median()
        return sorted(s for s, v in valid.items() if v["pe"] < median)
    if mode == "peg_under_1":
        return sorted(s for s, v in valid.items() if 0 < v.get("peg", float("nan")) < 1)
    return sorted(valid, key=lambda s: ((-1 if mode == "high_pe" else 1) * valid[s]["pe"], s))[:top_n]


def load_valuation_data(symbols: list[str], start_date: datetime, end_date: datetime,
                        data_source: str = "yfinance") -> tuple[dict, dict]:
    """Fetch once per run, before sweeping parameters. Provider failures are fatal."""
    from engine.feeds.market_data import MarketDataUtil

    provider = CachedFundamentals()
    market = MarketDataUtil(provider=data_source)
    prices, values = {}, {}
    for symbol in dict.fromkeys(symbols):
        payload = provider.get_fundamentals(symbol)
        frame = market.get_historical_data(symbol, start_date, end_date).copy()
        if frame.empty:
            raise ValueError(f"No daily prices for {symbol}; valuation universe cannot be silently reduced.")
        frame.index = pd.DatetimeIndex(frame.index).tz_localize(None).normalize()
        frame = frame.sort_index()
        frame = frame.loc[(frame.index >= pd.Timestamp(start_date).normalize()) &
                          (frame.index <= pd.Timestamp(end_date).normalize())]
        prices[symbol] = frame
        values[symbol] = daily_valuation(payload, frame["Close"])
    return prices, values


def backtest_valuation(prices: dict[str, pd.DataFrame], values: dict[str, pd.DataFrame],
                       start_date: datetime, end_date: datetime,
                       initial_capital: float = 10000, mode: str = "low_pe",
                       top_n: int = 3, rebalance: str = "monthly", stop_loss: float = 0,
                       slippage_bps: float = 10, include_taf_fees: bool = False,
                       include_cat_fees: bool = False) -> tuple[pd.DataFrame, dict]:
    """Run a long-only, unlevered basket. stop_loss is a ratio (0 disables it).

    Daily US sessions must align: a missing bar fails explicitly, so a suspended
    symbol is never sold on an invented open or silently removed from the basket.
    """
    from utils.backtester_util import calculate_portfolio_metrics

    if mode not in MODES or rebalance not in ("monthly", "quarterly"):
        raise ValueError("Valuation requires a supported mode and monthly/quarterly rebalance.")
    if int(top_n) != top_n or top_n < 1 or not 0 <= stop_loss < 1:
        raise ValueError("top_n must be a positive integer; stop_loss must be a ratio in [0, 1).")
    top_n = int(top_n)
    if not math.isfinite(initial_capital) or initial_capital <= 0 or not 0 <= slippage_bps < 10000:
        raise ValueError("Capital must be positive and slippage_bps must be in [0, 10000).")
    if not prices:
        raise ValueError("Valuation requires daily prices for the requested universe.")
    dates = next(iter(prices.values())).index
    if len(dates) < 3:
        raise ValueError("Valuation requires at least three daily bars.")
    for symbol, frame in prices.items():
        if (not frame.index.equals(dates) or frame.index.has_duplicates
                or not frame.index.is_monotonic_increasing):
            raise ValueError(f"Daily sessions do not align for {symbol}; repair missing price data.")
        if not frame[["Open", "Close"]].apply(
                lambda column: column.map(lambda x: math.isfinite(float(x)) and x > 0)
        ).all().all():
            raise ValueError(f"Invalid Open/Close prices for {symbol}.")
    if set(values) != set(prices) or any(not values[s].index.equals(dates) for s in prices):
        raise ValueError("Daily fundamentals must align with the price universe and sessions.")
    cash = float(initial_capital)
    slip = slippage_bps / 10000
    positions, trades, equity = {}, [], []
    pending_basket = None
    pending_stops = set()
    last_period = None
    realised = float(initial_capital)

    def sell(symbol, date, reason):
        nonlocal cash, realised
        position = positions.pop(symbol)
        qty = position["shares"]
        price = float(prices[symbol].at[date, "Open"]) * (1 - slip)
        taf = float(calculate_finra_taf_fee(qty)) if include_taf_fees else 0.0
        cat = float(calculate_cat_fee(qty)) if include_cat_fees else 0.0
        cash += qty * price - taf - cat
        fees = position["entry_fee"] + taf + cat
        pnl = qty * (price - position["entry_price"]) - fees
        realised += pnl
        trades.append({
            "ticker": symbol, "entry_time": position["entry_time"], "exit_time": date,
            "signal_time": position["signal_time"], "exit_signal_time": position.get("exit_signal_time"),
            "entry_price": position["entry_price"], "exit_price": price, "shares": qty,
            "pnl": pnl, "pnl_pct": pnl / (qty * position["entry_price"]) * 100,
            "capital_after": realised, "reason": reason, "exit_reason": reason,
            "hit_stop": reason == "stop_loss", "hit_target": False,
            "taf_fee": taf, "cat_fee": position["entry_fee"] + cat, "total_fees": fees,
        })

    for i, date in enumerate(dates):
        # All orders here were decided using the previous session's close.
        if i == len(dates) - 1:
            for symbol in list(positions):
                positions[symbol]["exit_signal_time"] = dates[i - 1]
                sell(symbol, date, "end_of_period")
        elif pending_basket is not None:
            for symbol in list(positions):
                positions[symbol]["exit_signal_time"] = dates[i - 1]
                sell(symbol, date, "rebalance")
            allocation = cash / len(pending_basket) if pending_basket else 0
            for symbol in pending_basket:
                price = float(prices[symbol].at[date, "Open"]) * (1 + slip)
                cat_per_share = float(calculate_cat_fee(1)) if include_cat_fees else 0
                qty = allocation / (price + cat_per_share)
                entry_fee = qty * cat_per_share
                cash -= qty * price + entry_fee
                positions[symbol] = {"shares": qty, "entry_price": price,
                                     "entry_time": date, "signal_time": dates[i - 1],
                                     "entry_fee": entry_fee}
        else:
            for symbol in pending_stops:
                if symbol in positions:
                    positions[symbol]["exit_signal_time"] = dates[i - 1]
                    sell(symbol, date, "stop_loss")
        pending_basket = None
        pending_stops = set()
        equity.append({"timestamp": date, "equity": cash + sum(
            p["shares"] * float(prices[s].at[date, "Close"]) for s, p in positions.items())})
        period = (date.year, date.month if rebalance == "monthly" else (date.month - 1) // 3)
        if i < len(dates) - 2 and period != last_period:
            cross_section = {s: v.loc[date].to_dict() for s, v in values.items()}
            pending_basket = select_symbols(cross_section, mode, top_n)
        elif stop_loss and i < len(dates) - 1:
            pending_stops = {s for s, p in positions.items()
                             if float(prices[s].at[date, "Close"]) <= p["entry_price"] * (1 - stop_loss)}
        last_period = period
    # Initial cash participates in first-day drawdown and returns.
    metrics = calculate_portfolio_metrics(pd.DataFrame(equity), initial_capital, start_date, end_date)
    metrics.update(total_trades=len(trades), win_rate=(
        sum(t["pnl"] > 0 for t in trades) / len(trades) * 100 if trades else 0))
    metrics["equity_curve"] = equity
    return pd.DataFrame(trades), metrics
