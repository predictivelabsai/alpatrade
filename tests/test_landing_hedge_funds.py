"""Landing: Pricing replaced by a Hedge Funds teaser; /hedge-funds behind sign-in with ?next=."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastcore.xml import to_xml

ROOT = Path(__file__).resolve().parent.parent


def test_home_has_hedge_funds_section_and_no_pricing():
    from engine.web import ph_landing as lp
    html = to_xml(lp.home_page())
    assert "Pricing" not in html and "/pricing" not in html
    assert 'id="hedge-funds"' in html
    assert f'src="{lp.HF_IMG_DESKTOP}"' in html and f'srcset="{lp.HF_IMG_MOBILE}"' in html
    assert 'alt="Screenshot of the AlpaTrade Hedge Funds page' in html
    # "See more" CTA goes to the (sign-in gated) page itself
    assert 'href="/hedge-funds" class="lp-btn primary"><span>See more</span>' in html
    # nav: Hedge Funds sits where Pricing was (between Leaderboard and Developers); footer too
    nav = html[html.index('class="lp-nav-links"'):]
    assert nav.index("Leaderboard") < nav.index("Hedge Funds") < nav.index("Developers")
    assert html.count(f'href="{lp.HEDGE_FUNDS_ANCHOR}"') >= 2
    assert "Free for everyone" in html


def test_snapshot_assets_exist():
    from engine.web import ph_landing as lp
    for src in (lp.HF_IMG_DESKTOP, lp.HF_IMG_MOBILE):
        f = ROOT / src.lstrip("/")
        assert f.is_file() and f.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and f.stat().st_size > 20_000


def test_platform_page_has_no_pricing():
    from engine.web import ph_landing as lp
    html = to_xml(lp.platform_page())
    assert "pricing" not in html.lower()


def test_safe_next_rejects_offsite_targets():
    from engine.web.ph_auth import safe_next
    assert safe_next("/hedge-funds") == "/hedge-funds"
    assert safe_next("/hedge-funds?q=x") == "/hedge-funds?q=x"
    for bad in ("", None, "//evil.com", "/\\evil.com", "https://evil.com", "hedge-funds",
                "/x\r\nSet-Cookie: a=b", 123):
        assert safe_next(bad) == ""


@pytest.fixture
def client(monkeypatch):
    from starlette.testclient import TestClient
    import app as app_module
    from engine.web import ph_auth, ph_hedgefunds
    users = {"u1": {"user_id": "u1", "email": "a@b.c", "email_verified_at": "x"}}
    monkeypatch.setattr(ph_auth, "get_user_by_id", lambda uid: users.get(uid))
    monkeypatch.setattr(ph_auth, "authenticate",
                        lambda e, p: users["u1"] if (e, p) == ("a@b.c", "pw-123456") else None)
    monkeypatch.setattr(ph_hedgefunds, "_user", lambda s: users.get((s or {}).get("user_id")))
    monkeypatch.setattr(ph_hedgefunds, "_page", lambda user, **kw: "HF-PAGE-OK")
    return TestClient(app_module.app)


def test_pricing_redirects_to_hedge_funds_section(client):
    r = client.get("/pricing", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/#hedge-funds"


def test_hedge_funds_requires_sign_in(client):
    r = client.get("/hedge-funds", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/signin?next=/hedge-funds"
    r = client.get("/hedge-funds?q=berk", follow_redirects=False)
    assert r.headers["location"] == "/signin?next=/hedge-funds%3Fq%3Dberk"
    for path in ("/hedge-funds/data", "/hedge-funds/13f.json", "/hedge-funds/performance.json"):
        assert client.get(path).status_code == 401


def test_signin_carries_next_and_lands_on_hedge_funds(client):
    page = client.get("/signin?next=/hedge-funds").text
    assert 'name="next" value="/hedge-funds"' in page
    assert 'href="/register?next=/hedge-funds"' in page
    reg = client.get("/register?next=/hedge-funds").text
    assert 'name="next" value="/hedge-funds"' in reg and 'href="/signin?next=/hedge-funds"' in reg
    # off-site next is dropped
    assert 'name="next"' not in client.get("/signin?next=//evil.com").text
    r = client.post("/signin", data={"email": "a@b.c", "password": "pw-123456",
                                     "next": "/hedge-funds"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/hedge-funds"
    # now signed in: the gated page renders, and /signin?next= bounces straight there
    assert client.get("/hedge-funds").text == "HF-PAGE-OK"
    r = client.get("/signin?next=/hedge-funds", follow_redirects=False)
    assert r.headers["location"] == "/hedge-funds"


def test_signin_without_or_with_bad_next_goes_to_dashboard(client):
    r = client.post("/signin", data={"email": "a@b.c", "password": "pw-123456",
                                     "next": "https://evil.com"}, follow_redirects=False)
    assert r.headers["location"] == "/dashboard"


def test_leaderboard_seed_shows_company_name():
    from engine.leaderboard import seed
    s = seed.SEEDS[0]
    assert s["author_name"] == "Predictive Labs Ltd"
    md = s["file"].read_text(encoding="utf-8")
    assert "Julian Kaljuvee" not in md and "author: Predictive Labs Ltd" in md
