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
import threading
from typing import Any, Callable, Optional

from engine.autonomy import store

Node = tuple[str, Callable[[dict], Any]]


class JobCancelled(RuntimeError):
    pass


class Pipeline:
    """Run ``nodes`` in order for a run, checkpointing and resuming each."""

    def __init__(self, nodes: list[Node]):
        self.nodes = nodes

    def run(self, run_id: str, ctx: Optional[dict] = None,
            stop_event: Optional[threading.Event] = None) -> dict:
        ctx = ctx or {}
        done = store.completed_steps(run_id)
        previous_outputs = store.completed_step_outputs(run_id)
        if not store.mark_running(run_id):
            raise JobCancelled("job cancelled")
        for name, fn in self.nodes:
            if stop_event and stop_event.is_set():
                store.append_event(run_id, "cancellation requested")
                raise JobCancelled("job cancelled")
            if name in done:
                store.append_event(run_id, f"skip {name} (checkpoint)")
                previous = previous_outputs.get(name)
                if isinstance(previous, dict):
                    ctx.update(previous.get("ctx", {}))
                continue
            try:
                out = fn(ctx)
            except JobCancelled:
                raise
            except Exception as e:  # noqa: BLE001
                store.save_step(run_id, name, status="failed", output={"error": str(e)})
                store.append_event(run_id, f"{name} failed: {e}", level="error")
                if not store.set_status(run_id, "failed", error=str(e)):
                    raise JobCancelled("job cancelled") from e
                raise
            store.save_step(run_id, name, output=_json_safe(out))
            store.append_event(run_id, f"{name} done")
            if isinstance(out, dict):
                ctx.update(out.get("ctx", {}))
        if stop_event and stop_event.is_set():
            raise JobCancelled("job cancelled")
        if not store.set_status(run_id, "done"):
            raise JobCancelled("job cancelled")
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


def scout_node(ctx: dict, user_id: Optional[str] = None,
               account_id: Optional[str] = None) -> dict:
    """Populate ctx['candidates'] + ctx['portfolio'] for the policy gate.

    Uses symbols the Scout put in the run config; falls back to a fresh scan.
    Annotates the deterministic ranking with an LLM sanity check when the
    configured runtime is reachable (best-effort; never alters the list).
    """
    from engine.autonomy import scout
    from engine.autonomy.policy import Candidate
    cfg = ctx.get("config") or {}
    portfolio = (
        scout.portfolio_state(account_id=account_id, user_id=user_id)
        if user_id else scout.portfolio_state()
    )
    scouted = cfg.get("scouted")
    if scouted:
        candidates = [Candidate(symbol=s["symbol"], strategy_slug=s.get("strategy", "btd"),
                                intended_notional=float(s.get("notional", 0)))
                      for s in scouted]
    else:
        scan_kwargs = {
            "strategy": cfg.get("strategy", "btd"),
            "limit": max(1, min(int(cfg.get("limit", 5)), 20)),
            "equity": portfolio.equity,
        }
        if user_id:
            scan_kwargs.update(user_id=user_id, account_id=account_id)
        candidates = scout.scan(**scan_kwargs)
    # LLM annotation (best-effort): flag anything a price-move ranker can't see.
    if candidates:
        try:
            from engine.autonomy.reason import reason
            tickers = ", ".join(c.symbol for c in candidates[:5])
            note = reason(
                "These symbols were picked by a deterministic price-move scanner for a "
                f"{cfg.get('strategy', 'btd')} paper strategy: {tickers}. In one or two "
                "sentences, flag any near-term binary risk (earnings, FDA, delisting) "
                "or say they look unremarkable. Plain text."
            )
            if note:
                store.append_event(ctx.get("run_id"), f"scout reasoning: {note[:200]}")
        except Exception:  # noqa: BLE001
            pass
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


