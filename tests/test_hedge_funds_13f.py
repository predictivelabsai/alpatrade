"""Unit tests for 13F parsing, CUSIP handling, 13F-implied returns and the screener."""
from datetime import date

import pandas as pd
import pytest

from engine.publicmarkets import hf13f
from engine.publicmarkets.hf13f_perf import (Filing, Position, aggregate_by_ticker, avg_coverage,
                                              daily_returns, long_equity_positions, summarize, window_return)


# ----------------------------------------------------------------- CUSIP handling

def test_normalize_cusip_pads_dropped_leading_zeros_and_strips_noise():
    assert hf13f.normalize_cusip("37833100") == "037833100"
    assert hf13f.normalize_cusip(" 025816-10-9 ") == "025816109"
    assert hf13f.normalize_cusip("g0403h108") == "G0403H108"
    assert hf13f.normalize_cusip("") is None
    assert hf13f.normalize_cusip("123") is None
    assert hf13f.normalize_cusip("1234567890") is None


def test_cusip_check_digit():
    assert hf13f.cusip_check_digit_ok("037833100")      # Apple
    assert hf13f.cusip_check_digit_ok("084670702")      # Berkshire B
    assert not hf13f.cusip_check_digit_ok("037833101")
    assert not hf13f.cusip_check_digit_ok("03783310")


def test_yahoo_ticker_and_figi_pick():
    assert hf13f.yahoo_ticker("BRK/B") == "BRK-B"
    assert hf13f.yahoo_ticker(None) is None
    data = [{"marketSector": "Equity", "securityType": "Equity Option", "ticker": "AAPL 1 C"},
            {"marketSector": "Equity", "securityType": "Common Stock", "ticker": "AAPL"}]
    assert hf13f.pick_figi_match(data)["ticker"] == "AAPL"
    assert hf13f.pick_figi_match([{"marketSector": "Corp", "ticker": "X 5 01/01/30"}]) is None
    assert hf13f.pick_figi_match(None) is None


def test_map_cusips_openfigi_marks_unmapped(monkeypatch):
    class R:
        status_code = 200
        headers = {}

        @staticmethod
        def json():
            return [{"data": [{"marketSector": "Equity", "securityType": "Common Stock", "ticker": "BRK/B",
                               "name": "BERKSHIRE HATHAWAY INC-CL B"}]},
                    {"warning": "No identifier found."}]

    monkeypatch.setattr(hf13f.requests, "post", lambda *a, **k: R())
    monkeypatch.delenv("OPENFIGI_API_KEY", raising=False)
    out = hf13f.map_cusips_openfigi(["084670702", "000000000"], sleep=0)
    assert out["084670702"]["ticker"] == "BRK-B" and out["084670702"]["status"] == "mapped"
    assert out["000000000"] == {"ticker": None, "name": None, "security_type": None, "status": "unmapped"}


# ----------------------------------------------------------------- EDGAR parsing

INFO_XML = b"""<?xml version="1.0"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass>
    <cusip>37833100</cusip><value>2000000</value>
    <shrsOrPrnAmt><sshPrnamt>10000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
  <infoTable><nameOfIssuer>SPDR S&amp;P 500</nameOfIssuer><titleOfClass>PUT</titleOfClass>
    <cusip>78462F103</cusip><value>500000</value><putCall>Put</putCall>
    <shrsOrPrnAmt><sshPrnamt>1000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
  <infoTable><nameOfIssuer>SOME CO NOTE</nameOfIssuer><titleOfClass>NOTE</titleOfClass>
    <cusip>123456AB1</cusip><value>100000</value>
    <shrsOrPrnAmt><sshPrnamt>100000</sshPrnamt><sshPrnamtType>PRN</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
</informationTable>"""


def test_parse_info_table_namespace_agnostic():
    rows = hf13f.parse_info_table(INFO_XML)
    assert [r["cusip"] for r in rows] == ["037833100", "78462F103", "123456AB1"]
    assert rows[0]["value"] == 2000000 and rows[0]["shares"] == 10000 and rows[0]["put_call"] is None
    assert rows[1]["put_call"] == "PUT"
    assert rows[2]["sh_prn_type"] == "PRN"


