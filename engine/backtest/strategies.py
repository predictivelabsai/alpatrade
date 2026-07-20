"""Pluggable strategy signal/exit logic for the Phase-0 backtest engine.

A strategy formalizes an idea into precise rules (skill: "translate your freeform idea
into precise mathematical rules"). Phase 0 ships buy_the_dip; the full asset-agnostic
Strategy protocol arrives with the engine extraction in Phase 1.

A strategy exposes:
  - name, params, warmup()  — lookback bars the feed must pre-roll
  - entry(bars, i)          — at bar i close, return an EntrySignal or None
  - brackets(entry_price)   — (target_price, stop_price) for the filled position
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


@dataclass(frozen=True)
class EntrySignal:
    side: str = "buy"
    reason: str = ""


@dataclass
class BuyTheDip:
    """Buy when price dips `dip_threshold` below the rolling high; exit on take-profit,
    stop-loss, or after `hold_days`. Sizing is `position_size` of available cash."""

    name: str = "buy_the_dip"
    dip_threshold: float = 0.02      # fractional drop from rolling high to trigger entry
    lookback: int = 20               # bars in the rolling-high window
    position_size: float = 0.10      # fraction of cash per entry
    take_profit: float = 0.01        # fractional gain to exit
    stop_loss: float = 0.005         # fractional loss to exit
    hold_days: int = 3               # max bars to hold before exit-at-open
    min_hold_days: int = 0           # min bars before any TP/SL exit (PDT-safe swing)
    params: dict = field(default_factory=dict)

    def __post_init__(self):
        # Snapshot the formalized rules for strategy_spec.json
        self.params = {
            "dip_threshold": self.dip_threshold,
            "lookback": self.lookback,
            "position_size": self.position_size,
            "take_profit": self.take_profit,
            "stop_loss": self.stop_loss,
            "hold_days": self.hold_days,
            "min_hold_days": self.min_hold_days,
        }

    def warmup(self) -> int:
        return self.lookback

    def entry(self, bars: pd.DataFrame, i: int) -> Optional[EntrySignal]:
        """At bar i (0-based row in this symbol's bars), decide whether to enter."""
        if i < self.lookback:
            return None
        window_high = bars["h"].iloc[i - self.lookback : i + 1].max()
        close = bars["c"].iloc[i]
        if window_high > 0 and close <= window_high * (1 - self.dip_threshold):
            return EntrySignal(side="buy", reason=f"dip {self.dip_threshold:.1%} from {self.lookback}-bar high")
        return None

    def brackets(self, entry_price: float) -> tuple[float, float]:
        target = entry_price * (1 + self.take_profit)
        stop = entry_price * (1 - self.stop_loss)
        return target, stop


STRATEGIES = {"buy_the_dip": BuyTheDip}


def build_strategy(name: str, **params) -> BuyTheDip:
    if name not in STRATEGIES:
        raise ValueError(f"Unknown strategy {name!r}; available: {sorted(STRATEGIES)}")
    return STRATEGIES[name](**params)
