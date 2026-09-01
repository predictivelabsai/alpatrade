"""Shareable report pages (``/r/{id}``) — pure-layer tests, no DB/network.

Covers id dispatch (uuid vs folder slug), traversal/containment safety, the
two metric-unit conventions (DB percent vs folder ratio), the verbatim
double disclosure, the no-identity guarantee, and markdown payload
neutralization.
"""
import json

import pytest

from engine.backtest.artifacts import DISCLOSURE
from engine.web import ph_reports
from engine.web.onboarding import format_params

UUID = "0f0e1d2c-3b4a-5968-7789-aabbccddeeff"
SLUG = "2026-08-16_AAPL_buy_the_dip_1d"

# Real summary.json shape (from backtest-results/<slug>/summary.json).
_SUMMARY = {
    "strategy_name": "buy_the_dip",
    "start": "2024-01-01T00:00:00",
    "end": "2024-06-30T00:00:00",
    "symbols": ["AAPL"],
    "timeframe": "1d",
    "initial_cash": 10000.0,
    "reproducible_core": {
        "metrics": {
            "total_return": 0.0124,
            "annualized_return": 0.0253,
            "sharpe": 1.29,
            "max_drawdown": -0.0119,
            "final_equity": 10123.88,
            "trading_days": 124,
        },
        "round_trip": {"trades": 23, "win_rate": 0.4348},
    },
    "assumptions": ["fill_model=next_open", "feed=iex"],
}

_DB_PAYLOAD = {
    "run_id": UUID,
    "strategy": "buy_the_dip",
    "strategy_slug": "btd-5dp-05sl-1tp-2d-3m",
    "status": "completed",
    "config": {"symbols": ["AAPL"], "lookback": "3m"},
    "params": {"dip_threshold": 0.05, "take_profit": 0.01,
               "stop_loss": 0.005, "hold_days": 3},
    "metrics": {"total_return": 9.1, "sharpe_ratio": 1.42,
                "max_drawdown": -4.8, "win_rate": 55.2, "total_trades": 31},
    "trades": [{"symbol": "AAPL", "direction": "long", "shares": 10,
                "entry_price": 183.99, "exit_price": 179.72, "pnl": -21.38,
                "entry_time": "2024-02-01T05:00:00"}],
}


# ---------------------------------------------------------------------------
# id dispatch + validation
# ---------------------------------------------------------------------------

def test_uuid_and_slug_dispatch():
    assert ph_reports.is_run_uuid(UUID)
    assert not ph_reports.is_folder_slug(UUID)  # uuid wins the dispatch
    assert ph_reports.is_folder_slug(SLUG)
    assert not ph_reports.is_run_uuid(SLUG)


@pytest.mark.parametrize("rid", ["..", "../etc", "a/b", "a\\b", ".git", "",
                                  "a" * 200, "2026-08-16_AAPL_..__1d"])
def test_slug_validation_rejects_bad_ids(rid):
    assert not ph_reports.is_folder_slug(rid)
    assert not ph_reports.is_run_uuid(rid)


# ---------------------------------------------------------------------------
# Folder path — containment + summary extraction
# ---------------------------------------------------------------------------

