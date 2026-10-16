"""Strategy Parameters page: edit params, version history, walk-forward, apply (v0.51.0).

* ``GET  /strategies/{sid}/params``            grouped form (defaults + help text) + versions + WF
* ``POST /strategies/{sid}/params``            validate server-side -> NEW draft version
* ``POST /strategies/{sid}/params/{vid}/wf``    start / reuse the walk-forward run (background)
* ``GET  /strategies/{sid}/params/wf/{rid}.json`` progress + (partial) results, polled by the page
* ``POST /strategies/{sid}/params/{vid}/apply/paper``  apply immediately
* ``GET|POST /strategies/{sid}/params/{vid}/apply/live``  needs a completed WF run + typed LIVE
* ``GET  /admin/strategy-params``              admin: every version of every user

All logic lives in engine/leaderboard/params.py; this module renders.
"""
from __future__ import annotations

import html
import json
import logging
from typing import Any, Dict, Optional

from starlette.responses import JSONResponse, RedirectResponse

from utils import btd_rules as R

log = logging.getLogger(__name__)

CSS = """
.sp{max-width:980px}
.sp .chips{display:flex;flex-wrap:wrap;gap:.4rem;margin:.2rem 0 1rem}
.sp .chip{font-size:.74rem;border:1px solid var(--line-br);border-radius:1rem;padding:.15rem .6rem;background:var(--bg-elev)}
.sp .chip.live{border-color:#b43b35;color:#b43b35}.sp .chip.paper{border-color:#1F5D43;color:#1F5D43}
.sp fieldset{border:1px solid var(--line);border-radius:.8rem;background:var(--bg-elev);margin:0 0 .9rem;padding:.8rem 1rem 1rem}
.sp legend{font-weight:650;font-size:.9rem;padding:0 .35rem}
.sp .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:.8rem 1rem}
.sp label{display:block;font-size:.8rem;font-weight:600;color:var(--ink)}
.sp input,.sp select{display:block;width:100%;box-sizing:border-box;margin-top:.25rem;font:inherit;font-size:16px;
 padding:.45rem .55rem;border:1px solid var(--line-br);border-radius:.45rem;background:var(--bg);color:var(--ink);min-height:40px}
.sp .help{display:block;font-weight:400;color:var(--ink-dim);font-size:.72rem;line-height:1.4;margin-top:.25rem}
.sp .ferr{display:block;color:#9b302b;font-size:.74rem;margin-top:.2rem;font-weight:600}
.sp .wide{grid-column:1/-1}
.sp .bar{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;margin:.4rem 0 1.4rem}
.sp .tbl{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--line);border-radius:.7rem;background:var(--bg-elev)}
.sp table{border-collapse:collapse;width:100%;font-size:.8rem;min-width:560px}
.sp th,.sp td{padding:.45rem .6rem;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
.sp th{font-size:.68rem;text-transform:uppercase;letter-spacing:.06em;color:var(--ink-dim)}
.sp td form{display:inline;margin:0}
.sp .mini{min-height:0;padding:.25rem .55rem;font-size:.72rem}
.sp .wf{border:1px solid var(--line);border-radius:.8rem;background:var(--bg-elev);padding:.9rem 1rem;margin:0 0 1.2rem}
.sp .wf .prog{font-size:.8rem;color:var(--ink-muted)}
.sp #wf-chart{height:300px;width:100%}
.sp .pos{color:#147a4b}.sp .neg{color:#b43b35}
.sp .live-warn{border:1px solid #b43b35;background:#fff3f1;padding:.8rem 1rem;border-radius:.5rem;margin:.6rem 0}
@media (max-width:640px){.sp{padding:1.2rem .9rem 2.5rem}.sp .grid{grid-template-columns:1fr}.sp .bar .lb-btn{flex:1 1 auto}}
"""