def test_parse_amendment_type():
    xml = b"""<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler"><formData><coverPage>
      <amendmentInfo><amendmentType>NEW HOLDINGS</amendmentType></amendmentInfo></coverPage></formData>
      </edgarSubmission>"""
    assert hf13f.parse_amendment_type(xml) == "NEW HOLDINGS"


def test_infer_value_multiplier():
    dollars = [{"value": 2_000_000, "shares": 10_000, "sh_prn_type": "SH", "put_call": None}]
    thousands = [{"value": 2_000, "shares": 10_000, "sh_prn_type": "SH", "put_call": None}]
    assert hf13f.infer_value_multiplier(dollars, date(2024, 2, 1)) == 1
    assert hf13f.infer_value_multiplier(thousands, date(2024, 2, 1)) == 1000
    assert hf13f.infer_value_multiplier([], date(2022, 2, 1)) == 1000
    assert hf13f.infer_value_multiplier([], date(2023, 2, 1)) == 1


def test_effective_holdings_applies_amendments():
    orig = {"form_type": "13F-HR", "amendment_type": None, "filing_date": date(2024, 2, 14), "rows": [{"cusip": "A"}]}
    newh = {"form_type": "13F-HR/A", "amendment_type": "NEW HOLDINGS", "filing_date": date(2024, 5, 15),
            "rows": [{"cusip": "B"}]}
    rest = {"form_type": "13F-HR/A", "amendment_type": "RESTATEMENT", "filing_date": date(2024, 3, 1),
            "rows": [{"cusip": "C"}]}
    assert [r["cusip"] for r in hf13f.effective_holdings([orig, newh])] == ["A", "B"]
    assert [r["cusip"] for r in hf13f.effective_holdings([orig, newh], as_of=date(2024, 2, 14))] == ["A"]
    assert [r["cusip"] for r in hf13f.effective_holdings([orig, rest, newh])] == ["C", "B"]
    assert hf13f.effective_holdings([newh]) == []


# ----------------------------------------------------------------- return calculation

def _prices():
    idx = pd.bdate_range("2023-12-25", "2025-01-10")
    n = len(idx)
    spy = pd.Series([100 * (1.0005 ** i) for i in range(n)], index=idx)
    aaa = pd.Series([50.0] * n, index=idx)                   # flat
    bbb = pd.Series([10 * (1.001 ** i) for i in range(n)], index=idx)
    return pd.DataFrame({"SPY": spy, "AAA": aaa, "BBB": bbb})


def test_long_equity_filter_and_aggregation():
    pos = [Position("1", 100, "AAA"), Position("1b", 50, "AAA"), Position("2", 30, "BBB", put_call="CALL"),
           Position("3", 20, None), Position("4", 10, "CCC", sh_prn_type="PRN"), Position("5", 0, "DDD")]
    assert len(long_equity_positions(pos)) == 3
    by, total = aggregate_by_ticker(pos)
    assert by == {"AAA": 150.0} and total == 170.0


def test_single_period_return_is_value_weighted_buy_and_hold():
    prices = _prices()
    f = Filing(date(2023, 12, 29), date(2024, 2, 14), [Position("a", 75, "AAA"), Position("b", 25, "BBB")])
    g = Filing(date(2024, 3, 29), date(2024, 5, 15), [Position("a", 1, "AAA")])
    daily, periods = daily_returns([f, g], prices, "quarter_end")
    p = periods[0]
    s, e = pd.Timestamp(p.start), pd.Timestamp(p.end)
    expected = 0.75 * 0 + 0.25 * (prices.loc[e, "BBB"] / prices.loc[s, "BBB"] - 1)
    assert p.fund_return == pytest.approx(expected)
    assert window_return(daily, s, e) == pytest.approx(expected)
    assert p.coverage == pytest.approx(1.0) and p.n_priced == 2
    assert p.spy_return == pytest.approx(prices.loc[e, "SPY"] / prices.loc[s, "SPY"] - 1)