def default_pipeline(user_id: Optional[str] = None,
                     account_id: Optional[str] = None,
                     stop_event: Optional[threading.Event] = None) -> Pipeline:
    """The paper-only scout→backtest→gate→paper→reconcile→promote pipeline (checkpointed)."""

    def _orch():
        from agents.orchestrator import Orchestrator
        return Orchestrator(user_id=user_id, account_id=account_id)

    def tenant_scout(ctx):
        return scout_node(ctx, user_id=user_id, account_id=account_id)

    def _check(result, phase):
        # A phase that returns {"error": ...} must halt the run honestly (→ failed),
        # not checkpoint a misleading "done".
        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(f"{phase}: {result['error']}")
        return result

    def backtest(ctx):
        cfg = dict(ctx.get("config") or {})
        # Closed-loop: if a prior run's refit node narrowed the grid, use it.
        refined = cfg.get("refined_grid")
        if refined:
            cfg["variations"] = refined
        else:
            # Regime-aware grid: classify today's regime and pass it through so
            # BacktestAgent pulls the per-regime preset (Phase 2a/2b).
            try:
                from engine.regime import current_regime
                cfg["regime"] = current_regime().state
            except Exception:  # noqa: BLE001
                pass
        r = _check(_orch().run_backtest(cfg), "backtest")
        best = (r.get("best_config") if isinstance(r, dict) else None) or {}
        # LLM rationale for the selected config (best-effort; selection stays
        # deterministic — the note only annotates the run log).
        if best.get("params"):
            try:
                from engine.autonomy.reason import reason
                note = reason(
                    "A grid-search backtest selected this config as best: "
                    f"params={best.get('params')}, sharpe={best.get('sharpe_ratio')}, "
                    f"out of {r.get('total_variations')} variations"
                    + (f" in a {cfg.get('regime')} regime" if cfg.get("regime") else "")
                    + ". In one sentence, state why these params plausibly won and one "
                      "risk to watch. Plain text."
                )
                if note:
                    store.append_event(ctx.get("run_id"), f"backtest reasoning: {note[:200]}")
            except Exception:  # noqa: BLE001
                pass
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
        return _check(
            _orch().run_paper_trade(cfg, stop_event=stop_event),
            "paper_trade",
        )

    def reconcile(ctx):
        return _orch().run_reconciliation(ctx.get("config"))

    def refit(ctx):
        """Closed-loop feedback: narrow the next grid when paper drifts from backtest.

        Reads the backtest result + the paper trades just executed, computes a
        drift signal (paper Sharpe vs backtest Sharpe), and—if drift is
        detected—produces a refined grid centred on the top-K variations. The
        refined grid is threaded into ctx so the next scout tick uses it. Pure
        logic lives in engine.autonomy.refit; this node does the I/O.
        """
        from engine.autonomy import refit as _refit
        from scripts.daily_pnl_report import gather_trades
        bt_result = ctx.get("backtest_result") or {}
        paper_trades = gather_trades(
            limit=200, user_id=user_id, account_id=account_id
        )
        plan = _refit.refit_plan(bt_result, paper_trades)
        log_msg = f"refit: {plan['reason']}"
        store.append_event(ctx.get("run_id"), log_msg)
        # LLM explanation of drift (best-effort; plan logic stays deterministic).
        try:
            from engine.autonomy.reason import reason
            note = reason(
                "A paper-trading refit check produced this signal: "
                f"{plan['reason']} (paper Sharpe={plan['paper_sharpe']}, "
                f"backtest Sharpe={plan['backtest_sharpe']}). In one sentence, "
                "explain the most plausible market cause and whether narrowing "
                "the parameter grid is the right response. Plain text."
            )
            if note:
                store.append_event(ctx.get("run_id"), f"refit reasoning: {note[:200]}")
        except Exception:  # noqa: BLE001
            pass
        out: dict = {"drift": plan["drift"], "refit_reason": plan["reason"],
                     "paper_sharpe": plan["paper_sharpe"],
                     "backtest_sharpe": plan["backtest_sharpe"]}
        if plan["drift"] and plan["refined_grid"]:
            out["ctx"] = {"refined_grid": plan["refined_grid"]}
        return out

    def promote(ctx):
        from agents.report_agent import ReportAgent
        from engine.autonomy import promote as _promote, notify as _notify
        from engine.autonomy.reason import reason
        strategies = ReportAgent().top_strategies(
            trade_type="paper", limit=10,
            user_id=user_id, account_id=account_id,
        ) or []
        if isinstance(strategies, dict):
            strategies = strategies.get("strategies", [])
        # Phase 3a: let the configured runtime (LangGraph/deepagents/hermes)
        # reason about which strategies are strongest. The deterministic
        # PromotionBar (promote.py) stays as the hard gate — the LLM never
        # decides alone; it only annotates the recommendation.
        if strategies and reason:
            try:
                summary_lines = [
                    f"- {s.get('strategy_slug','?')}: pnl={s.get('total_pnl','?')} "
                    f"sharpe={s.get('sharpe_ratio','?')} trades={s.get('total_trades','?')}"
                    for s in strategies[:10]
                ]
                llm_note = reason(
                    "Given these paper-trading strategies ranked by PnL, "
                    "which 1-3 show the most robust risk-adjusted profile "
                    "(high Sharpe, reasonable drawdown, enough trades)? "
                    "Be concise.\n" + "\n".join(summary_lines)
                )
                if llm_note:
                    store.append_event(ctx.get("run_id"), f"promote reasoning: {llm_note[:200]}")
            except Exception:  # noqa: BLE001
                pass
        promoted = _promote.run_promotions(strategies, run_id=ctx.get("run_id"))
        if promoted and not user_id:
            _notify.send_promotion_digest(promoted)
        return {"promoted": len(promoted)}

    return Pipeline([
        ("scout", tenant_scout),
        ("backtest", backtest),
        ("policy_gate", policy_gate),
        ("validate_backtest", validate_backtest),
        ("paper_trade", paper_trade),
        ("reconcile", reconcile),
        ("refit", refit),
        ("promote", promote),
    ])