_SHOW_IF = {"stop_k": ("stop_mode", "atr,stdev"), "tp_mult": ("stop_mode", "atr,stdev"),
            "sl": ("stop_mode", "pct"), "vol_max": ("vol_filter", "atr,spy_atr"),
            "regime_mode": ("regime_filter", "any"), "regime_sma": ("regime_mode", "sma")}
_CHOICE_LABEL = {"": "Off", "SPY": "SPY", "SMH": "SMH", "SPY,SMH": "SPY and SMH", "pct": "Fixed %", "atr": "ATR(14) multiple",
                 "stdev": "20-day stdev multiple", "always": "Always (from the next session)",
                 "exit_day": "Exit day only (after min hold)", "off": "Off", "spy_atr": "SPY ATR (market-wide)",
                 "low5": "Below 5-day low", "sma": "Below moving average", "high20": "20-day high",
                 "prev_close": "Previous close"}


def _e(v) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def _f(x, fmt="{:+.1f}%"):
    return "—" if x is None else fmt.format(x)


def _cls(x):
    return "" if x is None else ("pos" if x > 0 else "neg" if x < 0 else "")


def field_html(k: str, v: Any, err: Optional[str] = None) -> str:
    spec = R.PARAM_SPEC[k]
    attrs = ""
    if k in _SHOW_IF:
        dep, vals = _SHOW_IF[k]
        attrs = f" data-dep='{dep}' data-vals='{_e(vals)}'"
    if "choices" in spec:
        opts = "".join(f"<option value='{_e(c)}'{' selected' if str(v) == c else ''}>{_e(_CHOICE_LABEL.get(c, c))}</option>"
                       for c in spec["choices"])
        ctrl = f"<select name='{k}' id='f-{k}'>{opts}</select>"
    elif spec["type"] == "symbols":
        ctrl = (f"<input name='{k}' id='f-{k}' value='{_e(', '.join(v) if isinstance(v, list) else v)}' "
                "autocapitalize='characters' autocomplete='off' spellcheck='false'>")
    else:
        step = "1" if spec["type"] is int else "any"
        ctrl = (f"<input name='{k}' id='f-{k}' type='number' inputmode='decimal' step='{step}' min='{spec['min']:g}' "
                f"max='{spec['max']:g}' value='{_e(v)}'>")
    wide = " wide" if spec["type"] == "symbols" else ""
    return (f"<div class='fld{wide}'{attrs}><label for='f-{k}'>{_e(spec['label'])}{ctrl}"
            f"<span class='help'>{_e(spec['help'])} Default: {_e(_CHOICE_LABEL.get(str(spec['default']), spec['default']) if not isinstance(spec['default'], list) else ', '.join(spec['default']))}.</span>"
            + (f"<span class='ferr'>{_e(err)}</span>" if err else "") + "</label></div>")


def form_html(sid: int, values: Dict[str, Any], errors: Optional[Dict[str, str]] = None, base_id: Optional[int] = None) -> str:
    errors = errors or {}
    groups = []
    for g in R.PARAM_GROUPS:
        keys = [k for k, s in R.PARAM_SPEC.items() if s["group"] == g]
        groups.append(f"<fieldset><legend>{_e(g)}</legend><div class='grid'>"
                      + "".join(field_html(k, values.get(k, R.PARAM_SPEC[k]["default"]), errors.get(k)) for k in keys)
                      + "</div></fieldset>")
    top = ("<div class='flash err'>Please fix the highlighted fields.</div>" if errors else "")
    return (f"<form method='post' action='/strategies/{sid}/params' id='params-form' novalidate>{top}"
            + (f"<input type='hidden' name='base_version_id' value='{int(base_id)}'>" if base_id else "")
            + "".join(groups)
            + "<fieldset><legend>Save</legend><div class='grid'><div class='fld wide'><label for='f-note'>Note (optional)"
              "<input name='note' id='f-note' maxlength='300' placeholder='e.g. wider semis stop'>"
              "<span class='help'>Saving creates a new draft version. Nothing running changes until you apply it.</span>"
              "</label></div></div></fieldset>"
              "<div class='bar'><button class='lb-btn primary' type='submit'>Save as new version</button>"
              f"<a class='lb-btn' href='/strategies/{sid}/params'>Reset</a></div></form>"
              "<script>(function(){var f=document.getElementById('params-form');if(!f)return;"
              "function vis(d){var s=f.elements[d.dataset.dep];if(!s)return true;var h=s.closest('[data-dep]');"
              "if(h&&!vis(h))return false;if(d.dataset.dep==='regime_filter')return s.value!=='';"
              "return d.dataset.vals.split(',').indexOf(s.value)>=0}"
              "function upd(){f.querySelectorAll('[data-dep]').forEach(function(d){d.style.display=vis(d)?'':'none'})}"
              "f.addEventListener('change',upd);upd();})();</script>")


