"""Read-only live account view: GET-only client, isolation from paper paths,
paper-only order guards, per-user scoping, route/render and dev-login gating.
Offline — Alpaca and the DB are mocked."""
from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from fastcore.xml import to_xml

from engine.brokers import alpaca_live_readonly as ro
from engine.web import ph_devlogin, ph_live_account

ROOT = Path(__file__).resolve().parents[1]

ACCOUNT = {"account_number": "885504372", "status": "ACTIVE", "currency": "USD",
           "equity": "10500.50", "last_equity": "10400.00", "cash": "1200.25",
           "buying_power": "2400.50", "long_market_value": "9300.25"}
POSITIONS = [
    {"symbol": "AFRM", "side": "long", "qty": "12", "avg_entry_price": "60.10",
     "current_price": "62.00", "market_value": "744.00", "unrealized_pl": "22.80",
     "unrealized_plpc": "0.0316", "unrealized_intraday_pl": "3.1"},
    {"symbol": "BNBX", "side": "long", "qty": "0.5", "avg_entry_price": "10",
     "current_price": "9", "market_value": "4.5", "unrealized_pl": "-0.5",
     "unrealized_plpc": "-0.1", "unrealized_intraday_pl": "0"},
]
ORDERS = [{"symbol": "AFRM", "side": "sell", "type": "market", "qty": "12", "notional": None,
           "limit_price": None, "time_in_force": "day", "status": "accepted",
           "submitted_at": "2026-09-25T04:00:01.5Z"}]


class FakeHTTP:
    """Records every call; exposes only .get so any other verb would AttributeError."""

    def __init__(self, payloads=None, status=200):
        self.calls = []
        self.payloads = payloads or {"/v2/account": ACCOUNT, "/v2/positions": POSITIONS,
                                     "/v2/orders": ORDERS}
        self.status = status

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append(("GET", url, params))
        path = url.replace(ro.LIVE_BASE_URL, "")
        return SimpleNamespace(status_code=self.status, json=lambda: self.payloads[path])


def _client(http=None, expected="885504372"):
    return ro.LiveReadOnlyClient("AKTESTKEY123456", "SECRETVALUE987654321",
                                 expected_account_number=expected, http=http or FakeHTTP())


# ---- GET-only client -------------------------------------------------------

def test_snapshot_uses_only_three_allowlisted_gets_on_live_host():
    http = FakeHTTP()
    snap = _client(http).snapshot()
    assert snap["account"]["account_number"] == "885504372"
    assert [c[0] for c in http.calls] == ["GET", "GET", "GET"]
    assert [(c[1], c[2]) for c in http.calls] == [
        ("https://api.alpaca.markets/v2/account", None),
        ("https://api.alpaca.markets/v2/positions", None),
        ("https://api.alpaca.markets/v2/orders", {"status": "open"}),
    ]


@pytest.mark.parametrize("path,params", [
    ("/v2/orders", {"status": "all"}),
    ("/v2/orders", None),
    ("/v2/positions/AFRM", None),
    ("/v2/account/activities", None),
    ("/v2/watchlists", None),
])
def test_non_allowlisted_reads_are_refused_before_any_network(path, params):
    http = FakeHTTP()
    with pytest.raises(ro.LiveReadOnlyError):
        _client(http)._get(path, params)
    assert http.calls == []


def test_client_exposes_no_mutating_operations():
    names = {n.lower() for n in dir(ro.LiveReadOnlyClient)}
    for bad in ("submit", "order_create", "create_order", "cancel", "close", "replace",
                "post", "delete", "patch", "put", "liquidate"):
        assert not any(bad in n for n in names), bad
    src = (ROOT / "engine/brokers/alpaca_live_readonly.py").read_text()
    for verb in (".post(", ".delete(", ".patch(", ".put(", ".request(", "TradingClient"):
        assert verb not in src, verb
    assert ro.LIVE_BASE_URL == "https://api.alpaca.markets"
    assert set(ro.ALLOWED_GETS) == {"/v2/account", "/v2/positions", "/v2/orders"}


def test_account_number_mismatch_refuses_display():
    http = FakeHTTP({**FakeHTTP().payloads, "/v2/account": {**ACCOUNT, "account_number": "999"}})
    with pytest.raises(ro.LiveAccountMismatch):
        _client(http).snapshot()
    assert len(http.calls) == 1  # never went on to positions/orders


