"""Paper-only Alpaca index-options helpers.

Alpaca initially supports Cboe index options for SPX, SPXW, VIX, VIXW, DJX,
and XSP.  These helpers deliberately reject non-paper clients.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

SUPPORTED_INDEXES = frozenset({"SPX", "SPXW", "VIX", "VIXW", "DJX", "XSP"})


def _dump(model: Any) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if hasattr(model, "dict"):
        return model.dict()
    return dict(model)


def _require_paper(client: Any) -> None:
    if getattr(client, "paper", None) is False:
        raise ValueError("Index-options execution is restricted to Alpaca paper trading.")


def list_contracts(
    client: Any,
    underlying: str,
    *,
    contract_type: str | None = None,
    min_expiration: str | None = None,
    max_expiration: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Return active European-style contracts for one supported index."""
    from alpaca.trading.enums import AssetStatus, ContractType, ExerciseStyle
    from alpaca.trading.requests import GetOptionContractsRequest

    _require_paper(client)
    underlying = (underlying or "").upper().strip()
    if underlying not in SUPPORTED_INDEXES:
        raise ValueError(f"Supported index underlyings: {', '.join(sorted(SUPPORTED_INDEXES))}.")
    option_type = (contract_type or "").lower().strip()
    if option_type not in ("", "call", "put"):
        raise ValueError("contract_type must be 'call' or 'put'.")
    today = date.today()
    request = GetOptionContractsRequest(
        underlying_symbols=[underlying],
        status=AssetStatus.ACTIVE,
        style=ExerciseStyle.EUROPEAN,
        type=ContractType(option_type) if option_type else None,
        expiration_date_gte=min_expiration or (today + timedelta(days=1)),
        expiration_date_lte=max_expiration or (today + timedelta(days=60)),
        limit=max(1, min(int(limit), 100)),
    )
    response = client.get_option_contracts(request)
    return [_dump(contract) for contract in response.option_contracts]


def submit_order(
    client: Any,
    symbol: str,
    qty: int,
    side: str,
    *,
    limit_price: float | None = None,
    client_order_id: str | None = None,
) -> dict:
    """Submit a DAY order for an index-option contract in paper trading."""
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest

    _require_paper(client)
    symbol = (symbol or "").upper().strip()
    side = (side or "").lower().strip()
    if not symbol or not any(symbol.startswith(root) for root in SUPPORTED_INDEXES):
        raise ValueError("Use an Alpaca contract symbol for a supported index option.")
    if side not in ("buy", "sell"):
        raise ValueError("side must be 'buy' or 'sell'.")
    if int(qty) != qty or qty <= 0:
        raise ValueError("qty must be a positive whole number of contracts.")
    common = dict(
        symbol=symbol,
        qty=int(qty),
        side=OrderSide(side),
        time_in_force=TimeInForce.DAY,
    )
    if client_order_id:
        common["client_order_id"] = client_order_id
    if limit_price is None:
        request = MarketOrderRequest(**common)
    else:
        if float(limit_price) <= 0:
            raise ValueError("limit_price must be greater than zero.")
        request = LimitOrderRequest(**common, limit_price=float(limit_price))
    return _dump(client.submit_order(request))
