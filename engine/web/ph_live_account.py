"""``/live/account`` — READ-ONLY view of the signed-in user's linked Alpaca LIVE account.

Portfolio summary (equity, cash, buying power, day P&L), current positions and
open orders, fetched on each page load through
:class:`engine.brokers.alpaca_live_readonly.LiveReadOnlyClient` (GET-only,
allow-listed endpoints). The page has no forms, no POST route and no
order/cancel/close controls. Credentials come from
``alpatrade.user_live_broker_accounts`` scoped to ``session['user_id']``, so a
user only ever sees the live account linked to their own login.
"""
from __future__ import annotations

import html
import logging

from fasthtml.common import Div, NotStr, Style
from starlette.responses import RedirectResponse

from engine.web.ph_layout import page

logger = logging.getLogger(__name__)

_CSS = """
.la{width:100%;max-width:1180px;margin:auto;padding:0 1rem 3rem}
.la-head{display:flex;align-items:baseline;gap:1rem;flex-wrap:wrap;margin:.4rem 0 1rem}
.la h1{font-size:1.35rem;margin:0}
.la h2{font-size:.95rem;margin:1.4rem 0 .6rem}
.la .muted{color:var(--ink-muted);font-size:.8rem}
.la-head .muted{display:block}
.la-tabs{display:flex;margin-left:auto}
.la-tabs a{border:1px solid var(--line);background:var(--bg-elev);color:var(--ink-muted);
 text-decoration:none;padding:.48rem .8rem;font-size:.8rem}
.la-tabs a:first-child{border-radius:.45rem 0 0 .45rem}
.la-tabs a:last-child{border-radius:0 .45rem .45rem 0}
.la-tabs a.active{background:var(--accent);color:var(--bg-elev);border-color:var(--accent)}
.la-badge{font-size:.68rem;border:1px solid var(--line-br);border-radius:1rem;padding:.12rem .5rem;
 color:var(--ink-muted);margin-left:.4rem;vertical-align:middle;font-weight:600}
.la-badge.live{border-color:#b43b35;color:#b43b35}
.la-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:.7rem}
.la-kpi{background:var(--bg-elev);border:1px solid var(--line);border-radius:.65rem;padding:1rem}
.la-kpi .l{font-size:.7rem;text-transform:uppercase;letter-spacing:.06em;color:var(--ink-dim)}
.la-kpi .v{font-size:1.28rem;font-weight:650;margin-top:.2rem;font-variant-numeric:tabular-nums}
.la-kpi .s{font-size:.75rem;color:var(--ink-muted);margin-top:.15rem}
.la .pos{color:#147a4b}.la .neg{color:#b43b35}
.la-tblwrap{overflow-x:auto;border:1px solid var(--line);border-radius:.65rem}
.la table{width:100%;border-collapse:collapse;background:var(--bg-elev);font-size:.84rem;
 font-variant-numeric:tabular-nums}
.la th,.la td{padding:.55rem .7rem;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
.la th{font-size:.66rem;text-transform:uppercase;letter-spacing:.08em;color:var(--ink-dim)}
.la tr:last-child td{border-bottom:none}
.la td.num,.la th.num{text-align:right}
.la td.sym{font-family:var(--font-mono);font-weight:650}
.la .empty{background:var(--bg-elev);border:1px solid var(--line);border-radius:.65rem;
 padding:1.4rem;text-align:center;color:var(--ink-muted);font-size:.86rem}
.la .err{color:#9b302b;background:#fff0ee;padding:.7rem .9rem;border-radius:.45rem;font-size:.84rem}
.la .ro{font-size:.74rem;color:var(--ink-muted);margin-top:1.2rem}
.la a.refresh{font-size:.78rem;color:var(--accent);text-decoration:none;margin-left:.6rem}
@media(max-width:820px){.la-kpis{grid-template-columns:repeat(2,1fr)}}
"""

_LOCAL_TIME_JS = """
<script>
document.querySelectorAll('.la time[datetime]').forEach(function(t){
  var d=new Date(t.getAttribute('datetime'));
  if(!isNaN(d)){t.textContent=d.toLocaleString([], {month:'short',day:'numeric',
    hour:'2-digit',minute:'2-digit'});t.title=t.getAttribute('datetime');}
});
</script>
"""