def _wf_cell(sid: int, v: dict, run: Optional[dict]) -> str:
    if not run:
        return (f"<form method='post' action='/strategies/{sid}/params/{v['id']}/wf'>"
                "<button class='lb-btn mini' type='submit'>Run walk-forward</button></form>")
    if run["status"] == "running":
        return f"<a href='/strategies/{sid}/params?wf={run['id']}'>running…</a>"
    if run["status"] == "error":
        return (f"<span class='neg'>failed</span> <form method='post' action='/strategies/{sid}/params/{v['id']}/wf'>"
                "<button class='lb-btn mini' type='submit'>Retry</button></form>")
    o = ((run.get("result") or {}).get("oos") or {}).get("cand") or {}
    return (f"<a href='/strategies/{sid}/params?wf={run['id']}'>OOS {_f(o.get('total_pct'), '{:+.0f}%')} · "
            f"Sharpe {_f(o.get('sharpe'), '{:.2f}')}</a>")


def versions_html(sid: int, ov: dict) -> str:
    lv, pv = ov.get("live_version"), ov.get("paper_version")
    rows = []
    for v in reversed(ov["versions"]):
        badges = ""
        if lv and lv["id"] == v["id"]:
            badges += "<span class='chip live'>LIVE</span> "
        if pv and pv["id"] == v["id"]:
            badges += "<span class='chip paper'>paper</span> "
        ch = "; ".join(f"{_e(k)} {_e(_short(a))}→<b>{_e(_short(b))}</b>" for k, a, b in (v.get("diff") or [])) or \
             ("baseline" if v["status"] == "baseline" else "—")
        run = ov["wf"].get(v["id"])
        acts = (f"<a class='lb-btn mini' href='/strategies/{sid}/params?from={v['id']}'>Edit from</a> "
                f"<form method='post' action='/strategies/{sid}/params/{v['id']}/apply/paper'>"
                "<button class='lb-btn mini' type='submit'>Apply to paper</button></form> ")
        if (ov.get("activations") or {}).get("live"):
            acts += (f"<a class='lb-btn mini' style='color:#b43b35;border-color:#b43b35' "
                     f"href='/strategies/{sid}/params/{v['id']}/apply/live'>Apply to live…</a>")
        when = str(v.get("created_at") or "")[:16].replace("T", " ")
        rows.append(f"<tr><td><b>v{v['version']}</b> {badges}<br><span class='help'>{_e(when)} UTC · {_e(v.get('source'))}"
                    + (f" · {_e(v.get('note'))}" if v.get("note") else "") + f"</span></td><td>{ch}</td>"
                    f"<td>{_wf_cell(sid, v, run)}</td><td>{acts}</td></tr>")
    return ("<h2 style='font-size:1.05rem;margin:1.4rem 0 .5rem'>Versions</h2><div class='tbl'><table><thead><tr>"
            "<th>Version</th><th>Changes</th><th>Walk-forward</th><th>Actions</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table></div>")


def _short(x):
    if isinstance(x, list):
        return ",".join(map(str, x[:4])) + ("…" if len(x) > 4 else "")
    return "off" if x == "" else (f"{x:g}" if isinstance(x, float) else x)


