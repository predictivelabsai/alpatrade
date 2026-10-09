"""``/live/allocations`` — set the cash allocated to each live strategy per Alpaca account.

Writes ONLY ``alpatrade.strategy_allocations`` (sql/46). It never talks to the broker except
the read-only account snapshot used to validate the numbers against equity/cash, and it
never activates a strategy: a sleeve trades only when its ``strategy_configs`` row is active
and the runner picks it up (see utils/strategy_allocation.py). ``/live/account`` stays a
pure read-only view.

Semantics per strategy: blank = for the primary (Mag-7) "rest of the account"; for others
"no allocation" (row deactivated). A number = dollars of equity the strategy may use.
Validation: allocations >= 0, sum of fixed allocations <= account equity, universes of
allocated strategies disjoint. An allocation above current free cash is accepted with a
warning (the sleeve can't buy until cash frees up; it never uses margin).
"""
from __future__ import annotations

import hashlib
import html
import json
import logging
import re
from typing import Optional

from fasthtml.common import Div, NotStr, Style
from starlette.responses import RedirectResponse

from engine.web.ph_layout import page
from utils.live_btd_config import DEFAULT_STRATEGY
from utils.strategy_allocation import PRIMARY_PREFIX, validate_allocations

logger = logging.getLogger(__name__)
KNOWN_PREFIXES = {DEFAULT_STRATEGY: PRIMARY_PREFIX, "buy_the_dip_semi7_minhold_live": "s7btd"}

_CSS = """
.sa{max-width:980px;margin:auto;padding:0 1rem 3rem}.sa h1{font-size:1.3rem}
.sa table{width:100%;border-collapse:collapse;background:var(--bg-elev);font-size:.85rem}
.sa th,.sa td{padding:.5rem .6rem;border-bottom:1px solid var(--line);text-align:left}
.sa input[type=number]{width:9rem}.sa .muted{color:var(--ink-muted);font-size:.8rem}
.sa .err{color:#9b302b;background:#fff0ee;padding:.6rem .8rem;border-radius:.4rem;margin:.6rem 0}
.sa .ok{color:#147a4b;background:#eefaf3;padding:.6rem .8rem;border-radius:.4rem;margin:.6rem 0}
.sa .warn{color:#7a5a14;background:#fff8e6;padding:.6rem .8rem;border-radius:.4rem;margin:.6rem 0}
"""


def _e(v) -> str:
    return html.escape("" if v is None else str(v))


def default_prefix(name: str) -> str:
    if name in KNOWN_PREFIXES:
        return KNOWN_PREFIXES[name]
    return "s" + hashlib.sha1(name.encode()).hexdigest()[:6]


def _pool():
    from engine.live_accounts import _pool as p
    return p()


def load_rows(account_number: str) -> list[dict]:
    """Every strategy config joined with this account's allocation (if any)."""
    from sqlalchemy import text
    with _pool().get_session() as s:
        rows = s.execute(text("""
            SELECT c.name, c.display_name, c.params, c.is_active AS config_active, c.version,
                   a.cid_prefix, a.allocation_usd, COALESCE(a.is_active, FALSE) AS alloc_active
            FROM alpatrade.strategy_configs c
            LEFT JOIN alpatrade.strategy_allocations a
                   ON a.strategy_name = c.name AND a.account_number = :a
            ORDER BY c.id"""), {"a": str(account_number)}).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("params"), str):
            d["params"] = json.loads(d["params"])
        d["is_primary"] = d["name"] == DEFAULT_STRATEGY
        d["cid_prefix"] = d.get("cid_prefix") or default_prefix(d["name"])
        d["allocation_usd"] = None if d.get("allocation_usd") is None else float(d["allocation_usd"])
        out.append(d)
    return out


