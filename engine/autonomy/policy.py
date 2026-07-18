"""Deterministic risk policy — pure, replayable, no LLM, no I/O.

"The model may extract facts, but it does not decide whether policy applies."
Given a candidate order and the current portfolio state, decide admit/reject and the
sized notional. Pure functions so historical bars can be replayed in tests.

**Paper-only wall:** ``RiskLimits.allow_live`` is False and cannot be flipped by the
autonomy engine; any candidate marked ``is_live`` is rejected. Live promotion is a
human action taken outside this system.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskLimits:
    max_position_pct: float = 0.10       # per-position cap as a fraction of equity
    max_open_positions: int = 10
    max_gross_exposure_pct: float = 1.0  # total exposure cap as a fraction of equity
    allow_live: bool = False             # HARD paper-only; never True in the autonomy engine


@dataclass(frozen=True)
class Candidate:
    symbol: str
    strategy_slug: str
    intended_notional: float
    side: str = "buy"
    is_live: bool = False                # a live candidate is always rejected here


@dataclass(frozen=True)
class PortfolioState:
    equity: float
    open_positions: int
    gross_exposure: float                # current total position value ($)


@dataclass(frozen=True)
class Decision:
    admit: bool
    reason: str
    sized_notional: float = 0.0


def evaluate(candidate: Candidate, state: PortfolioState,
             limits: RiskLimits = RiskLimits(), *, kill_switch: bool = False) -> Decision:
    """Return an admit/reject + sized notional for one candidate. Pure."""
    if kill_switch:
        return Decision(False, "kill-switch engaged")
    if candidate.is_live or limits.allow_live:
        # The autonomy engine is paper-only by construction.
        return Decision(False, "live orders are disabled (paper-only); promote manually")
    if candidate.intended_notional <= 0:
        return Decision(False, "non-positive intended size")
    if state.equity <= 0:
        return Decision(False, "no equity")
    if state.open_positions >= limits.max_open_positions:
        return Decision(False, f"max open positions reached ({limits.max_open_positions})")

    sized = min(candidate.intended_notional, state.equity * limits.max_position_pct)
    headroom = state.equity * limits.max_gross_exposure_pct - state.gross_exposure
    if headroom <= 0:
        return Decision(False, "gross exposure limit reached")
    sized = min(sized, headroom)
    if sized <= 0:
        return Decision(False, "no sizing headroom")
    return Decision(True, "admitted", round(sized, 2))
