"""DB-free contracts for the Postmark email helpers.

Guards the regression where send_email_to had no body after the env check and
returned None — which silently sent no daily PnL email and crashed the report's
`all_ok &= ok` aggregation.
"""
from types import SimpleNamespace

import utils.email_util as email_util


class _FakeResp:
    def __init__(self, status=200):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_send_email_to_posts_to_postmark_and_returns_true(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, headers=headers, json=json)
        return _FakeResp(200)

    monkeypatch.setenv("POSTMARK_API_KEY", "tok")
    monkeypatch.setenv("FROM_EMAIL", "reports@example.com")
    monkeypatch.setattr(email_util.requests, "post", fake_post)

    ok = email_util.send_email_to("jk@example.eu", "Subj", "<b>hi</b>")

    assert ok is True  # never None — main() does `all_ok &= ok`
    assert captured["url"] == "https://api.postmarkapp.com/email"
    assert captured["json"]["To"] == "jk@example.eu"
    assert captured["json"]["From"] == "reports@example.com"
    assert captured["json"]["Subject"] == "Subj"
    assert captured["headers"]["X-Postmark-Server-Token"] == "tok"


def test_send_email_to_returns_false_when_unconfigured(monkeypatch):
    monkeypatch.delenv("POSTMARK_API_KEY", raising=False)
    monkeypatch.delenv("FROM_EMAIL", raising=False)
    assert email_util.send_email_to("x@example.eu", "s", "b") is False


def test_send_email_to_returns_false_on_transport_error(monkeypatch):
    monkeypatch.setenv("POSTMARK_API_KEY", "tok")
    monkeypatch.setenv("FROM_EMAIL", "reports@example.com")

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(email_util.requests, "post", boom)
    assert email_util.send_email_to("x@example.eu", "s", "b") is False


def test_send_email_to_return_type_is_boolean(monkeypatch):
    """`&=` in the report aggregator requires a real bool, never None."""
    monkeypatch.setenv("POSTMARK_API_KEY", "tok")
    monkeypatch.setenv("FROM_EMAIL", "reports@example.com")
    monkeypatch.setattr(email_util.requests, "post",
                        lambda *a, **k: _FakeResp(200))
    result = email_util.send_email_to("x@example.eu", "s", "b")
    assert isinstance(result, bool)
