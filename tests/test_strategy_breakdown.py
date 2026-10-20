from datetime import datetime, timezone

from engine.reporting.strategy_breakdown import OTHER, breakdown, normalize_fills
from utils.strategy_allocation import Sleeve

START = datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc)


def _sleeves():
    return [
        {"name": "mag7", "display": "Mag-7 BTD", "sleeve": Sleeve("mag7", "btd", None, True),
         "symbols": ["NVDA", "AAPL"]},
        {"name": "semi7", "display": "Semi-7 BTD", "sleeve": Sleeve("semi7", "s7btd", 1000.0),
         "symbols": ["AMD", "AVGO"]},
    ]


def _fill(oid, sym, side, qty, px, t, cid=""):
    return {"order_id": oid, "symbol": sym, "side": side, "qty": qty, "price": px,
            "transaction_time": t, "client_order_id": cid}


def test_attribution_fifo_and_other():
    raw = [
        _fill("1", "NVDA", "buy", 10, 100, "2026-09-20T15:00:00Z", "btd-NVDA-20260920"),
        _fill("2", "NVDA", "sell", 10, 110, "2026-10-05T15:00:00Z", "btdtp-NVDA-20260920"),
        _fill("3", "AMD", "buy", 5, 200, "2026-10-06T15:00:00Z", "s7btd-AMD-20261006"),
        _fill("4", "AMD", "sell", 5, 190, "2026-10-08T15:00:00Z"),  # no cid -> universe
        _fill("5", "TSLA", "buy", 1, 300, "2026-10-09T15:00:00Z", "manual-1"),
        _fill("6", "BNBX", "buy", 100, 1, "2026-10-09T15:00:00Z"),
    ]
    rows = {r["name"]: r for r in breakdown(
        normalize_fills(raw), [{"symbol": "TSLA", "unrealized_pl": "5", "market_value": "305"}],
        _sleeves(), START, 3000.0, excluded={"BNBX"})}
    assert rows["mag7"]["realized"] == 100 and rows["mag7"]["trades"] == 1 and rows["mag7"]["win_rate"] == 100
    assert rows["semi7"]["realized"] == -50 and rows["semi7"]["win_rate"] == 0
    assert rows["semi7"]["capital"] == 1000 and rows["semi7"]["return_pct"] == -5
    assert rows["mag7"]["capital"] == 2000
    assert rows[OTHER]["positions"] == ["TSLA"] and rows[OTHER]["unrealized"] == 5
    assert "BNBX" not in str(rows)
    assert rows["mag7"]["cum"] == [["2026-10-05", 100.0]]


def test_sell_before_period_ignored_and_unknown_basis():
    raw = [_fill("9", "AAPL", "sell", 1, 100, "2026-10-02T15:00:00Z", "btdx-AAPL-1")]
    r = {x["name"]: x for x in breakdown(normalize_fills(raw), [], _sleeves(), START, 1000)}["mag7"]
    assert r["trades"] == 1 and r["unknown_basis"] == 1 and r["realized"] == 0 and r["win_rate"] is None


def test_panel_renders():
    from engine.web.ph_pnl import _strategy_panel
    raw = [_fill("1", "NVDA", "buy", 1, 100, "2026-10-02T15:00:00Z", "btd-NVDA-1"),
           _fill("2", "NVDA", "sell", 1, 105, "2026-10-03T15:00:00Z", "btdtp-NVDA-1")]
    rows = breakdown(normalize_fills(raw), [], _sleeves(), START, 3000)
    h = _strategy_panel({"strategies": {"rows": rows, "ok": True}}, "MTD")
    assert "Mag-7 BTD" in h and "Semi-7 BTD" in h and "$5.00" in h and "<svg" in h