def wf_panel(sid: int, rid: int) -> str:
    return (f"<div class='wf' id='wf' data-url='/strategies/{sid}/params/wf/{int(rid)}.json'>"
            "<b>Walk-forward</b> <span class='prog' id='wf-prog'>starting…</span>"
            "<div id='wf-body'></div><div id='wf-chart'></div></div>"
            "<script src='https://cdn.plot.ly/plotly-2.35.2.min.js'></script>"
            "<script>(function(){var box=document.getElementById('wf');var url=box.dataset.url;"
            "function f(x,d){return x==null?'—':(d?x.toFixed(2):(x>0?'+':'')+x.toFixed(1)+'%')}"
            "function row(n,c,l,s){return '<tr><td>'+n+'</td><td>'+f(c.total_pct)+'</td><td>'+f(c.sharpe,1)+'</td><td>'+f(c.max_dd_pct)+'</td><td>'"
            "+f(l.total_pct)+' / '+f(l.sharpe,1)+' / '+f(l.max_dd_pct)+'</td><td>'+f(s.total_pct)+' / '+f(s.sharpe,1)+' / '+f(s.max_dd_pct)+'</td></tr>'}"
            "function render(j){var r=j.result||{};var lbl=r.compare_label||'current';"
            "var h='<div class=\"tbl\" style=\"margin-top:.6rem\"><table><thead><tr><th>Window</th><th>Return</th><th>Sharpe</th><th>Max DD</th><th>'+lbl+' (ret/Sh/DD)</th><th>SPY (ret/Sh/DD)</th></tr></thead><tbody>';"
            "var sg=r.segments||{};Object.keys(sg).forEach(function(k){h+=row(k,sg[k].cand,sg[k].live,sg[k].spy)});"
            "if(r.oos&&r.oos.cand)h+=row('<b>OOS chained</b>',r.oos.cand,r.oos.live||{},r.oos.spy||{});"
            "(r.folds||[]).forEach(function(x){h+=row('test '+x.test[0].slice(0,4)+' <span class=help>(fit '+x.fit[0].slice(0,4)+'–'+x.fit[1].slice(0,4)+': '+f(x.fit_cand.total_pct)+')</span>',x.cand,x.live,x.spy)});"
            "h+='</tbody></table></div><p class=\"help\">Parity backtester (same rules as paper/live), $10k per window, fees + 10 bps slippage. Data to '+(r.asof||'…')+'.'+(j.cached?' Cached result.':'')+'</p>';"
            "document.getElementById('wf-body').innerHTML=h;"
            "if(r.curve&&window.Plotly){var c=r.curve;Plotly.react('wf-chart',[{x:c.dates,y:c.cand,name:'This version',line:{color:'#1F5D43'}},"
            "{x:c.dates,y:c.live,name:lbl,line:{color:'#b07d12',dash:'dot'}},{x:c.dates,y:c.spy,name:'SPY',line:{color:'#888'}}],"
            "{margin:{l:45,r:10,t:10,b:30},legend:{orientation:'h'},yaxis:{title:'OOS growth of $10k'},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)'},{displayModeBar:false,responsive:true})}}"
            "function poll(){fetch(url,{credentials:'same-origin'}).then(function(r){return r.json()}).then(function(j){"
            "document.getElementById('wf-prog').textContent=j.status==='done'?'done':(j.status==='error'?'failed: '+(j.error||''):(j.progress||'running…'));"
            "render(j);if(j.status==='running')setTimeout(poll,2000);}).catch(function(){setTimeout(poll,4000)})}poll();})();</script>")