def _e(v) -> str:
    return html.escape(str(v if v is not None else ""))


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _money(v, signed: bool = False) -> str:
    x = _num(v)
    if x is None:
        return "—"
    return f"{'+' if signed and x > 0 else ''}{'-' if x < 0 else ''}${abs(x):,.2f}"


def _qty(v) -> str:
    x = _num(v)
    if x is None:
        return "—"
    return f"{x:,.0f}" if x == int(x) else f"{x:,.6f}".rstrip("0").rstrip(".")


def _cls(v) -> str:
    x = _num(v)
    return "" if x is None or x == 0 else ("pos" if x > 0 else "neg")


def _kpis(s: dict) -> str:
    pct = s.get("day_pl_pct")
    pct_txt = f"{pct:+.2f}%" if isinstance(pct, (int, float)) else ""
    cards = [
        ("Equity", _money(s.get("equity")), f"prev close {_money(s.get('last_equity'))}", ""),
        ("Cash", _money(s.get("cash")), "", ""),
        ("Buying power", _money(s.get("buying_power")), "", ""),
        ("Day P&amp;L", _money(s.get("day_pl"), signed=True), pct_txt, _cls(s.get("day_pl"))),
    ]
    return "<div class='la-kpis'>" + "".join(
        f"<div class='la-kpi' data-kpi='{lbl.split('&')[0].strip().lower().replace(' ', '-')}'>"
        f"<div class='l'>{lbl}</div><div class='v {cls}'>{val}</div>"
        f"<div class='s'>{_e(sub)}</div></div>"
        for lbl, val, sub, cls in cards) + "</div>"


def _positions_table(positions: list[dict]) -> str:
    if not positions:
        return "<div class='empty'>No open positions.</div>"
    rows = []
    for p in sorted(positions, key=lambda p: str(p.get("symbol"))):
        plpc = _num(p.get("unrealized_plpc"))
        rows.append(
            f"<tr data-symbol='{_e(p.get('symbol'))}'><td class='sym'>{_e(p.get('symbol'))}</td>"
            f"<td>{_e(p.get('side') or 'long')}</td>"
            f"<td class='num'>{_qty(p.get('qty'))}</td>"
            f"<td class='num'>{_money(p.get('avg_entry_price'))}</td>"
            f"<td class='num'>{_money(p.get('current_price'))}</td>"
            f"<td class='num'>{_money(p.get('market_value'))}</td>"
            f"<td class='num {_cls(p.get('unrealized_pl'))}'>{_money(p.get('unrealized_pl'), True)}</td>"
            f"<td class='num {_cls(plpc)}'>{(f'{plpc * 100:+.2f}%') if plpc is not None else '—'}</td>"
            f"<td class='num {_cls(p.get('unrealized_intraday_pl'))}'>"
            f"{_money(p.get('unrealized_intraday_pl'), True)}</td></tr>")
    return ("<div class='la-tblwrap'><table id='live-positions'><thead><tr>"
            "<th>Symbol</th><th>Side</th><th class='num'>Qty</th><th class='num'>Avg entry</th>"
            "<th class='num'>Price</th><th class='num'>Market value</th>"
            "<th class='num'>Unrealized P&amp;L</th><th class='num'>Unrealized %</th>"
            "<th class='num'>Today</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table></div>")


def _orders_table(orders: list[dict]) -> str:
    if not orders:
        return "<div class='empty'>No open orders.</div>"
    rows = []
    for o in orders:
        qty = (_qty(o.get("qty")) if o.get("qty") not in (None, "")
               else (f"{_money(o.get('notional'))} notional" if o.get("notional") else "—"))
        typ = o.get("type") or o.get("order_type") or ""
        lim = _money(o.get("limit_price")) if o.get("limit_price") else "—"
        stop = _money(o.get("stop_price")) if o.get("stop_price") else ""
        sub = str(o.get("submitted_at") or o.get("created_at") or "")
        rows.append(
            f"<tr data-symbol='{_e(o.get('symbol'))}'><td class='sym'>{_e(o.get('symbol'))}</td>"
            f"<td>{_e(o.get('side'))}</td><td>{_e(typ)}</td>"
            f"<td class='num'>{_e(qty)}</td>"
            f"<td class='num'>{lim}{(' / stop ' + stop) if stop else ''}</td>"
            f"<td>{_e(o.get('time_in_force'))}</td><td>{_e(o.get('status'))}</td>"
            f"<td><time datetime='{_e(sub)}'>{_e(sub[:16].replace('T', ' '))} UTC</time></td></tr>")
    return ("<div class='la-tblwrap'><table id='live-orders'><thead><tr>"
            "<th>Symbol</th><th>Side</th><th>Type</th><th class='num'>Qty / notional</th>"
            "<th class='num'>Limit</th><th>TIF</th><th>Status</th><th>Submitted</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")


