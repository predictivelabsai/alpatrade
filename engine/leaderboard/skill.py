"""The single-markdown strategy *skill*: rules prompt + a machine-readable Parameters block.

A strategy's ``skill_md`` is what "Copy for ChatGPT / Claude" puts on the clipboard. The
Parameters block is the first fenced JSON object that carries a ``params`` dict (same shape
as an ``alpatrade.strategy_configs`` row: ``params`` + ``execution``).
"""
from __future__ import annotations

import json
import re
from typing import Optional

_FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.DOTALL | re.MULTILINE)
_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def front_matter(md: str) -> dict:
    """Flat ``key: value`` YAML front matter (no nesting needed here)."""
    m = _FRONT.match(md or "")
    out: dict = {}
    if not m:
        return out
    for line in m.group(1).splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def extract_params(md: str) -> Optional[dict]:
    """First fenced JSON block holding a ``params`` dict, else None."""
    for m in _FENCE.finditer(md or ""):
        try:
            data = json.loads(m.group(1))
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict) and isinstance(data.get("params"), dict):
            return data
    return None


def copy_text(strategy: dict) -> str:
    """Clipboard text for ChatGPT / Claude: the strategy skill markdown itself.

    Strategies without a skill body still get a usable prompt (name + description).
    """
    md = (strategy.get("skill_md") or "").strip()
    if md:
        return md + "\n"
    return (f"# {strategy.get('name') or 'Trading strategy'}\n\n"
            f"{strategy.get('description') or ''}\n")


def chat_prompt(strategy: dict) -> str:
    """Natural-language AlpaTrade chat prompt for a paper backtest of the strategy."""
    block = extract_params(strategy.get("skill_md") or "") or {}
    p = block.get("params") or {}
    name = strategy.get("name") or "this strategy"
    if not p:
        return (f"Backtest my strategy \"{name}\" over the last 6 months against SPY "
                f"(paper only, no live orders): {strategy.get('description') or ''}").strip()
    syms = ",".join(p.get("symbols") or [])
    ref = "20-day high" if p.get("ref") == "high20" else "previous close"
    hold = p.get("max_hold") or p.get("min_hold")
    return (f"Backtest buy-the-dip on {syms} over the last 6 months vs SPY: buy when the price "
            f"is {p.get('dip')}% or more below the {ref}, take profit {p.get('tp')}%, "
            f"stop loss {p.get('sl')}%, hold {hold} days, position size "
            f"{p.get('pos_frac')} of equity, cash only. Paper only, no live orders. "
            f"(Strategy: {name})")
