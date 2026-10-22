"""Test fixtures: the rule values seeded by sql/57_rules_db_only.sql (== the pre-v0.55 code
fallbacks). Tests only; production code has no rule defaults (rules are DB-only)."""
from typing import Any, Dict

DEFAULT_PARAMS: Dict[str, Any] = {
    "symbols": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA"],
    "dip": 3.0, "tp": 8.0, "sl": 1.5, "min_hold": 3, "max_hold": 3,
    "pos_frac": 0.10, "max_exposure": 0.0, "ref": "high20", "feed": "iex",
    "entry_window": "15-5", "close_window": "15-2",
    # v0.49.0 risk overlay, OFF by default: "SPY,SMH" = no new dip buys while any of these trades
    # below its prior 5-session low (scripts/btd_risk_overlay_wf.py; enable via live_btd_config set)
    "regime_filter": "",
    # v0.51.0 user-editable rule keys (utils/btd_rules.PARAM_SPEC); these defaults = old behaviour
    "stop_mode": "pct", "stop_k": 2.0, "tp_mult": 0.0, "stop_timing": "always",
    "vol_filter": "off", "vol_max": 4.0, "regime_mode": "low5", "regime_sma": 200, "max_exposure_pct": 0.0,
    "session_mode": "regular", "stop_exempt": {},
}

DEFAULT_EXECUTION: Dict[str, Any] = {
    "regular_hours_exit": {"order_type": "market", "time_in_force": "day"},
    "extended_hours_exit": {"enabled": False, "order_type": "limit", "limit_ref": "bid",
                            "discount_bps": 15, "reprice_after_min": 5, "max_reprices": 2,
                            "fallback": "market_day_at_regular_open", "max_spread_bps": 50},
}


# sql/57 per-user fill-ins (former utils/user_live_runner.NEUTRAL)
USER_SEED: Dict[str, Any] = {"min_hold": 0, "max_exposure": 0.0, "ref": "high20", "feed": "iex", "entry_window": "15-5",
                             "close_window": "15-2", "regime_filter": "", "stop_mode": "pct", "stop_k": 2.0,
                             "tp_mult": 0.0, "stop_timing": "always", "vol_filter": "off", "vol_max": 4.0,
                             "regime_mode": "low5", "regime_sma": 200, "max_exposure_pct": 0.0,
                             "session_mode": "regular", "stop_exempt": {}}