def _tabs() -> str:
    return ("<div class='la-tabs'><a href='/live'>Live runs</a>"
            "<a class='active' href='/live/account'>Live account</a></div>")


def _head(sub: str, badge: str = "") -> str:
    return (f"<div class='la-head'><div><h1>Live account{badge}</h1>"
            f"<span class='muted'>{sub}</span></div>{_tabs()}</div>")


def load_view(user_id: str) -> dict:
    """Resolve the user's live link and fetch a read-only snapshot.

    Returns ``{"linked": False}``, ``{"linked": True, "error": str, ...}`` or
    ``{"linked": True, "account_number", "label", "summary", "positions", "orders"}``.
    """
    from engine.live_accounts import get_live_account_credentials
    try:
        creds = get_live_account_credentials(user_id)
    except Exception as exc:  # noqa: BLE001 — table missing / DB down
        logger.warning("live account lookup failed: %s", type(exc).__name__)
        return {"linked": False, "error": "Live account lookup is unavailable right now."}
    if not creds:
        return {"linked": False}
    from engine.brokers.alpaca_live_readonly import (
        LiveReadOnlyClient, LiveReadOnlyError, summarize_account)
    out = {"linked": True, "account_number": creds["account_number"], "label": creds["label"]}
    try:
        client = LiveReadOnlyClient(creds["api_key"], creds["secret_key"],
                                    expected_account_number=creds["account_number"])
        snap = client.snapshot()
    except LiveReadOnlyError as exc:
        out["error"] = str(exc)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("live account snapshot failed: %s", type(exc).__name__)
        out["error"] = "Could not read the live account right now."
        return out
    out.update(summary=summarize_account(snap["account"]),
               positions=snap["positions"], orders=snap["orders"])
    return out


def render(view: dict) -> str:
    if not view.get("linked"):
        msg = view.get("error") or (
            "No live broker account is linked to your login. Live accounts are linked "
            "read-only by an operator; paper accounts live under Settings.")
        return (f"<div class='la'>{_head('Read-only view of your real-money broker account')}"
                f"<div class='empty'>{_e(msg)}</div></div>")
    acct = _e(view.get("account_number"))
    badge = f"<span class='la-badge live'>LIVE</span><span class='la-badge'>read-only</span>"
    sub = (f"Alpaca account <b id='live-account-number'>{acct}</b> · {_e(view.get('label'))}"
           "<a class='refresh' href='/live/account'>Refresh</a>")
    if view.get("error"):
        body = f"<div class='err'>{_e(view['error'])}</div>"
    else:
        s = view.get("summary") or {}
        body = (_kpis(s)
                + f"<h2>Positions ({len(view.get('positions') or [])})</h2>"
                + _positions_table(view.get("positions") or [])
                + f"<h2>Open orders ({len(view.get('orders') or [])})</h2>"
                + _orders_table(view.get("orders") or []))
    foot = ("<p class='ro'>Read-only: this page only reads your account from Alpaca "
            "(account, positions, open orders). It cannot place, cancel or close anything, "
            "and this account is not available to chat trading tools or paper jobs. "
            "Runner-tracked strategy trades and performance are under "
            "<a href='/live'>Live runs</a>.</p>")
    return f"<div class='la'>{_head(sub, badge)}{body}{foot}</div>{_LOCAL_TIME_JS}"


def register(app, rt):
    @rt("/live/account", methods=["GET"])
    def live_account_get(session):
        user_id = session.get("user_id")
        if not user_id:
            return RedirectResponse("/signin", status_code=303)
        try:
            from engine.auth import get_user_by_id
            user = get_user_by_id(str(user_id))
        except Exception:  # noqa: BLE001
            user = None
        view = load_view(str(user_id))
        return page("live-account", Style(_CSS), Div(NotStr(render(view))), user=user,
                    title="Live account · AlpaTrade", right_news=False)

    return ["/live/account"]
