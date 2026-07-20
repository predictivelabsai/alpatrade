"""Resumable, checkpointed pipeline over the existing Orchestrator phases.

Framework-agnostic on purpose: the durable sequencing/checkpointing is ours (so a
framework swap never touches it). Each node's result is persisted via
``store.save_step``; a resumed run skips nodes already ``done``. Nodes reason through
agents via ``engine.agents.runtime`` where an LLM is needed.

**Paper-only:** the trading node calls the Orchestrator's *paper* phase; there is no
live-order path here (enforced by :mod:`engine.autonomy.policy` and by never importing
a live broker into this package).
"""
from __future__ import annotations

import os
from typing import Any, Callable, Optional

from engine.autonomy import store

Node = tuple[str, Callable[[dict], Any]]


class Pipeline:
    """Run ``nodes`` in order for a run, checkpointing and resuming each."""

    def __init__(self, nodes: list[Node]):
        self.nodes = nodes

    def run(self, run_id: str, ctx: Optional[dict] = None) -> dict:
        ctx = ctx or {}
        done = store.completed_steps(run_id)
        store.set_status(run_id, "running")
        for name, fn in self.nodes:
            if name in done:
                store.append_event(run_id, f"skip {name} (checkpoint)")
                continue
            try:
                out = fn(ctx)
            except Exception as e:  # noqa: BLE001
                store.save_step(run_id, name, status="failed", output={"error": str(e)})
                store.append_event(run_id, f"{name} failed: {e}", level="error")
                store.set_status(run_id, "failed", error=str(e))
                raise
            store.save_step(run_id, name, output=_json_safe(out))
            store.append_event(run_id, f"{name} done")
            if isinstance(out, dict):
                ctx.update(out.get("ctx", {}))
        store.set_status(run_id, "done")
        return ctx


def _json_safe(v: Any) -> Any:
    try:
        import json
        json.dumps(v)
        return v
    except Exception:  # noqa: BLE001
        return {"repr": str(v)[:500]}


# --------------------------------------------------------------------------- nodes

def policy_gate(ctx: dict) -> dict:
    """Filter ctx['candidates'] through the deterministic RiskPolicy (paper-only)."""
    from engine.autonomy.policy import evaluate, PortfolioState, RiskLimits
    state = ctx.get("portfolio") or PortfolioState(equity=0, open_positions=0, gross_exposure=0)
    limits = ctx.get("limits") or RiskLimits()
    kill = bool(ctx.get("kill_switch"))
    admitted = []
    for c in ctx.get("candidates", []):
        d = evaluate(c, state, limits, kill_switch=kill)
        if d.admit:
            admitted.append({"candidate": c, "sized_notional": d.sized_notional})
    return {"ctx": {"admitted": admitted}, "admitted_count": len(admitted)}


def scout_node(ctx: dict) -> dict:
    """Populate ctx['candidates'] + ctx['portfolio'] for the policy gate.

    Uses symbols the Scout put in the run config; falls back to a fresh scan.
    """
    from engine.autonomy import scout
    from engine.autonomy.policy import Candidate
    cfg = ctx.get("config") or {}
    portfolio = scout.portfolio_state()
    scouted = cfg.get("scouted")
    if scouted:
        candidates = [Candidate(symbol=s["symbol"], strategy_slug=s.get("strategy", "btd"),
                                intended_notional=float(s.get("notional", 0)))
                      for s in scouted]
    else:
        candidates = scout.scan(strategy=cfg.get("strategy", "btd"),
                                equity=portfolio.equity)
    return {"ctx": {"candidates": candidates, "portfolio": portfolio},
            "scouted": len(candidates)}


# Bounded paper session for an autonomy run (the Orchestrator default is 7 days, which
# would block the worker loop). Overridable per run via config['paper_duration_seconds'].
DEFAULT_PAPER_SECONDS = 3600


