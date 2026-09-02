"""Strategy presets — curated one-click ``agent:backtest`` starting configs.

Validates every preset against the real command surface: the tokens the
presets carry must be exactly what ``CommandProcessor._parse_kv_params`` and
``_agent_backtest`` understand, so a preset can never silently no-op or run
with dropped params. Also covers the ``/backtests`` preset strip rendering.
"""
import pytest

from engine.web import onboarding

# Tokens _agent_backtest consumes (tui/command_processor.py); anything else
# in a preset command would be silently ignored by the dispatcher.
_VALID_KEYS = {"strategy", "symbols", "lookback", "capital", "hours",
               "intraday_exit", "pdt", "_positional"}
_VALID_STRATEGIES = {"buy_the_dip", "momentum", "vix", "box_wedge"}
_TICKER_TOKENS = {"strategy", "symbols", "lookback", "capital", "hours",
                  "intraday_exit", "pdt"}  # keys whose value is never a ticker


def _parse(tail: str) -> dict:
    """Mirror CommandProcessor._parse_kv_params (kept in sync by test below).
    ``tail`` is everything AFTER ``agent:backtest``."""
    params = {}
    positional = []
    for part in tail.split():
        if ":" in part:
            key, value = part.split(":", 1)
            params[key.lower()] = value
        else:
            positional.append(part)
    if positional:
        params["_positional"] = " ".join(positional)
    return params


def test_every_preset_parses_with_known_keys():
    for preset in onboarding.STRATEGY_PRESETS:
        command = preset["command"]
        assert command.startswith("agent:backtest "), preset["name"]
        parsed = _parse(command.removeprefix("agent:backtest").strip())
        unknown = set(parsed) - _VALID_KEYS
        assert not unknown, (preset["name"], unknown)


def test_every_preset_has_strategy_symbols_lookback():
    for preset in onboarding.STRATEGY_PRESETS:
        parsed = _parse(preset["command"].removeprefix("agent:backtest").strip())
        assert parsed["strategy"] in _VALID_STRATEGIES, preset["name"]
        symbols = parsed["symbols"].split(",")
        assert 1 <= len(symbols) <= 10, preset["name"]
        assert all(s.isupper() and s.isalpha() for s in symbols), preset["name"]
        assert parsed["lookback"].endswith(("m", "w", "y")), preset["name"]


def test_parse_kv_params_matches_command_processor():
    """Keep this module's mini-parser honest against the real dispatcher."""
    from tui.command_processor import CommandProcessor

    sample = onboarding.STRATEGY_PRESETS[0]["command"]
    parts = sample.strip().split()
    expected = CommandProcessor._parse_kv_params(None, parts[1:])
    assert _parse(" ".join(parts[1:])) == expected


def test_preset_covers_all_four_strategies():
    strategies = {p["strategy"] for p in onboarding.STRATEGY_PRESETS}
    assert strategies == _VALID_STRATEGIES


def test_preset_names_unique_and_labeled():
    names = [p["name"] for p in onboarding.STRATEGY_PRESETS]
    assert len(names) == len(set(names))
    for preset in onboarding.STRATEGY_PRESETS:
        assert preset["name"] and preset["blurb"]


def test_preset_url_wraps_autorun():
    url = onboarding.preset_url(onboarding.STRATEGY_PRESETS[0])
    assert url.startswith("/app?new=1&autorun=agent%3Abacktest")


def test_backtests_page_renders_presets_strip():
    from engine.web.ph_runs import _render

    html = _render("backtest", [])
    assert "Start from a preset" in html
    assert "Dip · mega-cap tech" in html
    for preset in onboarding.STRATEGY_PRESETS:
        assert onboarding.preset_url(preset) in html


def test_backtests_page_with_rows_also_shows_presets():
    from engine.web.ph_runs import _render

    row = {"run_id": "0f0e1d2c-3b4a-5968-7789-aabbccddeeff",
           "strategy": "buy_the_dip", "strategy_slug": "btd-x", "status": "ok",
           "started_at": "2026-08-16T08:30:00", "params": {},
           "total_return": 1.0, "sharpe_ratio": 1.0}
    html = _render("backtest", [row])
    assert "Start from a preset" in html


def test_paper_page_has_no_presets_strip():
    from engine.web.ph_runs import _render

    assert "Start from a preset" not in _render("paper", [])


@pytest.mark.parametrize("bad", [None, {}, {"command": ""}, {"name": "x"}])
def test_preset_strip_tolerates_malformed_entries(bad):
    from engine.web import ph_runs

    original = onboarding.STRATEGY_PRESETS
    try:
        onboarding.STRATEGY_PRESETS = (bad,) if bad is not None else ()
        ph_runs._presets_strip()  # must not raise
    finally:
        onboarding.STRATEGY_PRESETS = original