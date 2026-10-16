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
alpatrade.strategy_allocations (the operator runner's config) and never places orders. A
dedicated per-activation process (utils/user_live_runner.py, started by
scripts/user_live_supervisor.py) trades it on the user's own account while
USER_LIVE_TRADING_ENABLED=1. Users pause (no new entries, exits continue), resume or deactivate
(process stopped) from Settings > Integrations.
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any, Callable, Optional

log = logging.getLogger("leaderboard.activate")
PAPER_DURATION_S = 604800          # legacy: one week per LLM paper job (no longer used)
PAPER_ALLOCATION_USD = 10000.0     # paper sleeve cap; cash is still checked at order time
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
        _migrate_legacy_paper(s)
    _schema_ok = True


def _migrate_legacy_paper(s) -> None:
    """Paper activations used to queue an LLM 'deepagent_paper' job (that loop is paused in prod,
    so they never ran). They now run as per-user runner processes like live ones: give each a
    prefix + allocation, make it runnable, and cancel the old queued job. Idempotent."""
    from sqlalchemy import text
    rows = s.execute(text("SELECT id, user_id::text, user_strategy_id, status, job_id FROM "
                          "alpatrade.user_strategy_activations WHERE mode = 'paper' AND cid_prefix IS NULL")).all()
    for aid, uid, sid, st, job in rows:
        s.execute(text("UPDATE alpatrade.user_strategy_activations SET cid_prefix = :p, "
                       "allocation_usd = COALESCE(allocation_usd, :v), "
                       "status = CASE WHEN status = 'queued' THEN 'active' ELSE status END, updated_at = NOW() "
                       "WHERE id = :i"), {"p": cid_prefix(uid, sid), "v": PAPER_ALLOCATION_USD, "i": aid})
        if job:
            s.execute(text("UPDATE alpatrade.autonomy_runs SET status = 'cancelled', updated_at = NOW() "
                           "WHERE run_id::text = :j AND status = 'queued'"), {"j": str(job)})


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


def own_or_clone(strategy_id: int, user: dict) -> Optional[int]:
    """The user's own strategy id for ``strategy_id``: itself if owned, else their clone (created
    on first use and listed under My strategies). None if not visible."""
    from engine.leaderboard import clone_bt
    res = clone_bt.clone_strategy(int(strategy_id), user)
    return int(res[0]) if res else None


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
    try:
        from utils.user_live_runner import user_params
        user_params((cfg.get("params") or {}))      # same validation the runner applies
    except ValueError as exc:
        return {"ok": False, "message": f"This strategy can't run yet: {exc}"}
    except ImportError:
        pass
    _record(user_id, strategy_id, "paper", acct, "active", prefix=cid_prefix(user_id, strategy_id),
            allocation=PAPER_ALLOCATION_USD, confirmed=True)
    return {"ok": True,
            "message": f"Paper trading started for strategy #{int(strategy_id)} on your Alpaca paper account "
                       f"(paper money, up to ${PAPER_ALLOCATION_USD:,.0f}; runs until you stop it). Its own "
                       "process starts within a minute and trades at US market hours (ET)."}


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
                                   "AND COALESCE(strategy_slug, '') NOT LIKE 'user:%' "   # per-user runner runs
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
                       f"{plan['cid_prefix']}-…. Your own live runner picks it up at the next trading session "
                       "(entries 15:45-15:55 ET); nothing has been ordered yet. Pause or deactivate it any time in "
                       "Settings > Integrations.")
    return plan


STATUS_LABEL = {"pending_runner": "Waiting for the next session", "active": "Running",
                "paused": "Paused (no new entries; exits continue)", "deactivated": "Deactivated"}
ACTIONS = {"pause": ("paused", ("pending_runner", "active")), "resume": ("active", ("paused",)),
           "deactivate": ("deactivated", ("pending_runner", "active", "paused"))}


