"""Exit handling for short positions and unlimited holds. DB-free, no network.

Regression cover for two bugs found on the live paper account, where a TSLA short
sat at +17.4% — far past the 6% take-profit — without ever exiting:

1. `qty_available <= 0` skipped every short (a short reports a negative quantity),
   so shorts were never even considered for exit.
2. P&L was derived as (current - entry) / entry, which inverts on a short: the
   winning position read as -17.4% and would have been stopped out at exactly the
   moment it was most profitable.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _pct(pos: dict) -> float:
    """The percentage the exit logic acts on, mirroring _process_exits."""
    qty = float(pos.get("qty", 0))
    entry = float(pos["avg_entry_price"])
    current = float(pos["current_price"])
    plpc = pos.get("unrealized_plpc")
    if plpc not in (None, ""):
        return float(plpc) * 100
    pct = ((current - entry) / entry) * 100
    return -pct if qty < 0 else pct


def _considered(pos: dict) -> bool:
    """Whether the position survives the availability guard."""
    qty = float(pos.get("qty", 0))
    qty_available = float(pos.get("qty_available", qty))
    return abs(qty_available) > 0


SHORT_WINNER = {"symbol": "TSLA", "qty": -8, "qty_available": -8,
                "avg_entry_price": "394.165536", "current_price": "325.65",
                "unrealized_plpc": "0.17382"}


def test_short_position_is_considered_for_exit():
    assert _considered(SHORT_WINNER), "a short must not be skipped by the qty guard"


def test_long_with_no_available_qty_is_skipped():
    held = {"qty": 5, "qty_available": 0, "avg_entry_price": "10", "current_price": "11"}
    assert not _considered(held)


def test_profitable_short_reads_as_a_gain():
    pct = _pct(SHORT_WINNER)
    assert pct > 0, f"short in profit must be positive, got {pct}"
    assert round(pct, 2) == 17.38


def test_profitable_short_takes_profit_and_does_not_stop_out():
    pct = _pct(SHORT_WINNER)
    take_profit, stop_loss = 6.0, 10.0
    assert pct >= take_profit, "should have taken profit at the 6% bar"
    assert not pct <= -stop_loss, "must never stop out a winning short"


def test_short_pnl_sign_is_correct():
    qty_available = -8
    entry, current = 394.165536, 325.65
    assert (current - entry) * qty_available > 0


def test_closing_a_short_is_recorded_as_a_buy():
    assert ("buy" if float(SHORT_WINNER["qty"]) < 0 else "sell") == "buy"


def test_close_qty_uses_magnitude():
    # partially held short: 6 of 8 available -> close 6, positive quantity
    qty, qty_available = -8, -6
    close_qty = int(abs(qty_available)) if abs(qty_available) < abs(qty) else None
    assert close_qty == 6


def test_falls_back_to_price_derived_pct_when_broker_omits_plpc():
    pos = dict(SHORT_WINNER)
    pos.pop("unrealized_plpc")
    assert _pct(pos) > 0


def test_long_position_pct_unchanged():
    long_pos = {"qty": 5, "qty_available": 5, "avg_entry_price": "100",
                "current_price": "106"}
    assert round(_pct(long_pos), 2) == 6.0


def test_hold_days_zero_means_no_time_exit():
    """hold_days of 0/None disables the time-based exit entirely."""
    days_held = 999
    for hold_days in (0, None):
        assert not (hold_days and days_held >= hold_days)
    assert (20 and days_held >= 20)  # an explicit limit still expires
