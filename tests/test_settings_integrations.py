"""Settings > Integrations: any user can save validated paper AND live Alpaca keys."""
import pytest

from engine import live_accounts as la


class _Resp:
    def __init__(self, code, body):
        self.status_code, self._b = code, body

    def json(self):
        return self._b


class _Http:
    def __init__(self, code=200, body=None):
        self.code, self.body, self.calls = code, body or {}, []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append(url)
        return _Resp(self.code, self.body)


def test_live_keys_validated_read_only_on_live_host():
    h = _Http(200, {"account_number": "999", "status": "ACTIVE", "equity": "10", "cash": "10"})
    info = la.validate_live_keys("AKTEST1234", "s3cret", http=h)
    assert info["account_number"] == "999"
    assert h.calls == ["https://api.alpaca.markets/v2/account"]   # one GET, live host


def test_live_keys_rejections():
    with pytest.raises(la.KeyValidationError, match="unauthorized"):
        la.validate_live_keys("AKTEST1234", "bad", http=_Http(401))
    with pytest.raises(la.KeyValidationError, match="PAPER"):
        la.validate_live_keys("PKTEST1234", "s", http=_Http(200))
    with pytest.raises(la.KeyValidationError, match="required"):
        la.validate_live_keys("", "", http=_Http(200))


def test_paper_keys_validated_on_paper_host():
    h = _Http(200, {"account_number": "PA1", "status": "ACTIVE"})
    assert la.validate_paper_keys("PKTEST1234", "s", http=h)["account_number"] == "PA1"
    assert h.calls == ["https://paper-api.alpaca.markets/v2/account"]
    with pytest.raises(la.KeyValidationError, match="LIVE"):
        la.validate_paper_keys("AKTEST1234", "s", http=h)


def test_integrations_cards_render_for_any_user():
    from fasthtml.common import to_xml
    from engine.web.ph_settings import _live_card, _paper_card
    html = to_xml(_live_card([])) + to_xml(_paper_card([], "", "Not connected"))
    assert "/settings/live-keys" in html and "ALPACA_LIVE_API_KEY" in html and "Not connected" in html
    assert "/settings/keys" in html and "disabled" not in html
    linked = to_xml(_live_card([{"account_number": "885", "label": "Alpaca live", "api_key_hint": "AKxx…yz",
                                 "updated_at": "2026-10-11"}]))
    assert "885" in linked and "AKxx…yz" in linked and "Disconnect 885" in linked