def list_live(user_id: str) -> list[dict]:
    try:
        ensure_schema()
        from sqlalchemy import text
        with _pool().get_session() as s:
            rows = s.execute(text("""SELECT a.id, a.user_strategy_id, a.account_ref, a.cid_prefix, a.allocation_usd,
                       a.status, a.updated_at, us.name FROM alpatrade.user_strategy_activations a
                       JOIN alpatrade.user_strategies us ON us.id = a.user_strategy_id
                       WHERE a.user_id = CAST(:u AS UUID) AND a.mode = 'live' ORDER BY a.id"""),
                             {"u": str(user_id)}).mappings().all()
        return [{**dict(r), "status": _confirmed_live(r)} for r in rows]
    except Exception as exc:  # noqa: BLE001
        log.warning("list live activations failed: %s", type(exc).__name__)
        return []


def set_status(user_id: str, activation_id: int, action: str) -> bool:
    """Per-user kill switch: pause / resume / deactivate ONE of the user's own activations."""
    if action not in ACTIONS:
        return False
    new, allowed = ACTIONS[action]
    ensure_schema()
    from sqlalchemy import text
    with _pool().get_session() as s:
        n = s.execute(text("""UPDATE alpatrade.user_strategy_activations SET status = :n, updated_at = NOW()
                              WHERE id = :i AND user_id = CAST(:u AS UUID) AND mode = 'live'
                                AND status = ANY(:ok)"""),
                      {"n": new, "i": int(activation_id), "u": str(user_id), "ok": list(allowed)}).rowcount
    return bool(n)


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


# ── status + controls shown on My strategies, strategy pages, the dashboard ──────────────
PAPER_LIVE_STATES = ("queued", "running")


def statuses(user_id: str) -> dict:
    """{strategy_id: {"paper": "running"|"starting"|"ended"|None, "live": status|None, ...}}."""
    out: dict = {}
    try:
        ensure_schema()
        from sqlalchemy import text
        with _pool().get_session() as s:
            rows = s.execute(text("""
                SELECT a.user_strategy_id, a.mode, a.status, a.job_id, a.allocation_usd, a.cid_prefix,
                       a.account_ref, r.status AS job_status
                FROM alpatrade.user_strategy_activations a
                LEFT JOIN alpatrade.autonomy_runs r ON a.mode = 'paper' AND r.run_id::text = a.job_id
                WHERE a.user_id = CAST(:u AS UUID)"""), {"u": str(user_id)}).mappings().all()
    except Exception as exc:  # noqa: BLE001
        log.warning("activation statuses failed: %s", type(exc).__name__)
        return out
    for r in rows:
        d = out.setdefault(int(r["user_strategy_id"]), {"paper": None, "live": None})
        if r["mode"] == "paper":
            d["paper"] = {"active": "running", "pending_runner": "starting", "paused": "paused",
                          "queued": "starting"}.get(r["status"], "ended")
        else:
            d["live"] = _confirmed_live(r)
            d["allocation"] = float(r["allocation_usd"]) if r["allocation_usd"] is not None else None
            d["prefix"] = r["cid_prefix"]
    return out


def _confirmed_live(r) -> str:
    """'pending_runner' reads as 'active' once the runner heartbeat shows it acting (display only)."""
    if r["status"] != "pending_runner":
        return r["status"]
    try:
        from engine.admin_running import heartbeats_for, runner_alive, runner_key
        key = runner_key("live", r["account_ref"], r["cid_prefix"])
        from sqlalchemy import text

        def ex(sql, params):
            with _pool().get_session() as s:
                return [dict(x) for x in s.execute(text(sql), params).mappings().all()]
        if key and runner_alive(heartbeats_for(ex, [key]).get(key)):
            return "active"
    except Exception as exc:  # noqa: BLE001
        log.debug("runner heartbeat lookup failed: %s", type(exc).__name__)
    return r["status"]


def stop_paper(user_id: str, strategy_id: int) -> bool:
    """Stop the user's paper activation (the supervisor stops its process on the next poll)."""
    ensure_schema()
    from sqlalchemy import text
    with _pool().get_session() as s:
        n = s.execute(text("UPDATE alpatrade.user_strategy_activations SET status = 'deactivated', updated_at = NOW() "
                           "WHERE user_id = CAST(:u AS UUID) AND user_strategy_id = :i AND mode = 'paper' "
                           "AND status <> 'deactivated'"),
                      {"u": str(user_id), "i": int(strategy_id)}).rowcount
    return bool(n)