def page_html(ov: dict, values: Dict[str, Any], *, errors=None, msg: str = "", wf_rid: Optional[int] = None,
              base_id: Optional[int] = None) -> str:
    s = ov["strategy"]
    sid = int(s["id"])
    lv, pv, lt = ov.get("live_version"), ov.get("paper_version"), ov["latest"]
    chips = f"<span class='chip'>Latest v{lt['version']} ({_e(lt['status'])})</span>"
    chips += (f"<span class='chip live'>Live runs v{lv['version']}</span>" if lv else "<span class='chip'>Not live</span>")
    if pv:
        chips += f"<span class='chip paper'>Paper runs v{pv['version']}</span>"
    flash = f"<div class='flash'>{_e(msg)}</div>" if msg else ""
    return (f"<div class='lb sp'>{flash}<a href='/strategies/{sid}' style='font-size:.82rem'>← Strategy</a>"
            f"<h1>Parameters · {_e(s['name'])}</h1><div class='chips'>{chips}</div>"
            "<p class='lede'>Edit the rules, save a new version, run a walk-forward backtest on the same engine the "
            "paper and live runners use, then apply it. Paper applies at once; live needs a completed walk-forward run "
            "and a typed LIVE confirmation. You can also ask the chat, e.g. <i>“widen the stop to 2x ATR”</i>.</p>"
            + (wf_panel(sid, wf_rid) if wf_rid else "")
            + form_html(sid, values, errors, base_id) + versions_html(sid, ov) + "</div>")


def live_confirm_html(sid: int, ov: dict, v: dict, run: Optional[dict], errors=None) -> str:
    lv = ov.get("live_version")
    diff = R.diff_params((lv or ov["versions"][0])["params"], v["params"])
    rows = "".join(f"<tr><td>{_e(R.PARAM_SPEC[k]['label'])}</td><td>{_e(_short(a))}</td><td><b>{_e(_short(b))}</b></td></tr>"
                   for k, a, b in diff) or "<tr><td colspan=3>No parameter changes vs the live version.</td></tr>"
    errs = "".join(f"<li>{_e(x)}</li>" for x in errors or [])
    o = ((run or {}).get("result") or {}).get("oos") or {}
    wf = ("<p class='help'>No completed walk-forward run for this version yet. "
          f"<a href='/strategies/{sid}/params'>Run it from the Parameters page</a>.</p>") if not run else (
        f"<p>Walk-forward (OOS test years chained): return {_f((o.get('cand') or {}).get('total_pct'))}, Sharpe "
        f"{_f((o.get('cand') or {}).get('sharpe'), '{:.2f}')}, max DD {_f((o.get('cand') or {}).get('max_dd_pct'))} · live version "
        f"{_f((o.get('live') or {}).get('total_pct'))} · SPY {_f((o.get('spy') or {}).get('total_pct'))}. "
        f"<a href='/strategies/{sid}/params?wf={run['id']}'>Details</a></p>")
    a = (ov.get("activations") or {}).get("live") or {}
    return (f"<div class='lb sp'><a href='/strategies/{sid}/params' style='font-size:.82rem'>← Parameters</a>"
            f"<h1>Apply v{v['version']} to LIVE</h1>"
            f"<div class='live-warn'><b>Real money.</b> Your live strategy on account <b>{_e(a.get('account_ref'))}</b> "
            f"(orders <code>{_e(a.get('cid_prefix'))}-…</code>, cash only, allocation "
            f"${float(a.get('allocation_usd') or 0):,.2f}) switches from "
            f"v{(lv or {}).get('version', '?')} to v{v['version']} at its next pass. Open positions keep the stops and "
            "targets fixed at their entry.</div>"
            f"<div class='tbl'><table><thead><tr><th>Parameter</th><th>Live now</th><th>New</th></tr></thead><tbody>{rows}"
            f"</tbody></table></div>{wf}"
            + (f"<ul style='color:#9b302b'>{errs}</ul>" if errs else "")
            + f"<form method='post' action='/strategies/{sid}/params/{v['id']}/apply/live' class='lb-form'>"
              "<label style='display:block;margin:.7rem 0'>Type <b>LIVE</b> to confirm<br>"
              "<input name='confirm' required autocomplete='off' style='width:8rem;font-size:16px'></label>"
              "<button class='lb-btn' type='submit' style='background:#b43b35;color:#fff;border-color:#b43b35'>"
              f"Confirm apply to live</button> <a class='lb-btn' href='/strategies/{sid}/params'>Cancel</a></form></div>")


