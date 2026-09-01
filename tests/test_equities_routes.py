"""Equities vertical wiring: routes register, guards redirect to /signin, and
the dashboard renders from the viewer's own linked keys (connect-card when
none). No DB or live broker needed."""

from unittest import mock

from fastcore.xml import to_xml

from verticals.equities import routes

FAKE_USER = {"user_id": "u-123", "email": "user@example.com"}


def _collect_routes(current_user):
    """Run register() against fakes and return {(path, method): view_fn}."""
    registered = {}

    def rt(path, methods=None):
        def deco(fn):
            registered[(path, methods[0] if methods else "GET")] = fn
            return fn
        return deco

    class FakeApp:
        def post(self, path):
            def deco(fn):
                registered[(path, "POST")] = fn
                return fn
            return deco

    routes.register(FakeApp(), rt, current_user)
    return registered


def _patch_data_sources(monkeypatch, keys=None):
    """Keep the views DB/broker-free: fake keys, broker, and report agent."""
    monkeypatch.setattr("engine.auth.get_alpaca_keys", lambda uid: keys)
    runs = ([{"run_id": "r-1", "mode": "backtest", "strategy_slug": "btd",
              "status": "done", "total_return": 1.5, "total_trades": 4}], None)
    monkeypatch.setattr(routes, "_recent_runs", lambda limit=12: runs)


def test_routes_registered_under_equities_prefix():
    registered = _collect_routes(lambda session: None)
    for path in ("/equities", "/equities/backtest", "/equities/runs",
                 "/equities/assistant"):
        assert (path, "GET") in registered or (path, "POST") in registered
    assert ("/equities/backtest", "GET") in registered
    assert ("/equities/backtest", "POST") in registered


def test_guards_redirect_to_signin():
    registered = _collect_routes(lambda session: None)
    for path in ("/equities", "/equities/backtest", "/equities/runs"):
        resp = registered[(path, "GET")](session={})
        assert resp.status_code == 303
        assert resp.headers["location"] == "/signin"


def test_dashboard_renders_connect_card_without_keys(monkeypatch):
    _patch_data_sources(monkeypatch, keys=None)
    registered = _collect_routes(lambda session: FAKE_USER)
    html = to_xml(registered[("/equities", "GET")](session={}))

    assert "Connect your Alpaca keys" in html
    assert 'href="/settings"' in html
    assert "Equities — Dashboard" in html


def test_dashboard_renders_kpis_with_linked_keys(monkeypatch):
    _patch_data_sources(monkeypatch, keys=("k", "s"))
    account = {"equity": "100000", "cash": "25000", "buying_power": "50000"}
    api = mock.MagicMock()
    api.get_account.return_value = account
    api.get_positions.return_value = []
    monkeypatch.setattr("engine.brokers.alpaca.AlpacaAPI",
                        lambda **kwargs: api)

    registered = _collect_routes(lambda session: FAKE_USER)
    html = to_xml(registered[("/equities", "GET")](session={}))

    assert "$100,000" in html
    assert "Open positions" in html
    assert "Connect your Alpaca keys" not in html


def test_backtest_form_renders(monkeypatch):
    _patch_data_sources(monkeypatch, keys=None)
    registered = _collect_routes(lambda session: FAKE_USER)
    html = to_xml(registered[("/equities/backtest", "GET")](session={}))

    assert "Run backtest" in html
    assert 'action="/equities/backtest"' in html