"""Settings > Integrations "Check" for saved Alpaca keys."""
from engine import key_check as kc
from engine.web import ph_settings as ps


class R:
    def __init__(self, code, body):
        self.status_code, self._b, self.text = code, body, str(body)

    def json(self):
        return self._b


class H:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def get(self, url, timeout=None, headers=None):
        self.calls.append(url)
        return self.resp


def test_call_ok_and_401():
    h = H(R(200, {"account_number": "PA123", "status": "ACTIVE"}))
    r = kc.call_account(kc.PAPER, "PKX", "s", http=h)
    assert r["ok"] and "PA123" in r["text"] and "ACTIVE" in r["text"]
    assert h.calls == ["https://paper-api.alpaca.markets/v2/account"]
    r = kc.call_account(kc.LIVE, "AKX", "s", http=H(R(401, {"message": "unauthorized."})))
    assert not r["ok"] and r["text"] == "HTTP 401 from api.alpaca.markets: unauthorized."


def test_inspect_pair_flags_our_side():
    assert kc.inspect_pair("PKABC", "sec", "paper") == []
    out = kc.inspect_pair("PKABC\n", "se c", "paper")
    assert any("whitespace" in x for x in out) and len(out) >= 2
    assert any("wrong environment" in x for x in kc.inspect_pair("AKX", "s", "paper"))
    assert any("wrong environment" in x for x in kc.inspect_pair("PKX", "s", "live"))


def test_check_uses_matching_endpoint_and_saves(monkeypatch):
    from engine import auth
    monkeypatch.setattr(kc, "ensure_schema", lambda: None)
    monkeypatch.setattr(kc, "_row", lambda m, u, r: (b"k", b"s"))
    monkeypatch.setattr(auth, "decrypt_key", lambda b: {b"k": "AKLIVE", b"s": "sec"}[b])
    saved = []
    monkeypatch.setattr(kc, "_save", lambda *a: saved.append(a))
    h = H(R(200, {"account_number": "999", "status": "ACTIVE"}))
    r = kc.check("live", "u", "999", http=h)
    assert r["ok"] and h.calls == ["https://api.alpaca.markets/v2/account"] and saved[0][:3] == ("live", "u", "999")
    r = kc.check("live", "u", "111", http=h)  # keys belong to another account
    assert not r["ok"] and "999" in r["text"]


def test_check_reports_decrypt_failure(monkeypatch):
    from engine import auth
    monkeypatch.setattr(kc, "ensure_schema", lambda: None)
    monkeypatch.setattr(kc, "_row", lambda m, u, r: (b"k", b"s"))
    monkeypatch.setattr(kc, "_save", lambda *a: None)

    def boom(b):
        raise ValueError("InvalidToken")
    monkeypatch.setattr(auth, "decrypt_key", boom)
    r = kc.check("paper", "u", "00000000-0000-0000-0000-000000000000")
    assert not r["ok"] and "could not be decrypted" in r["text"]


def test_cards_render_check_button_and_last_result():
    import datetime as dt
    at = dt.datetime(2026, 10, 11, 18, 0, tzinfo=dt.timezone.utc)
    checks = {("paper", "a1"): {"at": at, "ok": False, "text": "HTTP 401 from paper-api.alpaca.markets: unauthorized."}}
    from fasthtml.common import to_xml
    h = to_xml(ps._paper_card([{"account_id": "a1", "account_name": "Default", "api_key_hint": "PK…AB"}], "a1", "x", checks))
    assert "/settings/keys/check" in h and "value='paper'" in h and "value='a1'" in h
    assert "unauthorized." in h and "checked 2026-10-11 18:00 UTC" in h and "s-chk bad" in h
    h = to_xml(ps._live_card([{"account_number": "885", "api_key_hint": "AK…"}], {}))
    assert "value='live'" in h and "value='885'" in h and "s-chk ok" not in h and "s-chk bad" not in h