def admin_html(rows: list) -> str:
    tr = "".join(
        f"<tr><td>{_e(str(r.get('created_at'))[:16])}</td><td>{_e(r.get('email'))}</td>"
        f"<td><a href='/strategies/{int(r['user_strategy_id'])}'>#{int(r['user_strategy_id'])} {_e(r.get('strategy_name'))}</a></td>"
        f"<td>v{r['version']} {_e(r['status'])}</td><td>{_e(r.get('source'))}</td>"
        f"<td>{_e('; '.join(f'{k}: {_short(a)}→{_short(b)}' for k, a, b in (r.get('diff') or [])))}</td>"
        f"<td>{_e(r.get('wf_status') or '—')}</td><td>{_e(r.get('applied_to') or '—')}</td></tr>" for r in rows)
    return ("<div class='lb sp' style='max-width:1200px'><h1>Strategy parameter versions</h1>"
            "<p class='lede'>Every version of every user's strategy (newest first). Applies are also in activation_events.</p>"
            "<div class='tbl'><table><thead><tr><th>Created (UTC)</th><th>User</th><th>Strategy</th><th>Version</th>"
            "<th>Source</th><th>Changes</th><th>WF</th><th>Applied to</th></tr></thead><tbody>" + tr
            + "</tbody></table></div></div>")


def _form_values(form) -> Dict[str, Any]:
    out = {}
    for k in R.PARAM_SPEC:
        if k in form:
            out[k] = str(form.get(k) or "").strip()
    return out


