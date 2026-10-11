"""Activate a user's own (cloned / backtested) strategy on THEIR paper or live Alpaca account.

Shown as two buttons after a clone or backtest in chat (clone_bt.result_markdown).

Paper (direct): needs the user's paper keys (alpatrade.user_accounts). Queues one
``deepagent_paper`` autonomy job (the same worker path as the chat paper tools) with the
strategy's buy-the-dip params on the user's own paper account; recorded in
``alpatrade.user_strategy_activations`` (sql/49). Only the BTD template trades on paper today.

Live (explicit confirmation): needs a live link (alpatrade.user_live_broker_accounts, saved from
Settings > Integrations). The confirmation states real money, cash only (never margin) and the
dollar allocation. The request is validated with the multi-strategy sleeve rules
(utils/strategy_allocation.validate_allocations): allocation > 0 and within equity together with
the account's existing sleeves, a unique client_order_id prefix ``u<6 hex>`` (never ``btd`` /
``s7btd``), and a universe disjoint from the account's other active sleeves. It is stored as
``pending_runner``: this module never writes alpatrade.strategy_configs or
alpatrade.strategy_allocations (the live runner's config) and never places orders. The shared
runner only trades the operator's account today; per-user live sleeves need an operator switch.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Callable, Optional

log = logging.getLogger("leaderboard.activate")
PAPER_DURATION_S = 604800          # one week per activation (the worker's maximum)
_schema_ok = False


def _pool():
    from engine.db.pool import DatabasePool
    return DatabasePool()


def ensure_schema() -> None:
    global _schema_ok
    if _schema_ok:
        return
    from pathlib import Path
    from sqlalchemy import text
    from engine.leaderboard.clone_bt import ensure_schema as clone_schema
    clone_schema()
    sql = (Path(__file__).resolve().parents[2] / "sql" / "49_user_strategy_activations.sql").read_text()
    with _pool().get_session() as s:
        s.execute(text(sql))
    _schema_ok = True


def cid_prefix(user_id: str, strategy_id: int) -> str:
    """Per-user, per-strategy client_order_id prefix: 'u' + 6 hex (valid sleeve prefix)."""
    return "u" + hashlib.sha1(f"{user_id}:{int(strategy_id)}".encode()).hexdigest()[:6]


def paper_params(params: dict) -> dict:
    """User BTD config (dip/tp/sl in %, holds in days) -> paper agent params (ratio space)."""
    p = params or {}

    def ratio(v):
        v = float(v)
        return v / 100.0 if v >= 1 else v
    out: dict[str, Any] = {}
    for src, dst in (("dip", "dip_threshold"), ("tp", "take_profit_threshold"), ("sl", "stop_loss_threshold")):
        if p.get(src) is not None:
            out[dst] = ratio(p[src])
    if p.get("max_hold", p.get("hold_days")) is not None:
        out["hold_days"] = int(p.get("max_hold", p.get("hold_days")))
    if p.get("min_hold") is not None:
        out["min_hold_days"] = int(p["min_hold"])
    if p.get("pos_frac") is not None:
        out["position_size"] = float(p["pos_frac"])
    return out


def _owned(strategy_id: int, user_id: str) -> tuple[Optional[dict], Optional[dict]]:
    from engine.leaderboard import clone_bt, store
    s = store.get_visible(int(strategy_id), str(user_id))
    if not s or str(s.get("user_id")) != str(user_id):
        return None, None
    return s, clone_bt.get_config(int(strategy_id), str(user_id))


def _paper_account(user_id: str) -> Optional[str]:
    from sqlalchemy import text
    with _pool().get_session() as s:
        v = s.execute(text("SELECT account_id FROM alpatrade.user_accounts WHERE user_id = CAST(:u AS UUID) "
                           "AND is_active AND alpaca_api_key_enc IS NOT NULL ORDER BY created_at LIMIT 1"),
                      {"u": str(user_id)}).scalar()
    return str(v) if v else None


def _record(user_id: str, sid: int, mode: str, account_ref: str, status: str, *,
            prefix: Optional[str] = None, allocation: Optional[float] = None,
            job_id: Optional[str] = None, confirmed: bool = False) -> None:
    ensure_schema()
    from sqlalchemy import text
    with _pool().get_session() as s:
        s.execute(text("""
            INSERT INTO alpatrade.user_strategy_activations
                (user_id, user_strategy_id, mode, account_ref, cid_prefix, allocation_usd, status, job_id,
                 confirmed_at)
            VALUES (CAST(:u AS UUID), :i, :m, :a, :p, :v, :st, :j, CASE WHEN :c THEN NOW() END)
            ON CONFLICT (user_id, user_strategy_id, mode) DO UPDATE SET
                account_ref = EXCLUDED.account_ref, cid_prefix = EXCLUDED.cid_prefix,
                allocation_usd = EXCLUDED.allocation_usd, status = EXCLUDED.status,
                job_id = EXCLUDED.job_id, confirmed_at = EXCLUDED.confirmed_at, updated_at = NOW()
        """), {"u": str(user_id), "i": int(sid), "m": mode, "a": str(account_ref), "p": prefix,
               "v": allocation, "st": status, "j": job_id, "c": confirmed})


def activation_status(user_id: str, sid: int) -> dict:
    try:
        ensure_schema()
        from sqlalchemy import text
        with _pool().get_session() as s:
            rows = s.execute(text("SELECT mode, status, account_ref, allocation_usd, cid_prefix, job_id, updated_at "
                                  "FROM alpatrade.user_strategy_activations WHERE user_id = CAST(:u AS UUID) "
                                  "AND user_strategy_id = :i"), {"u": str(user_id), "i": int(sid)}).mappings().all()
        return {r["mode"]: dict(r) for r in rows}
    except Exception as exc:  # noqa: BLE001
        log.warning("activation status failed: %s", type(exc).__name__)
        return {}


# ── paper ───────────────────────────────────────────────────────────────────
def activate_paper(strategy_id: int, user_id: str,
                   enqueue: Optional[Callable[..., str]] = None) -> dict:
    """{'ok', 'message', 'job_id'?}. Queues the paper job on the user's own paper account."""
    from engine.leaderboard import clone_bt
    s, cfg = _owned(strategy_id, user_id)
    if not s:
        return {"ok": False, "message": "That strategy isn't one of yours. Clone it first."}
    cfg = cfg or {}
    if not clone_bt.paper_supported(cfg.get("template") or ""):
        return {"ok": False, "message": f"Paper trading isn't available for the {cfg.get('template') or '?'} "
                "template yet (buy-the-dip only)."}
    acct = _paper_account(user_id)
    if not acct:
        return {"ok": False, "needs_keys": True,
                "message": "Add your Alpaca paper keys in Settings > Integrations first."}
    params = paper_params(cfg.get("params") or {})
    config = {"strategy": "buy_the_dip", "duration_seconds": PAPER_DURATION_S,
              "approved_best_config": {"params": params}, "source_user_strategy_id": int(strategy_id),
              "email_notifications": False}
    syms = (cfg.get("params") or {}).get("symbols") or []
    if syms:
        config["symbols"] = [str(x).upper()[:10] for x in syms][:25]
    if enqueue is None:
        from engine.autonomy import queue
        enqueue = queue.enqueue
    job_id = enqueue(kind="deepagent_paper", config=config, user_id=str(user_id), account_id=acct,
                     dedupe_key=f"activate-paper:{int(strategy_id)}:{acct}")
    _record(user_id, strategy_id, "paper", acct, "queued", job_id=str(job_id), confirmed=True)
    return {"ok": True, "job_id": str(job_id),
            "message": f"Paper trading queued for strategy #{int(strategy_id)} on your Alpaca paper account "
                       "(runs for a week; paper money only)."}