def test_unpriced_positions_reduce_coverage_and_are_reweighted():
    prices = _prices()
    f = Filing(date(2023, 12, 29), date(2024, 2, 14), [Position("a", 50, "BBB"), Position("x", 50, "ZZZ")])
    _, periods = daily_returns([f], prices, "quarter_end")
    p = periods[0]
    s, e = pd.Timestamp(p.start), pd.Timestamp(p.end)
    assert p.coverage == pytest.approx(0.5)
    assert p.fund_return == pytest.approx(prices.loc[e, "BBB"] / prices.loc[s, "BBB"] - 1)


def test_annual_chaining_matches_single_asset_and_gap_breaks_chain():
    prices = _prices()
    quarters = [date(2023, 12, 29), date(2024, 3, 29), date(2024, 6, 28), date(2024, 9, 30), date(2024, 12, 31)]
    filings = [Filing(q, q, [Position("b", 1, "BBB")]) for q in quarters]
    daily, _ = daily_returns(filings, prices, "quarter_end")
    rows = {r["label"]: r for r in summarize(daily, prices["SPY"], first_year=2024)}
    s, e = pd.Timestamp("2023-12-29"), pd.Timestamp("2024-12-31")
    assert rows["2024"]["fund"] == pytest.approx(prices.loc[e, "BBB"] / prices.loc[s, "BBB"] - 1)
    assert rows["2024"]["spy"] == pytest.approx(prices.loc[e, "SPY"] / prices.loc[s, "SPY"] - 1)
    assert "TTM" in rows and "YTD 2025" in rows
    # Drop the Q2 filing -> a >120-day gap -> 2024 is n/a, SPY still reported.
    gappy = [f for f in filings if f.period_of_report != date(2024, 3, 29)
             and f.period_of_report != date(2024, 6, 28)]
    daily2, _ = daily_returns(gappy, prices, "quarter_end")
    rows2 = {r["label"]: r for r in summarize(daily2, prices["SPY"], first_year=2024)}
    assert rows2["2024"]["fund"] is None and rows2["2024"]["spy"] is not None


def test_follow_filing_enters_after_filing_date():
    prices = _prices()
    f = Filing(date(2023, 12, 29), date(2024, 2, 14), [Position("b", 1, "BBB")])
    _, periods = daily_returns([f], prices, "follow_filing")
    assert periods[0].start == date(2024, 2, 15)
    cov, n = avg_coverage(periods, date(2024, 1, 1), date(2024, 12, 31))
    assert cov == pytest.approx(1.0) and n == 1


def test_delisted_name_keeps_last_price():
    prices = _prices()
    prices.loc[pd.Timestamp("2024-02-01"):, "AAA"] = float("nan")
    prices.loc[pd.Timestamp("2024-01-31"), "AAA"] = 55.0
    f = Filing(date(2023, 12, 29), date(2024, 2, 14), [Position("a", 1, "AAA")])
    g = Filing(date(2024, 3, 29), date(2024, 5, 1), [Position("a", 1, "BBB")])
    _, periods = daily_returns([f, g], prices, "quarter_end")
    assert periods[0].fund_return == pytest.approx(0.10)


# ----------------------------------------------------------------- screener filters

def test_build_screen_sql_filters():
    from engine.publicmarkets.hedge_funds import build_screen_sql, cusip_variants
    sql, params = build_screen_sql(q="berk", min_aum="1b", pos="concentrated", rtype="holdings",
                                   holds_cusips=["037833100", "37833100"], perf_ciks=["0001067983"], sort="filed")
    assert "f.value >= :aum_lo" in sql and params["aum_lo"] == 1e9
    assert "f.positions >= :pos_lo" in sql and params["pos_hi"] == 20
    assert "i.cusip = ANY(:cusips)" in sql and "COALESCE(i.put_call, '') = ''" in sql
    assert "f.cik = ANY(:perf_ciks)" in sql
    assert params["q"] == "%berk%"
    assert params["rtypes"] == ["13F HOLDINGS REPORT", "13F COMBINATION REPORT"]
    assert "ORDER BY f.filing_date DESC" in sql
    sql2, params2 = build_screen_sql(rtype="notice", min_aum="lt100m")
    assert params2["rtypes"] == ["13F NOTICE"] and "COALESCE(f.value, 0) < :aum_hi" in sql2
    assert "WHERE f." not in sql2.split("FROM f")[1] or "aum_hi" in sql2
    assert cusip_variants(["037833100"]) == ["037833100", "37833100"]