def register(app, rt):
    from engine.leaderboard import params as SP
    from engine.web.ph_leaderboard import _not_found, _render, _user, _with_msg_url

    def render(user, title, inner):
        from fasthtml.common import Style
        resp = _render(user, title, "strategies", f"<style>{CSS}</style>" + inner)
        return resp

    def need_user(session, sid):
        user = _user(session)
        if not user:
            return None, RedirectResponse(f"/signin?next=/strategies/{sid}/params", status_code=303)
        return user, None

    @rt("/strategies/{sid}/params", methods=["GET"])
    def params_get(session, request, sid: int, msg: str = "", wf: int = 0):
        user, redir = need_user(session, sid)
        if redir:
            return redir
        try:
            ov = SP.overview(sid, str(user["user_id"]))
        except SP.ParamsError as exc:
            return render(user, "Parameters · AlpaTrade", f"<div class='lb sp'><a href='/strategies/{sid}'>← Strategy</a>"
                          f"<p class='flash err'>{_e(exc)}</p></div>")
        src = ov["latest"]
        frm = request.query_params.get("from")
        if frm and str(frm).isdigit():
            src = next((v for v in ov["versions"] if v["id"] == int(frm)), src)
        return render(user, f"Parameters · {ov['strategy']['name']}",
                      page_html(ov, src["params"], msg=msg, wf_rid=wf or None, base_id=src["id"]))

    @app.post("/strategies/{sid}/params")
    async def params_post(session, request, sid: int):
        user, redir = need_user(session, sid)
        if redir:
            return redir
        form = await request.form()
        vals = _form_values(form)
        base = str(form.get("base_version_id") or "")
        try:
            res = SP.create_version(sid, str(user["user_id"]), vals, source="ui", note=str(form.get("note") or ""),
                                    base_version_id=int(base) if base.isdigit() else None)
        except SP.ParamsError:
            return _not_found()
        if not res["ok"]:
            ov = SP.overview(sid, str(user["user_id"]))
            return render(user, "Parameters · AlpaTrade", page_html(ov, {**ov["latest"]["params"], **vals},
                                                                    errors=res["errors"]))
        v = res["version"]
        m = (f"No changes — still v{v['version']}." if res.get("unchanged") else
             f"Saved v{v['version']} (draft, {len(res['diff'])} change{'s' if len(res['diff']) != 1 else ''}). "
             "Run the walk-forward, then apply it.")
        return RedirectResponse(_with_msg_url(f"/strategies/{sid}/params", m), status_code=303)

    @app.post("/strategies/{sid}/params/{vid}/wf")
    async def params_wf(session, sid: int, vid: int):
        user, redir = need_user(session, sid)
        if redir:
            return redir
        try:
            r = SP.start_wf(sid, str(user["user_id"]), vid)
        except SP.ParamsError:
            return _not_found()
        return RedirectResponse(f"/strategies/{sid}/params?wf={r['run_id']}#wf", status_code=303)

    @rt("/strategies/{sid}/params/wf/{rid}.json", methods=["GET"])
    def params_wf_json(session, sid: int, rid: int):
        user = _user(session)
        if not user:
            return JSONResponse({"error": "sign in"}, status_code=401)
        from engine.rbac import is_admin
        r = SP.wf_status(rid, str(user["user_id"]), admin=is_admin(user))
        if not r or int(r["user_strategy_id"]) != int(sid):
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(json.loads(json.dumps({k: r.get(k) for k in ("id", "status", "progress", "error", "cached",
                                                                          "version_id", "result")}, default=str)))

    @app.post("/strategies/{sid}/params/{vid}/apply/paper")
    async def params_apply_paper(session, sid: int, vid: int):
        user, redir = need_user(session, sid)
        if redir:
            return redir
        try:
            res = SP.apply_version(sid, str(user["user_id"]), vid, "paper")
        except SP.ParamsError:
            return _not_found()
        m = res.get("message") or "; ".join(res.get("errors") or [])
        return RedirectResponse(_with_msg_url(f"/strategies/{sid}/params", m), status_code=303)

    def _live_ctx(user, sid, vid):
        ov = SP.overview(sid, str(user["user_id"]))
        v = next((x for x in ov["versions"] if x["id"] == int(vid)), None)
        return ov, v, (SP.wf_done(v["id"]) if v else None)

    @rt("/strategies/{sid}/params/{vid}/apply/live", methods=["GET"])
    def params_apply_live_get(session, sid: int, vid: int):
        user, redir = need_user(session, sid)
        if redir:
            return redir
        try:
            ov, v, run = _live_ctx(user, sid, vid)
        except SP.ParamsError:
            return _not_found()
        if not v:
            return _not_found()
        return render(user, "Apply to live · AlpaTrade", live_confirm_html(sid, ov, v, run))

    @app.post("/strategies/{sid}/params/{vid}/apply/live")
    async def params_apply_live_post(session, request, sid: int, vid: int):
        user, redir = need_user(session, sid)
        if redir:
            return redir
        form = await request.form()
        try:
            res = SP.apply_version(sid, str(user["user_id"]), vid, "live", str(form.get("confirm") or ""),
                                   plan_check=SP.live_universe_check(sid, str(user["user_id"])))
            if res.get("ok"):
                return RedirectResponse(_with_msg_url(f"/strategies/{sid}/params", res["message"]), status_code=303)
            ov, v, run = _live_ctx(user, sid, vid)
        except SP.ParamsError:
            return _not_found()
        return render(user, "Apply to live · AlpaTrade", live_confirm_html(sid, ov, v, run, res.get("errors")))

    @rt("/admin/strategy-params", methods=["GET"])
    def admin_params(session):
        user = _user(session)
        from engine.rbac import is_admin
        if not user or not is_admin(user):
            return RedirectResponse("/", status_code=303)
        try:
            rows = SP.admin_versions()
        except Exception as exc:  # noqa: BLE001
            log.warning("admin versions failed: %s", type(exc).__name__)
            rows = []
        return render(user, "Strategy parameter versions · Admin", admin_html(rows))

    return ["/strategies/{sid}/params"]