def test_errors_and_repr_never_contain_credentials():
    c = _client(FakeHTTP(status=401))
    with pytest.raises(ro.LiveReadOnlyError) as ei:
        c.get_account()
    for secret in ("AKTESTKEY123456", "SECRETVALUE987654321"):
        assert secret not in str(ei.value) and secret not in repr(c)

    class Boom:
        def get(self, *a, **k):
            raise ConnectionError("headers AKTESTKEY123456 SECRETVALUE987654321")
    with pytest.raises(ro.LiveReadOnlyError) as ei:
        _client(Boom()).get_account()
    assert "SECRETVALUE" not in str(ei.value)


def test_summarize_account_day_pl():
    s = ro.summarize_account(ACCOUNT)
    assert s["equity"] == pytest.approx(10500.50)
    assert s["day_pl"] == pytest.approx(100.50)
    assert s["day_pl_pct"] == pytest.approx(100.5 / 10400 * 100)


# ---- paper-only guards on shared order paths --------------------------------

def _api(paper):
    from engine.brokers.alpaca import AlpacaAPI
    with mock.patch("engine.brokers.alpaca.TradingClient"):
        api = AlpacaAPI(api_key="AKLIVE0000", secret_key="s", paper=paper)
    api.trading_client = mock.MagicMock()
    return api


@pytest.mark.parametrize("call", [
    lambda a: a.create_order("AAPL", qty=1),
    lambda a: a.create_order("AAPL", notional=100),
    lambda a: a.cancel_order("abc"),
    lambda a: a.cancel_all_orders(),
    lambda a: a.close_position("AAPL"),
    lambda a: a.close_all_positions(cancel_orders=True),
])
def test_alpaca_wrapper_refuses_every_mutation_on_live(call):
    api = _api(paper=False)
    out = call(api)
    assert out.get("refused") is True and "LIVE" in out["error"]
    api.trading_client.submit_order.assert_not_called()
    api.trading_client.cancel_order_by_id.assert_not_called()
    api.trading_client.cancel_orders.assert_not_called()
    api.trading_client.close_position.assert_not_called()
    api.trading_client.close_all_positions.assert_not_called()


def test_alpaca_wrapper_still_mutates_paper():
    api = _api(paper=True)
    api.cancel_all_orders()
    api.trading_client.cancel_orders.assert_called_once()
    api.close_position("AAPL")
    api.trading_client.close_position.assert_called_once()


def test_store_alpaca_keys_refuses_live_keys_without_touching_db(monkeypatch):
    import engine.auth as auth
    monkeypatch.setattr(auth, "_get_pool", mock.Mock(side_effect=AssertionError("db touched")))
    for k in ("AKXXXXXXXX", " akxxxx "):
        with pytest.raises(ValueError, match="LIVE"):
            auth.store_alpaca_keys("u1", k, "secret")
    assert auth.is_live_alpaca_key("AK123") and not auth.is_live_alpaca_key("PK123")


def test_live_link_table_is_only_used_by_the_readonly_view():
    """Structural isolation: no chat tool / paper job / reconcile / cleanup code can
    reach the live credentials, because only these files reference them."""
    allowed = {"engine/live_accounts.py", "engine/web/ph_live_account.py",
               "scripts/link_live_account.py", "tests/test_live_account.py"}
    pat = re.compile(r"user_live_broker_accounts|engine\.live_accounts|get_live_account_credentials"
                     r"|alpaca_live_readonly")
    hits = set()
    for sub in ("engine", "utils", "agents", "verticals", "tui", "scripts", "tests"):
        for p in (ROOT / sub).rglob("*.py"):
            if pat.search(p.read_text(errors="ignore")):
                hits.add(str(p.relative_to(ROOT)))
    for top in ("app.py", "api_app.py", "agui_app.py", "api.py", "web_app.py", "main.py"):
        p = ROOT / top
        if p.exists() and pat.search(p.read_text(errors="ignore")):
            hits.add(top)
    hits.discard("engine/brokers/alpaca_live_readonly.py")
    hits.discard("engine/brokers/alpaca.py")  # comment only
    hits.discard("engine/auth.py")  # docstring pointer only
    assert hits <= allowed, hits - allowed


# ---- per-user credential scoping ---------------------------------------------

def test_live_credentials_query_is_scoped_to_session_user(monkeypatch):
    import engine.live_accounts as la
    from engine.auth import encrypt_key
    from cryptography.fernet import Fernet
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    seen = {}

    class Sess:
        def execute(self, sql, params):
            seen["sql"], seen["params"] = str(sql), params
            row = {"account_number": "885504372", "label": "Alpaca live", "read_only": True,
                   "api_key_enc": encrypt_key("AKK"), "secret_key_enc": encrypt_key("SSS")}
            return SimpleNamespace(mappings=lambda: SimpleNamespace(
                first=lambda: row if params["uid"] == "owner" else None))

    @contextmanager
    def get_session():
        yield Sess()
    monkeypatch.setattr(la, "_pool", lambda: SimpleNamespace(get_session=get_session))
    creds = la.get_live_account_credentials("owner")
    assert creds["account_number"] == "885504372" and creds["api_key"] == "AKK"
    assert "user_id = :uid" in seen["sql"] and "read_only" in seen["sql"]
    assert la.get_live_account_credentials("someone-else") is None
    assert la.get_live_account_credentials("") is None