def _make_folder(tmp_path, summary=_SUMMARY, md="# Report\n\nAll good."):
    folder = tmp_path / SLUG
    folder.mkdir()
    (folder / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (folder / "report.md").write_text(md, encoding="utf-8")
    return folder


def test_folder_containment_check(tmp_path):
    _make_folder(tmp_path)
    assert ph_reports._load_folder_report(SLUG, tmp_path) is not None
    # A sibling directory is not itself a child of root → rejected.
    assert ph_reports._load_folder_report("../escape", tmp_path) is None
    assert ph_reports._load_folder_report("nested/" + SLUG, tmp_path) is None


def test_folder_report_extracts_summary_cards(tmp_path):
    _make_folder(tmp_path)
    payload = ph_reports._load_folder_report(SLUG, tmp_path)
    html = ph_reports.folder_report_html(payload)
    assert "1.2%" in html          # ratio 0.0124 scaled to percent
    assert "43.5%" in html         # win_rate ratio scaled
    assert "buy_the_dip" in html
    assert "fill_model=next_open" in html
    assert "rpt-md" in html        # markdown payload embedded


def test_folder_report_missing_folder_is_none(tmp_path):
    assert ph_reports._load_folder_report("2026-08-16_NOPE_buy_the_dip_1d",
                                          tmp_path) is None


def test_folder_report_oversized_summary_skipped(tmp_path, monkeypatch):
    _make_folder(tmp_path)
    monkeypatch.setattr(ph_reports, "_MAX_FILE_BYTES", 10)
    assert ph_reports._load_folder_report(SLUG, tmp_path) is None


def test_report_md_script_payload_neutralized(tmp_path):
    hostile = "# Report\n\n</script><script>alert(1)</script>javascript:evil()"
    _make_folder(tmp_path, md=hostile)
    payload = ph_reports._load_folder_report(SLUG, tmp_path)
    html = ph_reports.folder_report_html(payload)
    # The closing script sequence is broken so the data block survives intact.
    assert "</script>alert" not in html
    assert "javascript:" not in html


# ---------------------------------------------------------------------------
# DB path — pure render of the payload dict
# ---------------------------------------------------------------------------

def test_db_report_renders_metric_cards():
    html = ph_reports.db_report_html(_DB_PAYLOAD)
    assert "Total return" in html and "+9.1%" in html
    assert "Sharpe" in html and "1.42" in html
    assert "Max drawdown" in html and "-4.8%" in html
    assert "Win rate" in html and "55.2%" in html   # DB win_rate already percent
    assert "Trades" in html and "31" in html


def test_db_report_renders_params_via_shared_formatter():
    assert format_params({"dip_threshold": 0.05, "hold_days": 3}) == \
        "dip 5% · hold 3d"
    html = ph_reports.db_report_html(_DB_PAYLOAD)
    assert "dip 5%" in html and "hold 3d" in html


def test_db_report_orchestrator_shape_supported():
    """runs.results best_config shape (no summaries row) still renders."""
    payload = dict(_DB_PAYLOAD)
    payload["metrics"] = {
        "strategy": "buy_the_dip", "params": {"dip_threshold": 0.05},
        "total_return": 4.2, "win_rate": 51.0, "max_drawdown": -2.0,
        "total_trades": 12}
    html = ph_reports.db_report_html(payload)
    assert "+4.2%" in html and "Trades" in html


def test_db_report_null_safe():
    html = ph_reports.db_report_html({"run_id": UUID, "metrics": {},
                                      "params": {}, "trades": [{}]})
    assert "Backtest report" in html or "report" in html.lower()


# ---------------------------------------------------------------------------
# Framing: disclosure, identity, 404
# ---------------------------------------------------------------------------

def test_disclosure_appears_verbatim_twice():
    marker = "hypothetical historical simulation and does not represent actual"
    for html in (ph_reports.db_report_html(_DB_PAYLOAD),
                 ph_reports.folder_report_html(
                     {"summary": _SUMMARY, "report_md": "# x"})):
        assert marker in html
        assert html.count(marker) == 2


def test_no_user_identity_in_html():
    payload = dict(_DB_PAYLOAD)
    payload["params"] = dict(_DB_PAYLOAD["params"], user_id=UUID,
                             email="owner@example.com")
    payload["config"] = {"symbols": ["AAPL"], "user_id": UUID}
    html = ph_reports.db_report_html(payload)
    assert "user@example.com" not in html
    assert "user_id" not in html
    assert "email" not in html


def test_not_found_page_is_404():
    resp = ph_reports._not_found("whatever")
    assert resp.status_code == 404
    body = resp.body.decode("utf-8")
    assert "does not exist" in body
    assert "user@example.com" not in body