def deepagent_job_pipeline(
    kind: str,
    user_id: str,
    account_id: Optional[str],
    stop_event: Optional[threading.Event] = None,
) -> Pipeline:
    """Build a checkpointed pipeline for a DeepAgent-enqueued job kind."""
    from agents.orchestrator import Orchestrator

    def orchestrator() -> Orchestrator:
        return Orchestrator(user_id=user_id, account_id=account_id)

    def checked(result: Any, phase: str) -> Any:
        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(f"{phase} failed")
        return result

    def backtest(ctx: dict) -> dict:
        result = checked(orchestrator().run_backtest(dict(ctx.get("config") or {})), "backtest")
        return {"ctx": {"backtest_result": result}, "result": result}

    def validate_backtest(ctx: dict) -> dict:
        prior = ctx.get("backtest_result") or {}
        result = checked(orchestrator().run_validation(
            run_id=prior.get("run_id"), source="backtest", trades=prior.get("trades")
        ), "backtest validation")
        return {"ctx": {"backtest_validation": result}, "result": result}

    def paper(ctx: dict) -> dict:
        paper_orchestrator = orchestrator()
        best_config = (ctx.get("backtest_result") or {}).get("best_config")
        if best_config:
            paper_orchestrator.state.best_config = best_config
        result = checked(paper_orchestrator.run_paper_trade(
            dict(ctx.get("config") or {}), stop_event=stop_event
        ), "paper trade")
        return {"ctx": {"paper_result": result}, "result": result}

    def validate_paper(ctx: dict) -> dict:
        prior = ctx.get("paper_result") or {}
        result = checked(orchestrator().run_validation(
            run_id=prior.get("session_id") or prior.get("run_id"), source="paper_trade"
        ), "paper validation")
        return {"ctx": {"paper_validation": result}, "result": result}

    def reconcile(ctx: dict) -> dict:
        result = checked(orchestrator().run_reconciliation(dict(ctx.get("config") or {})),
                         "reconciliation")
        return {"ctx": {"reconciliation": result}, "result": result}

    def report(ctx: dict) -> dict:
        from agents.report_agent import ReportAgent

        result = ReportAgent().summary(
            limit=5, user_id=user_id, account_id=account_id
        )
        return {"result": result}

    if kind == "deepagent_backtest":
        return Pipeline([("backtest", backtest)])
    if kind == "deepagent_paper":
        return Pipeline([("paper_trade", paper)])
    if kind == "deepagent_full":
        return Pipeline([
            ("backtest", backtest),
            ("validate_backtest", validate_backtest),
            ("paper_trade", paper),
            ("validate_paper", validate_paper),
            ("reconcile", reconcile),
            ("report", report),
        ])
    raise ValueError(f"unsupported DeepAgent job kind: {kind}")


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