# ── live ────────────────────────────────────────────────────────────────────
def _universe(cfg: dict) -> list[str]:
    return [str(x).upper() for x in ((cfg or {}).get("params") or {}).get("symbols") or []]


def runner_trades_account(account_number: str) -> bool:
    """True when the shared live runner trades this account (it has a non-test live run), i.e.
    the primary Mag-7 sleeve owns 'the rest of the account' there."""
    from sqlalchemy import text
    with _pool().get_session() as s:
        return bool(s.execute(text("SELECT 1 FROM alpatrade.runs WHERE mode = 'live' "
                                   "AND config->>'account_number' = :a "
                                   "AND COALESCE((config->>'test')::boolean, FALSE) = FALSE LIMIT 1"),
                              {"a": str(account_number)}).scalar())


def live_plan(strategy_id: int, user_id: str, allocation: Optional[float] = None,
              snapshot: Optional[Callable[[dict], dict]] = None,
              existing: Optional[Callable[[str], list]] = None,
              runner_account: Optional[Callable[[str], bool]] = None) -> dict:
    """Everything the confirmation page shows + validation errors (nothing is written)."""
    from engine.live_accounts import get_live_account_credentials
    from utils.strategy_allocation import validate_allocations
    s, cfg = _owned(strategy_id, user_id)
    if not s:
        return {"ok": False, "errors": ["That strategy isn't one of yours. Clone it first."]}
    creds = get_live_account_credentials(str(user_id))
    if not creds:
        return {"ok": False, "needs_keys": True, "strategy": s,
                "errors": ["Add your Alpaca LIVE keys in Settings > Integrations first."]}
    if snapshot is None:
        def snapshot(c):
            from engine.brokers.alpaca_live_readonly import LiveReadOnlyClient
            a = LiveReadOnlyClient(c["api_key"], c["secret_key"],
                                   expected_account_number=c["account_number"]).get_account()
            return {"equity": float(a.get("equity") or 0), "cash": float(a.get("cash") or 0)}
    acct = creds["account_number"]
    try:
        bal = snapshot(creds)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "strategy": s, "account_number": acct,
                "errors": [f"Could not read the live account: {type(exc).__name__}"]}
    if existing is None:
        from engine.web.ph_strategy_allocations import load_rows
        existing = load_rows
    rows = existing(acct)
    primary_here = (runner_account or runner_trades_account)(acct)
    prefix = cid_prefix(user_id, strategy_id)
    uni = _universe(cfg or {})
    proposed = [{"strategy_name": r["name"], "cid_prefix": r["cid_prefix"],
                 "allocation_usd": r.get("allocation_usd"), "is_primary": r.get("is_primary"),
                 "is_active": bool(r.get("alloc_active"))
                 or bool(r.get("is_primary") and r.get("config_active") and primary_here)}
                for r in rows]
    name = f"user:{user_id}:{int(strategy_id)}"
    proposed.append({"strategy_name": name, "cid_prefix": prefix, "allocation_usd": allocation,
                     "is_active": True})
    universes = {r["name"]: [str(x).upper() for x in ((r.get("params") or {}).get("symbols") or [])] for r in rows}
    universes[name] = uni
    errors = []
    if allocation is None or not (float(allocation) > 0):
        errors.append("Enter a dollar allocation greater than 0.")
    elif float(allocation) > bal["cash"] + 1e-6:
        errors.append(f"Allocation ${float(allocation):,.2f} is more than the account's free cash "
                      f"${bal['cash']:,.2f} (cash only, never margin).")
    if allocation is not None and float(allocation) > 0:
        errors += validate_allocations(proposed, equity=bal["equity"], cash=bal["cash"], universes=universes)
    if not uni:
        errors.append("The strategy has no symbol universe to trade.")
    return {"ok": not errors, "errors": errors, "strategy": s, "config": cfg, "account_number": acct,
            "equity": bal["equity"], "cash": bal["cash"], "cid_prefix": prefix, "universe": uni,
            "allocation": allocation,
            "others": [p for p in proposed[:-1] if p["is_active"]]}


