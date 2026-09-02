"""Per-strategy paper-trading parameter schema — single source of truth.

The deploy-to-paper path spans four layers (web CTA → ``agent:paper`` command →
orchestrator → ``PaperTradeAgent``) and historically hard-coded buy-the-dip
param names at every hop, with three coexisting unit conventions (backtest
stores ratios, command strings use percents, VIX uses points). This module
owns the schema so every layer agrees:

* :data:`PARAM_SCHEMA` — the params each strategy accepts, with a ``kind``.
* :func:`resolve_paper_params` — precedence: explicit params > yaml section >
  schema defaults, translating ratios to percents for ``kind == "percent"``
  only (same rule as ``utils.strategy_slug._fmt_pct``: ``0 < |v| < 1`` → ×100).
  ``points`` (VIX level), ``ratio`` (contraction threshold) and ``days`` keys
  are never translated.
* :func:`strategy_command` — render a user-runnable ``agent:paper`` command.
* :func:`parse_command_params` — coerce flat command tokens into typed params.
* :func:`slug_params` — map resolved params onto ``build_slug``'s expectations.

Percent-kind values here are in percent units (5.0 = 5%); the DB backtest
storage keeps the ratio convention (0.05) and translation happens at the edges.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

STRATEGY_ALIASES = {
    "btd": "buy_the_dip",
    "mom": "momentum",
    "vix": "vix",
    "bwg": "box_wedge",
}

STRATEGY_NAMES = ("buy_the_dip", "momentum", "vix", "box_wedge")


@dataclass(frozen=True)
class PaperParam:
    """One paper-trading parameter for a strategy.

    kind controls parsing and ratio→percent translation:
    percent (5.0 = 5%, ratios auto-scaled), points (raw index level, never
    scaled), ratio (0-1, never scaled), days, dollars, fraction (0-1 of
    equity), bool.
    """

    key: str
    kind: str
    default: Any = None
    required: bool = True


PARAM_SCHEMA: Dict[str, List[PaperParam]] = {
    "buy_the_dip": [
        PaperParam("dip_threshold", "percent", 5.0),
        PaperParam("take_profit_threshold", "percent", 1.0),
        PaperParam("stop_loss_threshold", "percent", 0.5),
        PaperParam("hold_days", "days", 2),
        PaperParam("min_hold_days", "days", 0),
        PaperParam("capital_per_trade", "dollars", 1000.0),
        PaperParam("position_size", "fraction", None, required=False),
    ],
    "momentum": [
        PaperParam("momentum_threshold", "percent", 5.0),
        PaperParam("lookback_period", "days", 20),
        PaperParam("take_profit_threshold", "percent", 10.0),
        PaperParam("stop_loss_threshold", "percent", 5.0),
        PaperParam("hold_days", "days", 5),
        PaperParam("capital_per_trade", "dollars", 1000.0),
    ],
    "vix": [
        PaperParam("vix_threshold", "points", 20.0),
        PaperParam("hold_overnight", "bool", True),
        PaperParam("position_size", "fraction", None, required=False),
        PaperParam("capital_per_trade", "dollars", 1000.0),
    ],
    "box_wedge": [
        PaperParam("risk_per_trade_pct", "percent", 1.0),
        PaperParam("contraction_threshold", "ratio", 0.7),
        PaperParam("box_lookback", "days", 100),
        PaperParam("wedge_lookback", "days", 20),
        PaperParam("scale_out_1_5r_pct", "percent", 50.0),
        PaperParam("scale_out_3r_pct", "percent", 25.0),
        PaperParam("capital_per_trade", "dollars", 1000.0),
    ],
}


def canonical_strategy(name: str) -> Optional[str]:
    """Map a strategy name or slug prefix to its canonical name (None if unknown)."""
    raw = str(name or "").strip().lower()
    return STRATEGY_ALIASES.get(raw, raw or None)


def ratio_to_percent(value: Any) -> Any:
    """Backtest params store ratios (0.05 = 5%); the paper path wants percent.

    Same convention as ``utils.strategy_slug._fmt_pct``: anything in (0,1)
    is treated as a ratio and scaled by 100.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return value
    if 0 < abs(v) < 1:
        return round(v * 100, 6)
    return v


# Backtest storage uses legacy key names for some params; normalize to schema keys.
_STORAGE_KEY_ALIASES = {
    "take_profit": "take_profit_threshold",
    "stop_loss": "stop_loss_threshold",
    "risk_pct": "risk_per_trade_pct",
}


def storage_params(strategy: str, params: Optional[dict]) -> Dict[str, Any]:
    """DB best-config params (backtest storage convention) → schema-keyed params.

    Renames legacy keys (``take_profit`` → ``take_profit_threshold``,
    ``risk_pct`` → ``risk_per_trade_pct``) and converts the vix ``hold_type``
    token (``on``/``eod``) into the boolean ``hold_overnight``. Values are
    left untouched — :func:`resolve_paper_params` owns ratio→percent.
    """
    strategy = canonical_strategy(strategy)
    known = {p.key for p in PARAM_SCHEMA.get(strategy, [])}
    out: Dict[str, Any] = {}
    if not isinstance(params, dict):
        return out
    for key, value in params.items():
        key = _STORAGE_KEY_ALIASES.get(key, key)
        if key == "hold_type":
            out["hold_overnight"] = str(value).strip().lower() != "eod"
        elif key in known:
            out[key] = value
    return out


