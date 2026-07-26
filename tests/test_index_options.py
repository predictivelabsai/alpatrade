from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from engine.brokers.index_options import list_contracts, submit_order


def test_list_contracts_filters_for_european_index_options():
    client = MagicMock()
    client.paper = True
    client.get_option_contracts.return_value = SimpleNamespace(
        option_contracts=[
            SimpleNamespace(model_dump=lambda **_: {
                "symbol": "XSP260821P00500000",
                "style": "european",
            })
        ]
    )

    result = list_contracts(client, "xsp", contract_type="put", limit=5)

    request = client.get_option_contracts.call_args.args[0]
    assert request.underlying_symbols == ["XSP"]
    assert request.style.value == "european"
    assert request.type.value == "put"
    assert result[0]["symbol"] == "XSP260821P00500000"


def test_rejects_unsupported_underlying():
    client = MagicMock()
    client.paper = True
    with pytest.raises(ValueError, match="Supported index"):
        list_contracts(client, "SPY")


def test_rejects_live_order_client():
    client = MagicMock()
    client.paper = False
    with pytest.raises(ValueError, match="paper"):
        submit_order(client, "XSP260821P00500000", 1, "buy")


def test_submits_whole_contract_day_limit_order():
    client = MagicMock()
    client.paper = True
    client.submit_order.return_value = SimpleNamespace(
        model_dump=lambda **_: {"id": "paper-order", "status": "accepted"}
    )

    result = submit_order(
        client, "XSP260821P00500000", 1, "buy", limit_price=2.10,
    )

    request = client.submit_order.call_args.args[0]
    assert request.symbol == "XSP260821P00500000"
    assert float(request.limit_price) == 2.10
    assert request.time_in_force.value == "day"
    assert result["id"] == "paper-order"