def test_screen_returns_empty_when_holds_ticker_unmapped(monkeypatch):
    import engine.publicmarkets.hedge_funds as hf
    monkeypatch.setattr(hf, "performance_by_cik", lambda method="quarter_end": {})
    monkeypatch.setattr(hf, "cusips_for_ticker", lambda t: [])
    res = hf.screen_13f(period="2026-03-31", holds="ZZZZ")
    assert res["rows"] == [] and res["holds_unmapped"] is True


def test_hedge_funds_page_renders_13f_filters_and_performance(monkeypatch):
    from fastcore.xml import to_xml
    import engine.publicmarkets.hedge_funds as hf
    from engine.web import ph_hedgefunds

    monkeypatch.setattr(hf, "activist_filings", lambda **kw: [])
    monkeypatch.setattr(hf, "filing_periods", lambda min_filers=1: [{"period": "2026-03-31", "filers": 10776}])
    monkeypatch.setattr(hf, "screen_13f", lambda **kw: {"rows": [{
        "cik": "0001067983", "name": "Berkshire Hathaway Inc", "period": "2026-03-31", "filed": "2026-05-15",
        "form": "13F-HR", "report_type": "13F HOLDINGS REPORT", "value": 2.6e11, "value_scaled": False,
        "positions": 90, "ttm": {"fund": 0.12, "spy": 0.15}, "last_year": {"fund": 0.1, "label": "2025"}}],
        "holds_unmapped": False})
    monkeypatch.setattr(hf, "performance_rows", lambda method="quarter_end": {
        "labels": ["2025", "YTD 2026", "TTM"], "spy": {"2025": 0.18, "YTD 2026": 0.05, "TTM": 0.15},
        "computed_at": "2026-09-26 09:00",
        "funds": [{"cik": "0001067983", "name": "Berkshire Hathaway", "latest_period": "2026-06-30",
                   "latest_filed": "2026-08-14", "value": 2.6e11, "positions": 90,
                   "returns": {"2025": {"fund": 0.1, "spy": 0.18, "coverage": 0.99},
                               "TTM": {"fund": 0.12, "spy": 0.15, "coverage": 0.98}}}]})
    html = to_xml(ph_hedgefunds._page(None, params=ph_hedgefunds._clean_params(holds="AAPL", perf="1")))
    for name in ("q", "period", "rtype", "min_aum", "pos", "holds", "hsort", "perf", "method"):
        assert f'name="{name}"' in html
    assert "estimated from 13f holdings" in html.lower()
    assert "hf-methodology" in html and "SPY" in html
    assert "+12.0%" in html and "-3.0%" in html        # TTM and TTM vs SPY
    assert "n/a" in html                               # YTD 2026 missing -> n/a
    assert 'name="ticker"' in html                     # activist filters still present


def test_clean_params_rejects_unknown_values():
    from engine.web.ph_hedgefunds import _clean_params
    p = _clean_params(min_aum="evil", pos="x", rtype="drop table", hsort="?", method="z", period="bad")
    assert p["min_aum"] == "" and p["pos"] == "" and p["rtype"] == "holdings"
    assert p["hsort"] == "aum" and p["method"] == "quarter_end" and p["period"] == ""


def test_thousands_candidates_skip_large_average_positions():
    from engine.publicmarkets.hedge_funds import _thousands_candidates
    rows = [("big", 5.7e12, 50651), ("baupost", 5_115_380, 22), ("none", None, 10), ("zero", 1e6, 0)]
    assert _thousands_candidates(rows) == ["baupost"]