def _coerce(value: Any, kind: str) -> Any:
    """Coerce a raw (often string) token into the param's python type."""
    if kind == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() not in ("false", "no", "0", "off")
    if isinstance(value, str):
        value = value.strip()
    try:
        num = float(value)
    except (TypeError, ValueError):
        return value
    if kind in ("days",):
        return int(num)
    return num


def resolve_paper_params(strategy: str, params: Optional[dict],
                         yaml_params: Optional[dict],
                         translate: bool = True) -> Dict[str, Any]:
    """Effective paper params for ``strategy``.

    Precedence: explicit ``params`` > the strategy's ``parameters.yaml``
    section > schema defaults. Only *explicit* percent-kind values are
    normalized to percent units (a stored ratio 0.05 becomes 5.0) — the
    orchestrator's merged dict is in DB best-config ratio space, while
    ``parameters.yaml`` sections and schema defaults are already percent-unit
    (agent-facing) and must pass through unscaled, as must everything when
    ``translate`` is False (``PaperTradeAgent`` receives percent-unit params;
    re-translating would turn a 0.5% stop_loss into 50%). All other kinds
    pass through unscaled so VIX points and dimensionless ratios survive.
    """
    strategy = canonical_strategy(strategy)
    schema = PARAM_SCHEMA.get(strategy, [])
    yaml_cfg = (yaml_params or {}).get(strategy, {}) if strategy else {}
    out: Dict[str, Any] = {}
    for spec in schema:
        value = None
        explicit = isinstance(params, dict) and params.get(spec.key) is not None
        if explicit:
            value = params.get(spec.key)
        elif isinstance(yaml_cfg, dict) and yaml_cfg.get(spec.key) is not None:
            value = yaml_cfg.get(spec.key)
        elif spec.default is not None or not spec.required:
            value = spec.default
        if value is None:
            out[spec.key] = None
            continue
        value = _coerce(value, spec.kind)
        if translate and explicit and spec.kind == "percent":
            value = ratio_to_percent(value)
        out[spec.key] = value
    return out


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


def strategy_command(strategy: str, params: dict,
                     symbols: Optional[List[str]] = None) -> str:
    """A user-runnable ``agent:paper`` command trading the given params.

    Raises ValueError on an unknown strategy or a missing required key, so
    schema bugs surface in tests instead of silently hiding a UI CTA.
    """
    strategy = canonical_strategy(strategy)
    if strategy not in PARAM_SCHEMA:
        raise ValueError(f"Unknown paper strategy: {strategy!r}")
    resolved = resolve_paper_params(strategy, params, None)
    missing = [p.key for p in PARAM_SCHEMA[strategy]
               if p.required and resolved.get(p.key) is None]
    if missing:
        raise ValueError(f"Missing required {strategy} params: {', '.join(missing)}")
    tokens = [f"strategy:{strategy}"]
    for p in PARAM_SCHEMA[strategy]:
        value = resolved.get(p.key)
        if value is None:
            continue
        tokens.append(f"{p.key}:{_fmt(value)}")
    if symbols:
        clean = [str(s).upper().strip() for s in symbols if s][:10]
        if clean:
            tokens.append("symbols:" + ",".join(clean))
    return "agent:paper " + " ".join(tokens)


def parse_command_params(strategy: str, raw: Optional[dict]) -> Dict[str, Any]:
    """Flat ``agent:paper`` tokens (strings) → typed params for ``strategy``.

    Only schema keys are carried; unknown tokens are left for the caller's
    own handling (symbols, duration, poll, …).
    """
    strategy = canonical_strategy(strategy)
    schema = PARAM_SCHEMA.get(strategy, [])
    out: Dict[str, Any] = {}
    if not isinstance(raw, dict):
        return out
    for spec in schema:
        if raw.get(spec.key) is not None:
            out[spec.key] = _coerce(raw[spec.key], spec.kind)
    return out


def slug_params(strategy: str, resolved: dict) -> dict:
    """Map resolved paper params onto ``build_slug``'s per-strategy keys.

    Percent-kind values go back to storage ratios first: ``build_slug``'s
    formatter re-applies the ``0 < |v| < 1`` → ×100 heuristic, so a 0.5%
    stop passed as percent ``0.5`` would otherwise render as ``50sl``
    instead of ``05sl``. Points (VIX level) and ratios (contraction
    threshold) pass through unscaled.
    """
    strategy = canonical_strategy(strategy)
    kinds = {p.key: p.kind for p in PARAM_SCHEMA.get(strategy, [])}

    def slug_value(key: str):
        value = resolved.get(key)
        if kinds.get(key) == "percent" and isinstance(value, (int, float)):
            return value / 100.0
        return value

    if strategy == "buy_the_dip":
        return {
            "dip_threshold": slug_value("dip_threshold"),
            "stop_loss": slug_value("stop_loss_threshold"),
            "take_profit": slug_value("take_profit_threshold"),
            "hold_days": resolved.get("hold_days"),
            "min_hold_days": resolved.get("min_hold_days"),
        }
    if strategy == "momentum":
        return {
            "lookback_period": resolved.get("lookback_period"),
            "momentum_threshold": slug_value("momentum_threshold"),
            "hold_days": resolved.get("hold_days"),
            "take_profit": slug_value("take_profit_threshold"),
            "stop_loss": slug_value("stop_loss_threshold"),
        }
    if strategy == "vix":
        return {
            "vix_threshold": resolved.get("vix_threshold"),
            "hold_type": "on" if resolved.get("hold_overnight", True) else "eod",
        }
    if strategy == "box_wedge":
        return {
            "risk_pct": slug_value("risk_per_trade_pct"),
            "contraction_threshold": resolved.get("contraction_threshold"),
        }
    return dict(resolved)