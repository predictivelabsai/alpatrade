"""Referrals: parsing, dedupe/caps, email rendering, Postmark payload, rate limit."""
import base64

from engine import referrals as rf
from engine.web import ph_referrals as pr


def test_parse_emails_dedupes_and_flags_invalid():
    good, bad = rf.parse_emails(["A@x.com, b@y.org", "a@x.com", "nope", ""])
    assert good == ["a@x.com", "b@y.org"] and bad == ["nope"]


def test_plan_caps_and_skips():
    emails = ["me@x.com", "old@x.com", "reg@x.com", "hot@x.com", "n1@x.com", "n2@x.com", "n3@x.com"]
    p = rf.plan_invites(emails, own_email="ME@x.com", already_invited={"old@x.com"}, used=3,
                        registered={"reg@x.com"}, recently_emailed={"hot@x.com"})
    assert p["send"] == ["n1@x.com", "n2@x.com"]
    why = dict(p["skipped"])
    assert why["me@x.com"] == "that's you" and why["old@x.com"] == "already invited"
    assert why["reg@x.com"].startswith("already has") and "24h" in why["hot@x.com"]
    assert "limit" in why["n3@x.com"] and p["remaining_after"] == 0


def test_codes():
    c = rf.new_code()
    assert len(c) == 8 and rf.clean_code(c.lower()) == c
    assert rf.clean_code("x'; drop") == "" and rf.clean_code(None) == ""


def test_render_email_has_link_video_code(monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", "https://alpatrade.chat")
    subj, body, text = rf.render_email(inviter_name="Julian <b>", code="ABCD2345")
    assert "invited you" in subj
    assert "https://alpatrade.chat/register?ref=ABCD2345" in body and "ABCD2345" in text
    assert "https://youtu.be/rfbsMxSUGh4" in body and "img.youtube.com/vi/rfbsMxSUGh4" in body
    assert "&lt;b&gt;" in body and "<b>Julian <b>" not in body  # escaped inviter name


class _R:
    status_code = 200
    text = ""

    def json(self):
        return {"MessageID": "mid-1"}


class _H:
    def __init__(self):
        self.calls = []

    def post(self, url, **kw):
        self.calls.append((url, kw))
        return _R()


def test_send_invite_payload_attaches_pdf(monkeypatch):
    monkeypatch.setenv("POSTMARK_API_KEY", "tok")
    monkeypatch.setenv("FROM_EMAIL", "info@alpatrade.chat")
    h = _H()
    assert rf.send_invite_email("f@x.com", inviter_name="J", code="ABCD2345", http=h) == "mid-1"
    url, kw = h.calls[0]
    p = kw["json"]
    assert url.endswith("/email") and kw["headers"]["X-Postmark-Server-Token"] == "tok"
    assert p["To"] == "f@x.com" and p["Tag"] == "referral-invite"
    att = p["Attachments"][0]
    assert att["ContentType"] == "application/pdf"
    assert base64.b64decode(att["Content"])[:4] == b"%PDF"


def test_send_invite_unconfigured(monkeypatch):
    monkeypatch.delenv("POSTMARK_API_KEY", raising=False)
    assert rf.send_invite_email("f@x.com", inviter_name="J", code="C", http=_H()) is None


def test_rate_limit():
    pr._RATE.clear()
    assert all(pr.rate_ok("u", now=1000 + i) for i in range(3))
    assert not pr.rate_ok("u", now=1010)
    assert pr.rate_ok("u", now=1000 + pr.RATE_WINDOW_S + 5)


def test_invite_page_render_mobile_safe():
    html = pr.render("ABCD2345", "https://alpatrade.chat/register?ref=ABCD2345",
                     [{"email": "a@x.com", "status": "accepted", "sent_at": None}],
                     {"sent": ["b@x.com"], "skipped": [("c@x.com", "already invited")]}, remaining=2)
    assert html.count("name='email'") == 2 and "1 joined" in html and "Skipped c@x.com" in html
