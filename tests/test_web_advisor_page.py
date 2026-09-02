"""The /advisor digest page — rendering, escaping, deep links, graceful edges.

DB-free: the rail query is isolated behind a fake ``DatabasePool`` (same
pattern as ``tests/test_daily_advisor.py``) and the full-report fetch is
monkeypatched on ``engine.reporting.advisor``.
"""
from fastcore.xml import to_xml

from engine.web import ph_advisor
from engine.web.ph_layout import _ICONS, _left_pane


def _record(report_id="report-1", session_date="2026-07-28", **overrides):
    report = {
        "report_id": report_id,
        "user_id": "user-1",
        "account_id": "account-1",
        "session_date": session_date,
        "status": "completed",
        "severity": "review",
        "evidence": {
            "account": {"account_id": "account-1", "account_name": "Paper #1"},
            "broker": {"equity": 100_000.0, "daily_pct": -2.4},
            "paper": {"sharpe": 0.42, "closed_trades": 12},
        },
        "advisory": {
            "headline": "Paper results drifting from backtest",
            "summary": "Paper Sharpe 0.42 vs backtest 1.10 over the same window.",
            "drivers": [
                {"title": "Drift", "detail": "Paper Sharpe is below the drift gate."},
            ],
            "recommendations": [
                {
                    "kind": "backtest",
                    "title": "Retest the refined grid",
                    "explanation": "Re-run the refined grid on the current regime.",
                    "approval_required": True,
                    "proposed_parameters_display": "dip 7% · TP 5% · SL 5%",
                    "test_config": {
                        "strategy": "buy_the_dip",
                        "symbols": ["AAPL", "MSFT"],
                        "lookback": "3m",
                        "variations": {"dip_threshold": [0.05, 0.07]},
                    },
                },
                {
                    "kind": "risk",
                    "title": "Pause new paper entries",
                    "rationale": "Daily loss breached the urgent gate.",
                },
            ],
            "why_no_change": "No stored parameters change until a retest confirms.",
            "data_warnings": ["1 broker fetch was retried."],
            "ai_status": "available",
            "generation_note": "",
            "disclaimer": "Paper trading is simulated; every action requires approval.",
        },
        "narrative": "Paper Sharpe 0.42 vs backtest 1.10 over the same window.",
        "model_provider": "xai",
        "model_name": "grok-4-1-fast-reasoning",
        "error_code": None,
    }
    report.update(overrides)
    return report


def _rail_row(**overrides):
    row = {
        "report_id": "report-1",
        "account_id": "account-1",
        "session_date": "2026-07-28",
        "status": "completed",
        "severity": "review",
    }
    row.update(overrides)
    return row


def test_advisor_route_is_registered():
    import app as app_module

    paths = {r.path for r in app_module.app.routes}
    assert "/advisor" in paths


def test_nav_lists_daily_advisor_in_trade_section():
    page_html = to_xml(_left_pane("advisor", None))
    assert 'href="/advisor"' in page_html
    assert "Daily advisor" in page_html
    assert 'class="page-link active"' in page_html
    # A real icon key must exist so the link does not fall back to the dot.
    assert "advisor" in _ICONS


def test_render_shows_headline_summary_drivers_and_disclaimer():
    html = ph_advisor._render([_rail_row()], [_record()], "2026-07-28")
    assert "Paper results drifting from backtest" in html
    assert "Paper Sharpe 0.42 vs backtest 1.10" in html
    assert "<b>Drift:</b>" in html
    assert "Paper trading is simulated; every action requires approval." in html
    assert "advisor-section review" in html
    assert "session 2026-07-28" in html
    assert "grok-4-1-fast-reasoning" in html


def test_recommendation_cta_is_built_from_test_config():
    html = ph_advisor._render([_rail_row()], [_record()], "2026-07-28")
    assert (
        "href='/app?new=1&amp;autorun=agent%3Abacktest%20strategy%3Abuy_the_dip"
        "%20symbols%3AAAPL%2CMSFT%20lookback%3A3m'" in html
    )
    assert "Test in chat" in html
    assert "explicit approval required" in html


def test_risk_recommendation_gets_no_backtest_cta():
    rec = {
        "kind": "risk",
        "title": "Pause new paper entries",
        "rationale": "Daily loss breached the urgent gate.",
    }
    html = ph_advisor._rec_html(rec)
    assert "Test in chat" not in html
    assert "agent:backtest" not in html


