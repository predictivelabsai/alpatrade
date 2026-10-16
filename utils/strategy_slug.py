"""
Strategy Slug Builder

Generates human-readable slugs that encode strategy + parameters + lookback.
E.g. `btd-3dp-05sl-1tp-1d-1m` = buy_the_dip with 3% dip, 0.5% SL, 1% TP, 1-day hold, 1m lookback.
"""


_PREFIXES = {
    "buy_the_dip": "btd",
    "momentum": "mom",
    "valuation": "val",
    "vix": "vix",
    "box_wedge": "bwg",
}


def _fmt_pct(value: float) -> str:
    """Format a percentage value: whole numbers as-is, fractional drop the dot.

    0.5 → '05', 1.5 → '15', 3.0 → '3', 0.03 (as ratio) → '3'.
    """
    # If value looks like a ratio (< 1 and not 0), convert to percentage
    if 0 < abs(value) < 1:
        value = round(value * 100, 4)
    # Round to avoid floating-point artifacts (e.g. 7.000000000000001)
    value = round(value, 4)
    # Now value is in percentage form
    if value == int(value):
        return str(int(value))
    # Fractional: drop the decimal point  (0.5 → "05", 1.5 → "15")
    return str(value).replace(".", "")


def build_slug(strategy: str, params: dict, lookback: str = "") -> str:
    """Build a human-readable strategy slug.

    Args:
        strategy: Strategy name (e.g. "buy_the_dip").
        params: Strategy parameters dict.
        lookback: Lookback period string (e.g. "1m", "3m").

    Returns:
        Slug string like "btd-3dp-05sl-1tp-1d-1m".
    """
    prefix = _PREFIXES.get(strategy, strategy[:3])
    tokens = [prefix]

    if strategy == "buy_the_dip":
        if "dip_threshold" in params:
            tokens.append(f"{_fmt_pct(params['dip_threshold'])}dp")
        if "stop_loss" in params:
            tokens.append(f"{_fmt_pct(params['stop_loss'])}sl")
        if "take_profit" in params:
            tokens.append(f"{_fmt_pct(params['take_profit'])}tp")
        if "hold_days" in params:
            tokens.append(f"{int(params['hold_days'])}d")
        if int(params.get("min_hold_days") or 0) > 0:
            tokens.append(f"{int(params['min_hold_days'])}min")

    elif strategy == "momentum":
        if "lookback_period" in params:
            tokens.append(f"{int(params['lookback_period'])}lb")
        if "momentum_threshold" in params:
            tokens.append(f"{_fmt_pct(params['momentum_threshold'])}mt")
        if "hold_days" in params:
            tokens.append(f"{int(params['hold_days'])}d")
        if "take_profit" in params:
            tokens.append(f"{_fmt_pct(params['take_profit'])}tp")
        if "stop_loss" in params:
            tokens.append(f"{_fmt_pct(params['stop_loss'])}sl")

    elif strategy == "valuation":
        tokens.extend([
            str(params.get("mode", "low_pe")),
            f"{int(params.get('top_n', 3))}n",
            str(params.get("rebalance", "monthly")),
            # Explicit ratio preserves fractional stop values without ambiguity.
            f"{float(params.get('stop_loss') or 0)}sr",
        ])

    elif strategy == "vix":
        if "vix_threshold" in params:
            tokens.append(f"{_fmt_pct(params['vix_threshold'])}t")
        if "hold_type" in params:
            tokens.append(params["hold_type"])  # e.g. "on" for overnight

    elif strategy == "box_wedge":
        if "risk_pct" in params:
            tokens.append(f"{_fmt_pct(params['risk_pct'])}r")
        if "contraction_threshold" in params:
            tokens.append(f"{_fmt_pct(params['contraction_threshold'])}ct")

    if lookback:
        tokens.append(lookback)

    return "-".join(tokens)


def parse_slug(slug: str) -> dict:
    """Decode a valuation slug to strategy, exact ratio params and lookback.

    Older strategy slugs have no decoder and ambiguous percentage tokens;
    this decoder deliberately accepts only the reversible valuation format.
    """
    import re
    match = re.fullmatch(
        r"val-(low_pe|high_pe|below_median|peg_under_1)-(\d+)n-"
        r"(monthly|quarterly)-(\d+(?:\.\d+)?(?:e[+-]?\d+)?)sr(?:-(\d+[dmyw]))?", slug,
    )
    if not match:
        raise ValueError(f"Invalid valuation slug: {slug}")
    mode, count, frequency, stop, lookback = match.groups()
    if int(count) < 1 or not 0 <= float(stop) < 1:
        raise ValueError(f"Invalid valuation slug: {slug}")
    return {"strategy": "valuation", "params": {
        "mode": mode, "top_n": int(count), "rebalance": frequency,
        "stop_loss": float(stop),
    }, "lookback": lookback or ""}