def parse_form(form: dict, rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Form values -> proposed allocation rows (+ parse errors)."""
    errs, out = [], []
    for r in rows:
        raw = str(form.get(f"alloc__{r['name']}", "") or "").strip().replace(",", "").lstrip("$")
        if raw == "":
            val = None
        else:
            try:
                val = round(float(raw), 2)
            except ValueError:
                errs.append(f"{r['name']}: {raw!r} is not a number"); continue
        active = r["is_primary"] or val is not None
        out.append({"strategy_name": r["name"], "cid_prefix": r["cid_prefix"], "allocation_usd": val,
                    "is_active": active, "is_primary": r["is_primary"]})
    return out, errs


def check(proposed: list[dict], rows: list[dict], *, equity: Optional[float], cash: Optional[float]):
    """(errors, warnings) for a proposal."""
    if equity is None:
        return ["account equity unavailable -> cannot validate allocations"], []
    universes = {r["name"]: list((r.get("params") or {}).get("symbols") or []) for r in rows}
    errs = validate_allocations(proposed, equity=equity, cash=cash, universes=universes)
    warns = []
    fixed = sum(p["allocation_usd"] or 0 for p in proposed if p["is_active"] and not p["is_primary"])
    if cash is not None and fixed > cash + 1e-6:
        warns.append(f"non-primary allocations ${fixed:,.2f} exceed free cash ${cash:,.2f}: those sleeves only "
                     "buy as cash frees up (cash only, never margin)")
    prim = next((p for p in proposed if p["is_primary"]), None)
    if prim and prim["allocation_usd"] is None:
        warns.append(f"primary strategy gets the rest of the account: ${max(0.0, equity - fixed):,.2f}")
    return errs, warns


def save(account_number: str, proposed: list[dict], by: str) -> None:
    from sqlalchemy import text
    with _pool().get_session() as s:
        for p in proposed:
            if p["is_primary"] and p["allocation_usd"] is None:
                # no row needed: NULL = rest of account (keeps the pre-sleeve behaviour)
                s.execute(text("DELETE FROM alpatrade.strategy_allocations WHERE account_number=:a AND strategy_name=:n"),
                          {"a": account_number, "n": p["strategy_name"]})
                continue
            s.execute(text("""
                INSERT INTO alpatrade.strategy_allocations
                    (account_number, strategy_name, cid_prefix, allocation_usd, is_active, updated_by)
                VALUES (:a, :n, :p, :v, :act, :by)
                ON CONFLICT (account_number, strategy_name) DO UPDATE SET
                    allocation_usd = EXCLUDED.allocation_usd, is_active = EXCLUDED.is_active,
                    updated_by = EXCLUDED.updated_by, updated_at = NOW()"""),
                {"a": account_number, "n": p["strategy_name"], "p": p["cid_prefix"],
                 "v": p["allocation_usd"], "act": p["is_active"], "by": by})
        s.commit()


def account_numbers(user_id: str) -> list[dict]:
    from engine.live_accounts import list_live_accounts
    return list_live_accounts(user_id)


def account_balances(user_id: str, account_number: str) -> dict:
    from engine.brokers.alpaca_live_readonly import LiveReadOnlyClient, summarize_account
    from engine.live_accounts import get_live_account_credentials
    creds = get_live_account_credentials(user_id, account_number)
    if not creds:
        return {}
    c = LiveReadOnlyClient(creds["api_key"], creds["secret_key"], expected_account_number=creds["account_number"])
    return summarize_account(c.get_account())


def render(accounts: list[dict], selected: Optional[str], rows: list[dict], bal: dict,
           errors=(), warnings=(), saved=False) -> str:
    if not accounts:
        return ("<div class='sa'><h1>Strategy allocations</h1><p class='muted'>No live broker account is "
                "linked to your login.</p></div>")
    tabs = " · ".join(
        f"<a href='/live/allocations?account={_e(a['account_number'])}'>{'<b>' if str(a['account_number']) == selected else ''}"
        f"{_e(a.get('label') or a['account_number'])}{'</b>' if str(a['account_number']) == selected else ''}</a>"
        for a in accounts)
    msg = "".join(f"<div class='err'>{_e(x)}</div>" for x in errors)
    msg += "".join(f"<div class='warn'>{_e(x)}</div>" for x in warnings)
    if saved and not errors:
        msg += "<div class='ok'>Saved. Runners pick allocations up on their next event pass.</div>"
    eq, cash = bal.get("equity"), bal.get("cash")
    trs = []
    for r in rows:
        v = "" if r["allocation_usd"] is None else f"{r['allocation_usd']:.2f}"
        state = "active" if r["config_active"] else "inactive config (not traded)"
        ph = "rest of account" if r["is_primary"] else "not allocated"
        syms = ", ".join((r.get("params") or {}).get("symbols") or [])
        trs.append(f"<tr><td><b>{_e(r.get('display_name') or r['name'])}</b><div class='muted'>{_e(r['name'])} · v{_e(r['version'])}"
                   f" · prefix <code>{_e(r['cid_prefix'])}</code></div></td><td class='muted'>{_e(syms)}</td>"
                   f"<td>{_e(state)}</td><td><input type='number' min='0' step='0.01' name='alloc__{_e(r['name'])}' "
                   f"value='{v}' placeholder='{ph}'></td></tr>")
    return (f"<div class='sa'><h1>Strategy allocations</h1><p class='muted'>{tabs}</p>"
            f"<p>Account <b>{_e(selected)}</b> · equity <b>${(eq or 0):,.2f}</b> · cash <b>${(cash or 0):,.2f}</b></p>{msg}"
            f"<form method='post' action='/live/allocations'><input type='hidden' name='account' value='{_e(selected)}'>"
            "<table><tr><th>Strategy</th><th>Universe</th><th>Status</th><th>Allocation (USD)</th></tr>"
            + "".join(trs) + "</table><p><button type='submit'>Save allocations</button></p></form>"
            "<p class='muted'>Each strategy sizes positions as pos_frac × its allocation and can only buy while its "
            "own exposure + pending buys stay within the allocation, never beyond account cash (no margin). "
            "Orders are tagged by the strategy's client_order_id prefix. Saving here does not activate a strategy "
            "or place any order.</p></div>")


def register(app, rt):
    def _view(session, account, form=None):
        user_id = session.get("user_id")
        if not user_id:
            return RedirectResponse("/signin", status_code=303)
        try:
            from engine.auth import get_user_by_id
            user = get_user_by_id(str(user_id))
        except Exception:  # noqa: BLE001
            user = None
        errors, warnings, saved, rows, bal = [], [], False, [], {}
        try:
            accts = account_numbers(str(user_id))
        except Exception:  # noqa: BLE001
            accts = []; errors.append("Live account lookup is unavailable right now.")
        own = [str(a["account_number"]) for a in accts]
        sel = account if account in own else (own[0] if own else None)
        if account and account not in own:
            errors.append("That account is not linked to your login.")
        if sel:
            try:
                rows = load_rows(sel)
            except Exception as exc:  # noqa: BLE001
                logger.warning("allocations load failed: %s", type(exc).__name__)
                errors.append("Strategy allocations are unavailable (run sql/46_strategy_allocations.sql).")
            try:
                bal = account_balances(str(user_id), sel)
            except Exception as exc:  # noqa: BLE001
                logger.warning("allocations balance failed: %s", type(exc).__name__)
            if form is not None and rows and not errors:
                proposed, errs = parse_form(form, rows)
                e2, warnings = check(proposed, rows, equity=bal.get("equity"), cash=bal.get("cash"))
                errors += errs + e2
                if not errors:
                    save(sel, proposed, (user or {}).get("email") or str(user_id))
                    saved = True; rows = load_rows(sel)
                else:  # echo the attempted values
                    for r, p in zip(rows, proposed):
                        r["allocation_usd"] = p["allocation_usd"]
        return page("live-account", Style(_CSS), Div(NotStr(render(accts, sel, rows, bal, errors, warnings, saved))),
                    user=user, title="Strategy allocations · AlpaTrade", right_news=False)

    @rt("/live/allocations", methods=["GET"])
    def allocations_get(session, account: str = ""):
        return _view(session, account or None)

    @rt("/live/allocations", methods=["POST"])
    async def allocations_post(session, request):
        form = dict(await request.form())
        acct = str(form.get("account") or "")
        if not re.fullmatch(r"[A-Za-z0-9]{1,64}", acct):
            acct = ""
        return _view(session, acct or None, form=form)

    return ["/live/allocations"]
