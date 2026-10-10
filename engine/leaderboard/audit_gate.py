"""Leaderboard side of the backtest audit (utils/backtest_audit.py).

* ``audit_strategy(row)``: audit a kind='backtest' leaderboard row from its stored
  ``backtest_metrics`` (+ ``audit_input``) and the skill's Parameters block. Used at render time
  for the "Audit: warnings / failed" badge; nothing is hidden.
* ``gate(bm, skill_md)``: used by every publish path (cwt_pipeline publish / publish_group,
  seed_semi7_backtest). Attaches ``bm['audit']`` + ``bm['engine_stamp']`` and raises
  PermissionError when the audit fails, so a failing backtest is never (re)published.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from utils import backtest_audit as ba

log = logging.getLogger("leaderboard.audit")


def _skill_params(skill_md: str) -> dict:
    try:
        from engine.leaderboard.skill import extract_params
        return extract_params(skill_md or "") or {}
    except Exception:  # noqa: BLE001
        return {}


def _live_params(slug: Optional[str]) -> Optional[dict]:
    if not slug:
        return None
    try:
        from sqlalchemy import text
        from engine.db.pool import DatabasePool
        with DatabasePool().get_session() as s:
            p = s.execute(text("SELECT params FROM alpatrade.strategy_configs WHERE name = :n AND is_active "
                               "ORDER BY version DESC LIMIT 1"), {"n": slug}).scalar()
        return json.loads(p) if isinstance(p, str) else p
    except Exception as exc:  # noqa: BLE001
        log.warning("live params lookup failed: %s", type(exc).__name__)
        return None


def audit_input_for(bm: dict, skill_md: str = "", live_params: Optional[dict] = None) -> ba.AuditInput:
    a = ba.from_leaderboard_metrics(bm or {}, live_params=live_params)
    sp = _skill_params(skill_md)
    ex = sp.get("execution") or {}
    if a.slippage_bps is None and ex.get("slippage_bps_per_side") is not None:
        a.slippage_bps = float(ex["slippage_bps_per_side"])
        # engine.backtest.fills.Friction books its cost per trade as fees (cwt_pipeline)
        if a.fees_recorded is None:
            a.fees_recorded = a.slippage_bps > 0
    if a.label is None and not (bm or {}).get("live_slug"):
        a.label = "research"     # trader-described strategies, not presented as our live strategy
    if a.engine is None and not a.engine_stamp:
        a.engine = (bm or {}).get("template") and str(bm["template"]).split()[0] or None
    return a


def audit_strategy(row: dict) -> Optional[ba.AuditReport]:
    if (row or {}).get("kind") != "backtest":
        return None
    bm = row.get("backtest_metrics") if isinstance(row.get("backtest_metrics"), dict) else {}
    if not bm:
        return None
    lp = None
    if (bm.get("audit_input") or {}).get("label") == "live" and not (bm.get("audit_input") or {}).get("live_params"):
        lp = _live_params(bm.get("live_slug"))
    return ba.audit(audit_input_for(bm, row.get("skill_md") or "", lp))


def gate(bm: dict, skill_md: str = "", live_params: Optional[dict] = None) -> dict:
    from utils.engine_stamp import stamp
    bm = dict(bm)
    rep = ba.audit(audit_input_for(bm, skill_md, live_params))
    bm["audit"] = rep.to_dict()
    ba.assert_publishable(rep)
    bm.setdefault("engine_stamp", stamp((bm.get("audit_input") or {}).get("engine") or "unknown"))
    return bm
