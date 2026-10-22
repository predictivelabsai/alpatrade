"""v0.49.0 risk overlays: regime filter (live helper, default off) + backtest overlay params."""
import sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.live_btd_runner import regime_block  # noqa: E402
from btd_fixtures import DEFAULT_PARAMS  # noqa: E402
from utils.live_btd_config import coerce_params  # noqa: E402

MON = date(2026, 10, 19)


def bars(lows, start=9):
    return [{"t": f"2026-10-{start + i:02d}T04:00:00Z", "l": l} for i, l in enumerate(lows)]


def test_regime_filter_off_by_default_and_coerced():
    assert DEFAULT_PARAMS["regime_filter"] == ""
    assert coerce_params({"regime_filter": "SPY,SMH"})["regime_filter"] == "SPY,SMH"


def test_regime_blocks_below_prior_5_day_low_only():
    b = {"SPY": bars([600, 601, 602, 603, 604]), "SMH": bars([300, 301, 302, 303, 304])}
    assert regime_block(b, {"SPY": 650, "SMH": 310}, MON) is None
    assert "SMH" in regime_block(b, {"SPY": 650, "SMH": 299.9}, MON)
    b["SPY"].append({"t": "2026-10-19T04:00:00Z", "l": 1})        # today's partial bar is ignored
    assert regime_block(b, {"SPY": 650, "SMH": 310}, MON) is None


def test_regime_fails_closed_without_data():
    assert "fail closed" in regime_block({"SPY": bars([1, 2])}, {"SPY": 10}, MON)