def build_paper_config(base_config: Optional[dict], admitted: list,
                       default_duration: int = DEFAULT_PAPER_SECONDS) -> dict:
    """Pure: turn the risk-gate's admitted candidates into a paper-trade config.

    Threads the gate's *sized_notional* into ``capital_per_trade`` (the per-trade cap)
    and restricts trading to the admitted symbols, so the executed size is the
    risk-policy size — not the strategy default. Bounds the session duration.
    """
    cfg = dict(base_config or {})
    if admitted:
        cfg["symbols"] = [a["candidate"].symbol for a in admitted]
        cfg["capital_per_trade"] = round(min(a["sized_notional"] for a in admitted), 2)
    cfg["duration_seconds"] = int(cfg.get("paper_duration_seconds", default_duration))
    return cfg


def default_pipeline(user_id: Optional[str] = None, account_id: Optional[str] = None) -> Pipeline:
    """The paper-only scout→backtest→gate→paper→reconcile→promote pipeline (checkpointed)."""

    def _orch():
        from agents.orchestrator import Orchestrator
        return Orchestrator(user_id=user_id, account_id=account_id)

    def _check(result, phase):
        # A phase that returns {"error": ...} must halt the run honestly (→ failed),
        # not checkpoint a misleading "done".
        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(f"{phase}: {result['error']}")
        return result

    def backtest(ctx):
        r = _check(_orch().run_backtest(ctx.get("config")), "backtest")
        best = (r.get("best_config") if isinstance(r, dict) else None) or {}
        return {"ctx": {"backtest_result": r, "best_config": best},
                "variations": r.get("total_variations") if isinstance(r, dict) else None,
                "has_strategy": bool(best.get("params"))}

    def validate_backtest(ctx):
        if not (ctx.get("best_config") or {}).get("params"):
            return {"skipped": "no viable backtest strategy"}
        return _check(_orch().run_validation(source="backtest"), "validate_backtest")

    def paper_trade(ctx):
        # PAPER account only; size + symbols come from the risk gate. If the backtest
        # produced no viable strategy, there is nothing to paper-trade — skip cleanly.
        if not (ctx.get("best_config") or {}).get("params"):
            return {"skipped": "no viable backtest strategy (no trades) — nothing to paper-trade"}
        dur = int(os.getenv("AUTONOMY_PAPER_SECONDS", DEFAULT_PAPER_SECONDS))
        cfg = build_paper_config(ctx.get("config"), ctx.get("admitted", []), default_duration=dur)
        return _check(_orch().run_paper_trade(cfg), "paper_trade")

    def reconcile(ctx):
        return _orch().run_reconciliation(ctx.get("config"))

    def promote(ctx):
        from agents.report_agent import ReportAgent
        from engine.autonomy import promote as _promote, notify as _notify
        strategies = ReportAgent().top_strategies(trade_type="paper", limit=10) or []
        if isinstance(strategies, dict):
            strategies = strategies.get("strategies", [])
        promoted = _promote.run_promotions(strategies, run_id=ctx.get("run_id"))
        if promoted:
            _notify.send_promotion_digest(promoted)
        return {"promoted": len(promoted)}

    return Pipeline([
        ("scout", scout_node),
        ("backtest", backtest),
        ("policy_gate", policy_gate),
        ("validate_backtest", validate_backtest),
        ("paper_trade", paper_trade),
        ("reconcile", reconcile),
        ("promote", promote),
    ])


def run_once(config: Optional[dict] = None, user_id: Optional[str] = None,
             account_id: Optional[str] = None) -> str:
    """Create one autonomy run and execute the full pipeline synchronously.

    Returns the run_id (inspect alpatrade.autonomy_run_steps for the checkpoints).
    For a quick verification run pass e.g.
    ``{"symbols": ["AAPL"], "lookback": "1m", "paper_duration_seconds": 15}``.
    """
    run_id = store.create_run("full", config=config or {}, user_id=user_id, account_id=account_id)
    ctx = {"config": config or {}, "run_id": run_id}
    default_pipeline(user_id, account_id).run(run_id, ctx)
    return run_id