# ---- route + render -----------------------------------------------------------

def _routes():
    reg = {}

    def rt(path, methods=None):
        def deco(fn):
            for m in (methods or ["GET"]):
                reg[(path, m)] = fn
            return fn
        return deco
    ph_live_account.register(None, rt)
    return reg


def test_route_is_get_only_and_requires_login():
    reg = _routes()
    assert list(reg) == [("/live/account", "GET")]
    resp = reg[("/live/account", "GET")](session={})
    assert resp.status_code == 303 and resp.headers["location"] == "/signin"


def test_page_renders_summary_positions_orders_without_controls(monkeypatch):
    monkeypatch.setattr("engine.live_accounts.get_live_account_credentials",
                        lambda uid, account_number=None: {"account_number": "885504372",
                                                          "label": "Alpaca live",
                                                          "api_key": "AKK", "secret_key": "SSS"}
                        if uid == "owner" else None)
    monkeypatch.setattr(ro.LiveReadOnlyClient, "__init__",
                        lambda self, k, s, expected_account_number=None, http=None:
                        (setattr(self, "_headers", {}), setattr(self, "_http", FakeHTTP()),
                         setattr(self, "expected_account_number", expected_account_number))[0])
    monkeypatch.setattr("engine.auth.get_user_by_id", lambda uid: {"user_id": uid,
                                                                  "email": "o@x",
                                                                  "email_verified_at": 1})
    html = to_xml(_routes()[("/live/account", "GET")](session={"user_id": "owner"}))
    assert "885504372" in html and "$10,500.50" in html and "+$100.50" in html
    assert "$1,200.25" in html and "$2,400.50" in html
    assert 'id="live-positions"' in html or "id='live-positions'" in html
    assert "AFRM" in html and "BNBX" in html and "$744.00" in html and "+3.16%" in html
    assert "live-orders" in html and ">sell<" in html and ">day<" in html and ">accepted<" in html
    body = html.split("la-head", 1)[1]
    assert "<form" not in body and "<button" not in body and "hx-post" not in body
    assert "AKK" not in html and "SSS" not in html
    assert 'href="/live"' in html or "href='/live'" in html

    other = to_xml(_routes()[("/live/account", "GET")](session={"user_id": "intruder"}))
    assert "885504372" not in other and "No live broker account is linked" in other


def test_render_error_state_and_notional_orders():
    html = ph_live_account.render({"linked": True, "account_number": "1", "label": "L",
                                   "error": "Alpaca rejected the linked live keys"})
    assert "rejected" in html
    html = ph_live_account.render({"linked": True, "account_number": "1", "label": "L",
                                   "summary": ro.summarize_account(ACCOUNT), "positions": [],
                                   "orders": [{**ORDERS[0], "qty": None, "notional": "250"}]})
    assert "$250.00 notional" in html and "No open positions." in html


def test_sidebar_links_live_account():
    from engine.web.ph_layout import _left_pane
    html = to_xml(_left_pane("live-account", None))
    assert 'href="/live/account"' in html and "Live account" in html


# ---- dev login gating ------------------------------------------------------------

def test_dev_login_not_registered_without_env(monkeypatch):
    monkeypatch.delenv("ALPATRADE_DEV_LOGIN", raising=False)
    reg = {}
    assert ph_devlogin.register(None, lambda *a, **k: (lambda f: reg.setdefault(a, f))) == []
    assert reg == {}


def _req(client, host, fwd=None):
    headers = {"host": host}
    if fwd:
        headers["x-forwarded-for"] = fwd
    return SimpleNamespace(client=SimpleNamespace(host=client), headers=headers)


def test_dev_login_requires_loopback_client_and_local_host():
    assert ph_devlogin.request_is_local(_req("127.0.0.1", "localhost:5099"))
    assert ph_devlogin.request_is_local(_req("::1", "[::1]:5099"))
    assert not ph_devlogin.request_is_local(_req("10.0.1.5", "localhost:5099"))
    assert not ph_devlogin.request_is_local(_req("127.0.0.1", "alpatrade.chat"))
    assert not ph_devlogin.request_is_local(_req("127.0.0.1", "localhost", fwd="1.2.3.4"))