def live_id(user_id: str, strategy_id: int) -> Optional[int]:
    ensure_schema()
    from sqlalchemy import text
    with _pool().get_session() as s:
        v = s.execute(text("SELECT id FROM alpatrade.user_strategy_activations WHERE user_id = CAST(:u AS UUID) "
                           "AND user_strategy_id = :i AND mode = 'live'"),
                      {"u": str(user_id), "i": int(strategy_id)}).scalar()
    return int(v) if v else None


_PAPER_LBL = {"running": "Paper running", "starting": "Paper starting", "paused": "Paper paused",
              "ended": "Paper stopped"}
_LIVE_LBL = {"pending_runner": "Live starting", "active": "Live running", "paused": "Live paused",
             "deactivated": "Live off"}


def status_badges(st: Optional[dict]) -> str:
    st = st or {}
    out = []
    if st.get("paper"):
        cls = "on" if st["paper"] in ("running", "starting") else ""
        out.append(f"<span class='act-badge paper {cls}'>{_PAPER_LBL[st['paper']]}</span>")
    if st.get("live"):
        cls = {"active": "on", "pending_runner": "on", "paused": "warn"}.get(st["live"], "")
        alloc = f" · ${st['allocation']:,.0f}" if st.get("allocation") and st["live"] != "deactivated" else ""
        out.append(f"<span class='act-badge live {cls}'>{_LIVE_LBL.get(st['live'], st['live'])}{alloc}</span>")
    return "".join(out)


ACT_CSS = """
.act-badge{display:inline-block;font-size:.68rem;font-weight:650;padding:.12rem .45rem;border-radius:999px;
  margin:.15rem .3rem .15rem 0;background:#eef0ec;color:#5b6157;white-space:nowrap}
.act-badge.on{background:#e3f4ea;color:#147a4b}.act-badge.live.on{background:#fdeceb;color:#b43b35}
.act-badge.warn{background:#fff6e0;color:#8a6410}
.act-ctl{display:flex;flex-wrap:wrap;gap:.35rem;align-items:center;margin:.35rem 0 0}
.act-ctl form{margin:0;display:inline}
.act-ctl .ab{display:inline-flex;align-items:center;min-height:2rem;padding:.25rem .65rem;border-radius:.4rem;
  font-size:.76rem;font-weight:650;cursor:pointer;text-decoration:none;border:1px solid var(--line-br,#d6d9d2);
  background:var(--bg-elev,#fff);color:var(--ink,#1d211b);white-space:nowrap}
.act-ctl .ab.paper{background:#1F5D43;color:#fff;border-color:#1F5D43}
.act-ctl .ab.live{color:#b43b35;border-color:#b43b35}
.act-ctl .ab.stop{color:#9b302b}
@media(max-width:640px){.act-ctl .ab{min-height:2.5rem;font-size:.8rem}}
"""


def controls_html(sid: int, st: Optional[dict] = None, *, back: str = "", badges: bool = True) -> str:
    """Activate Paper / Activate Live / Pause / Resume / Deactivate (+ status) for one strategy.
    Works for a strategy the user doesn't own: the routes clone it first."""
    import html as _h
    sid = int(sid)
    st = st or {}
    b = f"<input type='hidden' name='back' value='{_h.escape(back)}'>" if back else ""

    def post(path, label, cls):
        return (f"<form method='post' action='/strategies/{sid}/{path}'>{b}"
                f"<button type='submit' class='ab {cls}'>{label}</button></form>")
    out = []
    if st.get("paper") in ("running", "starting", "paused"):
        out.append(post("paper/stop", "Stop paper", "stop"))
    else:
        out.append(post("activate/paper", "Activate Paper", "paper"))
    live = st.get("live")
    if live in ("pending_runner", "active"):
        out.append(post("live/pause", "Pause live", ""))
        out.append(post("live/deactivate", "Deactivate live", "stop"))
    elif live == "paused":
        out.append(post("live/resume", "Resume live", ""))
        out.append(post("live/deactivate", "Deactivate live", "stop"))
    else:
        out.append(f"<a class='ab live' href='/strategies/{sid}/activate/live'>Activate Live…</a>")
    return ("<div class='act-ctl' data-strategy='" + str(sid) + "'>"
            + (status_badges(st) if badges else "") + "".join(out) + "</div>")