def test_recommendation_without_usable_config_has_no_cta():
    rec = {
        "kind": "backtest",
        "title": "Retest",
        "rationale": " rationale",
        "test_config": {"variations": {"dip_threshold": [0.05]}},
    }
    html = ph_advisor._rec_html(rec)
    assert "Test in chat" not in html


def test_advisory_fields_are_html_escaped():
    report = _record(
        advisory={
            "headline": "<script>alert(1)</script>",
            "summary": "ok",
            "drivers": [{"title": "D", "detail": "<b>bold</b>"}],
            "recommendations": [],
            "why_no_change": "No change <i>now</i>.",
            "data_warnings": ["<img onerror='x'>"],
            "ai_status": "available",
            "generation_note": "",
            "disclaimer": "sim",
        },
        evidence={"account": {"account_name": "<img onerror=alert(1)>"}},
    )
    html = ph_advisor._report_section(report)
    assert "&lt;script&gt;" in html
    assert "<script>" not in html
    assert "&lt;b&gt;bold&lt;/b&gt;" in html
    assert "&lt;img onerror=&#x27;x&#x27;&gt;" in html
    assert "<img onerror" not in html


def test_unknown_report_id_falls_back_to_latest_session(monkeypatch):
    seen = []

    def fake_get(report_id, user_id):
        seen.append((report_id, user_id))
        return _record(report_id=report_id) if report_id == "report-9" else None

    monkeypatch.setattr(ph_advisor, "_report", fake_get)
    rail = [_rail_row(report_id="report-9", session_date="2026-07-29"),
            _rail_row(report_id="report-1", session_date="2026-07-28")]
    reports, selected = ph_advisor._resolve(rail, "foreign-report", "", "user-1")
    # Foreign ?report= fell through, then ?date= empty → latest session.
    assert [r["report_id"] for r in reports] == ["report-9"]
    assert selected == "2026-07-29"
    assert seen[0] == ("foreign-report", "user-1")


def test_date_query_selects_that_session(monkeypatch):
    monkeypatch.setattr(
        ph_advisor, "_report", lambda rid, uid: _record(report_id=rid))
    rail = [_rail_row(report_id="r2", session_date="2026-07-29"),
            _rail_row(report_id="r1", session_date="2026-07-28")]
    reports, selected = ph_advisor._resolve(rail, "", "2026-07-28", "user-1")
    assert [r["report_id"] for r in reports] == ["r1"]
    assert selected == "2026-07-28"


def test_garbage_date_falls_back_to_latest(monkeypatch):
    monkeypatch.setattr(
        ph_advisor, "_report", lambda rid, uid: _record(report_id=rid))
    rail = [_rail_row(session_date="2026-07-29")]
    reports, selected = ph_advisor._resolve(rail, "", "not-a-date", "user-1")
    assert selected == "2026-07-29"
    assert len(reports) == 1


def test_generating_report_shows_progress_note_without_advisory_sections():
    report = _record(status="generating", advisory={})
    html = ph_advisor._report_section(report)
    assert "still generating" in html
    assert "Performance drivers" not in html
    assert "Recommended next step" not in html


def test_failed_report_surfaces_the_error_code():
    report = _record(status="failed", error_code="model_unavailable")
    html = ph_advisor._report_section(report)
    assert "Report failed" in html
    assert "model_unavailable" in html


def test_empty_rail_renders_the_empty_state():
    html = ph_advisor._render([], [], None)
    assert "No post-close daily advisor report" in html
    assert "advisor-grid" not in html


class _BrokenPool:
    """Pool whose get_session raises — the page must degrade, not 500."""

    @staticmethod
    def get_session():
        raise RuntimeError("db down")


def test_rail_returns_empty_list_when_db_is_down(monkeypatch):
    import engine.db.pool as pool_module

    monkeypatch.setattr(pool_module, "DatabasePool", lambda: _BrokenPool())
    assert ph_advisor._rail("user-1") == []


def test_dashboard_advisor_card_links_to_the_digest_page():
    from engine.web.ph_pnl import _advisor_cards

    card = _advisor_cards({"advisor_reports": [_record()]})
    assert "/advisor?report=report-1" in card
    empty = _advisor_cards({"advisor_reports": []})
    assert "href='/advisor'" in empty