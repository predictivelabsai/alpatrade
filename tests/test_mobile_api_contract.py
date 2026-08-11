"""DB-free regression tests for the mobile REST contract."""

from enum import Enum

import pytest

from api_app import _position_item_from_alpaca, app


class _Side(Enum):
    SHORT = "short"


def test_openapi_includes_direct_paper_order_endpoint():
    assert "/v2/order" in app.openapi()["paths"]


def test_alpaca_position_maps_ratio_pnl_to_percent():
    item = _position_item_from_alpaca({
        "symbol": "AAPL",
        "side": _Side.SHORT,
        "qty": "-3",
        "avg_entry_price": "301.32",
        "current_price": "313.33",
        "market_value": "-939.99",
        "unrealized_pl": "-36.03",
        "unrealized_plpc": "-0.03986",
        "cost_basis": "-903.96",
    })

    assert item.symbol == "AAPL"
    assert item.side == "short"
    assert item.shares == 3
    assert item.unrealized_pnl == pytest.approx(-36.03)
    assert item.unrealized_pnl_pct == pytest.approx(-3.986)
    assert item.status == "open"
