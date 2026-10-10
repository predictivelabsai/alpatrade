from pathlib import Path

from fasthtml.common import to_xml

from engine.web.ph_landing import BROKERS, developers_page, home_page

ROOT = Path(__file__).resolve().parents[1]


def test_home_has_broker_row_not_stats_or_cli():
    h = to_xml(home_page())
    assert "Works with" in h
    for old in ("5-agent", "strategies built-in", "live paper trading", "dated backtest artifacts",
                "btd-7dp-05sl-1tp-1d-3m", "42 trades"):
        assert old not in h, old
    assert [b[0] for b in BROKERS] == ["LHV", "Alpaca", "Interactive Brokers", "Saxo Bank", "moomoo"]
    for name, site, logo in BROKERS:
        assert f'href="{site}"' in h and f'src="{logo}"' in h and f'alt="{name} logo"' in h
        assert logo.startswith("/static/brokers/")  # vendored, not hotlinked
        assert (ROOT / logo.lstrip("/")).is_file(), logo


def test_developers_has_cli_section_labelled_example():
    h = to_xml(developers_page())
    assert 'id="cli"' in h
    assert "alpatrade backtest paper btd-7dp-05sl-1tp-1d-3m" in h
    assert "42 trades · win-rate 61% · Sharpe 1.34 · max DD -6.2%" in h
    assert "Example output" in h and "not a live result" in h
    assert "Command name format" in h and "The artifacts folder" in h
    assert "summary.json" in h and "trades.csv" in h
