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


def default_pipeline(user_id: Optional[str] = None, account_id: Optional[str] = None) -> Pipeline:
    """The paper-only scout→backtest→gate→paper→reconcile→promote pipeline (checkpointed)."""

    def _orch():
        from agents.orchestrator import Orchestrator
        return Orchestrator(user_id=user_id, account_id=account_id)

    def backtest(ctx):
        return _orch().run_backtest(ctx.get("config"))

    def validate_backtest(ctx):
        return _orch().run_validation(source="backtest")

    def paper_trade(ctx):
        # PAPER account only.
        return _orch().run_paper_trade(ctx.get("config"))

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