def activate_live(strategy_id: int, user_id: str, allocation: Optional[float], confirm: str,
                  **kw) -> dict:
    """Record a confirmed, validated live activation as 'pending_runner' (no orders, no runner config)."""
    plan = live_plan(strategy_id, user_id, allocation, **kw)
    if (confirm or "").strip().upper() != "LIVE":
        plan["ok"] = False
        plan.setdefault("errors", []).append("Type LIVE to confirm real-money, cash-only trading.")
    if not plan.get("ok"):
        return plan
    _record(user_id, strategy_id, "live", plan["account_number"], "pending_runner",
            prefix=plan["cid_prefix"], allocation=round(float(allocation), 2), confirmed=True)
    plan["message"] = (f"Live activation recorded for strategy #{int(strategy_id)}: ${float(allocation):,.2f} "
                       f"cash only on account {plan['account_number']}, orders tagged "
                       f"{plan['cid_prefix']}-…. It starts trading once per-user live sleeves are enabled "
                       "on the shared runner; nothing has been ordered.")
    return plan


def buttons_html(strategy_id: int) -> str:
    """The two chat buttons (raw HTML inside the markdown reply)."""
    sid = int(strategy_id)
    b = ("display:inline-flex;align-items:center;min-height:2.6rem;padding:.5rem 1rem;border-radius:.45rem;"
         "font-weight:650;font-size:.85rem;text-decoration:none;cursor:pointer;margin:.2rem .4rem .2rem 0;")
    return (f"<div class='activate-btns' data-strategy='{sid}' style='display:flex;flex-wrap:wrap;margin:.4rem 0'>"
            f"<form method='post' action='/strategies/{sid}/activate/paper' style='margin:0'>"
            f"<button type='submit' class='act-paper' style='{b}background:#1F5D43;color:#fff;border:0'>"
            "Activate Paper</button></form>"
            f"<a class='act-live' href='/strategies/{sid}/activate/live' style='{b}background:#fff;color:#b43b35;"
            "border:1px solid #b43b35'>Activate Live…</a></div>")


__all__ = ["activate_paper", "activate_live", "live_plan", "buttons_html", "cid_prefix",
           "paper_params", "activation_status"]
