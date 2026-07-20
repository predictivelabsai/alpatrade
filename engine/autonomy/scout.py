"""Scout — the opportunity scanner that self-feeds the autonomy queue.

Deterministic by default (rank a liquid S&P universe by today's move; no LLM needed),
so it is fully replayable in tests. Produces:
  * ``portfolio_state()`` — live PAPER account equity / open positions / gross exposure
    (the input the RiskPolicy gate needs), and
  * ``scan()`` — ranked :class:`~engine.autonomy.policy.Candidate` list, and
  * ``enqueue_run()`` — create one autonomy run carrying the scouted symbols.

Paper-only: reads the paper account; never places an order.
"""
from __future__ import annotations

import logging
from typing import Optional

from engine.autonomy.policy import Candidate, PortfolioState

log = logging.getLogger("autonomy.scout")

# Strategy → which end of today's move to target.
_DIP_STRATEGIES = {"btd", "buy_the_dip"}

# Scout slug → the backtester's registered strategy name (grid-search rejects slugs).
# The grid-search backtester registers exactly: buy_the_dip, momentum, vix.
_STRATEGY_NAMES = {
    "btd": "buy_the_dip", "buy_the_dip": "buy_the_dip",
    "mom": "momentum", "momentum": "momentum",
    "vix": "vix", "vix_strategy": "vix",
}


def strategy_name(strategy: str) -> str:
    """Map a scout strategy slug to the backtester's full strategy name."""
    return _STRATEGY_NAMES.get((strategy or "").lower(), strategy)


def portfolio_state(account_id: Optional[str] = None) -> PortfolioState:
    """Live PAPER-account snapshot for the RiskPolicy gate."""
    try:
        from engine.brokers.alpaca import AlpacaAPI
        api = AlpacaAPI(paper=True)
        acct = api.get_account() or {}
        positions = api.get_positions() or []
    except Exception as e:  # noqa: BLE001
        log.warning("portfolio_state: broker unreachable (%s)", e)
        return PortfolioState(equity=0.0, open_positions=0, gross_exposure=0.0)
    equity = float(acct.get("equity", 0) or 0)
    gross = 0.0
    for p in positions:
        try:
            gross += abs(float(p.get("market_value", 0) or 0))
        except Exception:  # noqa: BLE001
            continue
    return PortfolioState(equity=equity, open_positions=len(positions), gross_exposure=gross)


def scan(strategy: str = "btd", limit: int = 5, position_pct: float = 0.10,
         period: str = "1d", equity: Optional[float] = None) -> list[Candidate]:
    """Rank the universe by today's move and propose candidates for ``strategy``.

    Dip strategies target the biggest decliners; momentum targets the biggest gainers.
    ``intended_notional`` is ``equity * position_pct`` (equity from the paper account
    when not supplied). Deterministic given the same market data.
    """
    try:
        from engine.market_map import market_map_data
        stocks = [s for s in market_map_data(period).get("stocks", [])
                  if s.get("return") is not None and s.get("price")]
    except Exception as e:  # noqa: BLE001
        log.warning("scan: market data unavailable (%s)", e)
        return []
    if not stocks:
        return []

    dip = strategy.lower() in _DIP_STRATEGIES
    stocks.sort(key=lambda s: s["return"], reverse=not dip)  # decliners first for dips
    if equity is None:
        equity = portfolio_state().equity
    notional = round(max(0.0, equity) * position_pct, 2)

    out = []
    for s in stocks[:limit]:
        out.append(Candidate(symbol=s["ticker"], strategy_slug=strategy,
                             intended_notional=notional, side="buy", is_live=False))
    return out


def enqueue_run(strategy: str = "btd", limit: int = 5,
                user_id: Optional[str] = None, account_id: Optional[str] = None) -> Optional[str]:
    """Scan and enqueue a single autonomy run carrying the scouted symbols.

    Returns the run_id, or None if nothing was found.
    """
    candidates = scan(strategy=strategy, limit=limit)
    if not candidates:
        return None
    from engine.autonomy import queue
    symbols = [c.symbol for c in candidates]
    return queue.enqueue("full", config={
        "strategy": strategy_name(strategy),   # backtester needs the full name, not the slug
        "symbols": symbols,
        "scouted": [{"symbol": c.symbol, "strategy": c.strategy_slug,
                     "notional": c.intended_notional} for c in candidates],
    }, user_id=user_id, account_id=account_id)
