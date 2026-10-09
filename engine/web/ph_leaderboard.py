"""Strategy Leaderboard + user strategies (``/leaderboard``, ``/strategies`` …).

* ``/leaderboard`` (public): every *public* strategy — name, user, description, annualised
  return, period running and alpha vs SPY — with Copy for ChatGPT, Copy for Claude and
  Clone into AlpaTrade. Figures are computed live from the owner's live runner run
  (:mod:`engine.leaderboard.perf`); a strategy without live data shows "—".
* ``/strategies`` (signed in): the user's own strategies (several allowed), each private or
  public, with a one-click public/private toggle, edit and delete.
* ``/strategies/{id}``: strategy page (public, or the owner's private one) with the full
  single-markdown strategy skill; ``/strategies/{id}/skill.md`` downloads it.
* ``POST /strategies/{id}/clone``: in-app clone into the signed-in user's strategies,
  private by default.

Mobile: the Leaderboard renders as stacked cards below 760px; hover tooltips become tap
toasts on touch screens, and the compounded figure is shown as secondary text.
"""
from __future__ import annotations

import html
import json
import logging
from typing import Optional

from fasthtml.common import Div, NotStr, Section, Style
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from engine.leaderboard import perf as lperf
from engine.leaderboard import store
from engine.leaderboard.skill import chat_prompt, copy_text

log = logging.getLogger(__name__)

LB_CSS = """
.lb{width:100%;max-width:1160px;margin:0 auto;padding:2rem 1.5rem 3rem;color:var(--ink)}
.lb h1{font-size:clamp(1.5rem,3.2vw,2.2rem);font-weight:600;letter-spacing:-.02em;margin:.3rem 0 .4rem}
.lb .lede{color:var(--ink-muted);font-size:.95rem;line-height:1.55;max-width:46rem;margin:0 0 1.4rem}
.lb .eyebrow{font-family:var(--font-mono);font-size:.7rem;letter-spacing:.16em;text-transform:uppercase;color:var(--accent)}
.lb a{color:var(--accent)}
.lb .flash{background:var(--accent-dim);color:var(--accent-deep,#164a35);border-radius:.55rem;padding:.65rem .9rem;font-size:.86rem;margin:0 0 1rem}
.lb .flash.err{background:#fff0ee;color:#9b302b}
.lb-list{border:1px solid var(--line);border-radius:.9rem;background:var(--bg-elev);overflow:hidden}
.lb-row{display:grid;grid-template-columns:2rem minmax(0,2.8fr) minmax(0,1fr) minmax(0,1.15fr) minmax(0,1.1fr) minmax(0,1.05fr);
 gap:.4rem 1.1rem;padding:1.05rem 1.15rem;border-top:1px solid var(--line);align-items:start}
.lb-row:first-child{border-top:0}
.lb-head{font-size:.66rem;text-transform:uppercase;letter-spacing:.09em;color:var(--ink-dim);background:var(--bg);padding:.65rem 1.15rem}
.lb-rank{font-family:var(--font-mono);font-weight:700;color:var(--ink-dim);font-size:.95rem;padding-top:.1rem}
.lb-name a{font-weight:650;color:var(--ink);text-decoration:none;font-size:1rem}
.lb-name a:hover{color:var(--accent)}
.lb-desc{color:var(--ink-muted);font-size:.84rem;line-height:1.5;margin-top:.25rem}
.lb-cell{font-size:.86rem}
.lb-l{display:none}
.lb-v{font-weight:650;font-variant-numeric:tabular-nums;font-size:1rem}
.lb-v[data-tip]{cursor:help;border-bottom:1px dotted var(--line-br)}
.lb-sub{display:block;color:var(--ink-muted);font-size:.76rem;margin-top:.15rem;font-variant-numeric:tabular-nums}
.lb-sub.m{display:none}
.lb .pos{color:#147a4b}.lb .neg{color:#b43b35}
.lb-actions{grid-column:2/-1;display:flex;flex-wrap:wrap;gap:.5rem;margin-top:.55rem}
.lb-skill-h{display:flex;align-items:center;gap:.6rem}
.lb-copy{display:inline-flex;align-items:center;gap:.3rem;border:1px solid var(--line-br);background:var(--bg-elev);color:var(--ink);
 border-radius:.45rem;padding:.2rem .5rem;font-size:.75rem;font-weight:500;cursor:pointer}.lb-copy:hover{border-color:var(--accent);color:var(--accent)}
.lb-btn.ai svg{height:15px;width:auto;display:block;flex:none}.lb-btn.ai svg path{fill:currentColor}
.lb-det{margin:1.2rem 0}.lb-det h2{font-size:1rem;margin:1.1rem 0 .4rem}.lb-det .chart{height:300px;width:100%}
.lb-det .chart.small{height:200px}.lb-det table{border-collapse:collapse;font-size:.82rem}
.lb-det td,.lb-det th{padding:.25rem .7rem .25rem 0;text-align:left;border-bottom:1px solid var(--line)}
.lb-det pre{white-space:pre-wrap;font-size:.78rem;background:var(--bg-elev);border:1px solid var(--line);padding:.7rem;border-radius:.5rem;max-height:420px;overflow:auto}
.lb-btn{display:inline-flex;align-items:center;justify-content:center;gap:.35rem;border:1px solid var(--line-br);background:var(--bg-elev);
 color:var(--ink);border-radius:2rem;padding:.42rem .9rem;font-size:.8rem;font-weight:550;cursor:pointer;text-decoration:none;
 font-family:inherit;line-height:1.2;min-height:36px}
.lb-btn:hover{border-color:var(--accent);color:var(--accent)}
.lb-btn.primary{background:var(--accent);border-color:var(--accent);color:var(--bg-elev)}
.lb-btn.primary:hover{background:var(--ink);border-color:var(--ink);color:var(--bg-elev)}
.lb-btn.danger{color:#9b302b}
.lb-actions form{margin:0;display:inline-flex}
.lb-note{color:var(--ink-dim);font-size:.76rem;line-height:1.55;margin:1rem 0 0;max-width:62rem}
.lb-band{margin-top:1.6rem;border:1px solid var(--line);border-radius:.9rem;background:var(--bg-elev);padding:1.2rem 1.25rem;
 display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:.8rem}
.lb-band b{display:block;font-size:1rem}.lb-band span{color:var(--ink-muted);font-size:.85rem}
.lb-empty{padding:1.6rem;text-align:center;color:var(--ink-muted);font-size:.9rem}
.lb-badge{display:inline-block;font-size:.66rem;font-weight:650;border-radius:1rem;padding:.1rem .5rem;border:1px solid var(--line-br);
 color:var(--ink-muted);vertical-align:middle;margin-left:.35rem;text-transform:uppercase;letter-spacing:.05em}
.lb-badge.pub{border-color:var(--accent);color:var(--accent)}
.lb-badge.live{border-color:#b43b35;color:#b43b35}
.lb-badge.bt{border-color:#7a5a12;color:#7a5a12;background:#fff7e0}
.lb-src{display:inline-block;margin-top:.3rem;font-size:.76rem;color:var(--ink-muted);overflow-wrap:anywhere}
.lb-src a{color:var(--accent)}
.lb-filters{display:flex;flex-wrap:wrap;align-items:center;gap:.45rem;margin:0 0 .9rem}
.lb-pill{display:inline-flex;align-items:center;gap:.3rem;border:1px solid var(--line-br);border-radius:2rem;padding:.32rem .8rem;
 font-size:.8rem;color:var(--ink);text-decoration:none;background:var(--bg-elev);min-height:34px;box-sizing:border-box}
.lb-pill.on{background:var(--ink);border-color:var(--ink);color:var(--bg-elev)}
.lb-pill small{opacity:.7}
.lb-filters form{display:flex;gap:.4rem;margin:0 0 0 auto}
.lb-filters input[type=search]{border:1px solid var(--line-br);border-radius:2rem;padding:.35rem .8rem;font:inherit;font-size:.82rem;
 background:var(--bg-elev);color:var(--ink);min-width:12rem}
.lb-pager{display:flex;align-items:center;justify-content:center;gap:.8rem;margin:1rem 0 0;font-size:.84rem;color:var(--ink-muted)}
.lb-pager a{min-height:40px;display:inline-flex;align-items:center}
.lb-count{font-size:.8rem;color:var(--ink-muted);margin:0 0 .5rem}
.lb-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.7rem;margin:1.1rem 0}
.lb-kpi{background:var(--bg-elev);border:1px solid var(--line);border-radius:.7rem;padding:.85rem .95rem}
.lb-kpi .k{font-size:.66rem;text-transform:uppercase;letter-spacing:.08em;color:var(--ink-dim)}
.lb-kpi .lb-v{display:inline-block;margin-top:.25rem;font-size:1.25rem}
.lb-md{background:var(--bg-elev);border:1px solid var(--line);border-radius:.9rem;padding:1.1rem 1.3rem;margin-top:1.2rem;
 font-size:.9rem;line-height:1.6;overflow-wrap:anywhere}
.lb-md pre{background:var(--bg);border:1px solid var(--line);border-radius:.5rem;padding:.8rem;overflow-x:auto;font-size:.78rem;white-space:pre}
.lb-md code{font-family:var(--font-mono);font-size:.82em}
.lb-md h1{font-size:1.3rem}.lb-md h2{font-size:1.1rem;margin-top:1.3rem}.lb-md h3{font-size:.98rem}
.lb-form{display:grid;gap:.9rem;max-width:52rem}
.lb-form label{display:grid;gap:.3rem;font-size:.82rem;font-weight:600}
.lb-form label small{font-weight:400;color:var(--ink-muted)}
.lb-form input[type=text],.lb-form textarea{width:100%;box-sizing:border-box;border:1px solid var(--line-br);border-radius:.55rem;
 padding:.6rem .7rem;font:inherit;font-size:.9rem;background:var(--bg-elev);color:var(--ink)}
.lb-form textarea.code{font-family:var(--font-mono);font-size:.78rem;min-height:22rem}
.lb-form .chk{display:flex;align-items:center;gap:.5rem;font-weight:500}
.lb-toast{position:fixed;left:50%;bottom:1.2rem;transform:translateX(-50%) translateY(150%);background:var(--ink);color:var(--bg-elev);
 padding:.7rem 1rem;border-radius:.6rem;font-size:.84rem;line-height:1.45;max-width:min(92vw,34rem);z-index:9999;opacity:0;
 transition:all .22s ease;box-shadow:0 8px 24px rgba(0,0,0,.18)}
.lb-toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
@media(max-width:760px){
 .lb{padding:1.2rem 1rem 2.4rem}
 .lb-head{display:none}
 .lb-list{border:0;background:transparent;display:grid;gap:.8rem}
 .lb-row{grid-template-columns:minmax(0,1fr) minmax(0,1fr);border:1px solid var(--line);border-radius:.9rem;background:var(--bg-elev);
  padding:1rem;gap:.75rem .9rem;position:relative}
 .lb-row:first-child{border-top:1px solid var(--line)}
 .lb-rank{position:absolute;top:.85rem;right:.95rem;font-size:.78rem;background:var(--bg);border:1px solid var(--line);
  border-radius:1rem;padding:.05rem .5rem}
 .lb-name{grid-column:1/-1;padding-right:2.6rem}
 .lb-l{display:block;font-size:.64rem;text-transform:uppercase;letter-spacing:.08em;color:var(--ink-dim);margin-bottom:.15rem}
 .lb-sub.m{display:block}
 .lb-actions{grid-column:1/-1;display:grid;grid-template-columns:1fr 1fr;gap:.5rem;margin-top:.2rem}
 .lb-actions .wide,.lb-actions form{grid-column:1/-1}
 .lb-actions form .lb-btn{width:100%}
 .lb-btn{min-height:44px;font-size:.84rem}
 .lb-strip{grid-template-columns:repeat(2,minmax(0,1fr))}
 .lb-band{flex-direction:column;align-items:stretch}
 .lb-md{padding:.9rem}
 .lb-form input[type=text]{min-height:44px;font-size:16px}  /* tap target; no iOS zoom */
 .lb-pill{min-height:40px}
 .lb-filters form{margin:0;width:100%}
 .lb-filters input[type=search]{flex:1;min-width:0;min-height:44px;font-size:16px}
}
"""

LB_JS = """
<script>
(function(){
var AI={chatgpt:{q:'https://chatgpt.com/?q=',home:'https://chatgpt.com/',name:'ChatGPT'},
        claude:{q:'https://claude.ai/new?q=',home:'https://claude.ai/new',name:'Claude'},
        grok:{q:'https://grok.com/?q=',home:'https://grok.com/',name:'Grok'}};
function toast(m){var t=document.getElementById('lb-toast');if(!t){t=document.createElement('div');t.id='lb-toast';
 t.className='lb-toast';t.setAttribute('role','status');document.body.appendChild(t)}t.textContent=m;t.classList.add('show');
 clearTimeout(t._h);t._h=setTimeout(function(){t.classList.remove('show')},Math.max(3800,m.length*45))}
function md(id){var n=document.getElementById('lb-md-'+id);try{return n?JSON.parse(n.textContent):''}catch(e){return ''}}
function copyText(t){if(navigator.clipboard&&window.isSecureContext)return navigator.clipboard.writeText(t);
 return new Promise(function(ok,no){var a=document.createElement('textarea');a.value=t;a.style.position='fixed';a.style.opacity='0';
 document.body.appendChild(a);a.select();var r=false;try{r=document.execCommand('copy')}catch(e){}a.remove();r?ok():no()})}
var MAXURL=6000;  /* prefill limit: longer ?q= URLs get truncated or rejected by the chat sites */
function page(id){return location.origin+'/strategies/'+id}
window.lbPrefill=function(id,p,t){var b=AI[p],full=b.q+encodeURIComponent(t);if(full.length<=MAXURL)return {url:full,full:true};
 var short='I am looking at this AlpaTrade trading-strategy skill: '+page(id)+' (raw SKILL.md: '+page(id)+'/skill.md). '+
  'I have copied the full SKILL.md to my clipboard and will paste it in my next message. '+
  'Once I do, explain the strategy, its exact rules and its main risks.';
 return {url:b.q+encodeURIComponent(short),full:false}};
window.lbCopy=function(id,p){var t=md(id);if(!t)return;var b=AI[p],r=lbPrefill(id,p,t);
 copyText(t).then(function(){toast(r.full?'Copied \u2014 opening '+b.name+' with the strategy prefilled'
   :'Copied \u2014 '+b.name+' opens with a short prompt; paste (Ctrl/\u2318+V) the full SKILL.md there')})
  .catch(function(){toast(r.full?'Opening '+b.name+' with the strategy prefilled':'Copy failed \u2014 '+b.name+' gets the page link; use Download .md')});
 window.open(r.url,'_blank','noopener')};
window.lbCopyRaw=function(id){var t=md(id);if(!t)return;copyText(t).then(function(){toast('Copied')})
 .catch(function(){toast('Copy failed \u2014 use Download .md')})};
window.lbChat=function(prompt){try{sessionStorage.setItem('alpatrade.pendingPrompt',prompt)}catch(e){}window.location.href='/app'};
window.lbToast=toast;
document.addEventListener('click',function(e){var el=e.target.closest&&e.target.closest('[data-tip]');
 if(el&&el.dataset.tip&&window.matchMedia('(hover: none)').matches)toast(el.dataset.tip)});
document.querySelectorAll('[data-md-render]').forEach(function(el){if(!window.marked)return;
 try{var src=JSON.parse(document.getElementById(el.dataset.mdRender).textContent);
 src=src.replace(/^---\\n[\\s\\S]*?\\n---\\n/,'');el.innerHTML=window.marked.parse(src.replace(/</g,'&lt;'))}catch(e){}});
})();
</script>
"""

_SIGNIN_MSG = "Sign in (or create a free account) to clone strategies into AlpaTrade."


def _e(v) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def _cls(v) -> str:
    return "" if v is None else ("pos" if v > 0 else "neg" if v < 0 else "")


def _json_script(el_id: str, value) -> str:
    payload = json.dumps(value).replace("</", "<\\/")
    return f"<script type='application/json' id='{_e(el_id)}'>{payload}</script>"


def _user(session) -> Optional[dict]:
    from engine.web.ph_auth import current_user
    try:
        return current_user(session)
    except Exception:  # noqa: BLE001
        return None


# ── fragments ───────────────────────────────────────────────────────────────
def _annualised_cell(m: dict, label: bool = True) -> str:
    v = m.get("annualised_pct")
    sub = (f"<span class='lb-sub'>compounded {lperf.pct(m.get('annualised_compound_pct'))}</span>"
           if m.get("annualised_compound_pct") is not None else "")
    sub_m = sub.replace("class='lb-sub'", "class='lb-sub m'")
    return ((f"<span class='lb-l'>Annualised return</span>" if label else "")
            + f"<span class='lb-v {_cls(v)}' data-tip='{_e(lperf.annualised_tip(m))}' "
              f"title='{_e(lperf.annualised_tip(m))}'>"
              f"{lperf.pct(v)}</span>" + sub_m)


def _alpha_cell(m: dict, label: bool = True) -> str:
    v = m.get("alpha_pct")
    if m.get("is_backtest"):
        sub = (f"<span class='lb-sub'>annualised · CAGR {lperf.pct(m.get('annualised_pct'))} vs SPY "
               f"{lperf.pct(m.get('spy_annualised_pct'))}</span>" if v is not None else "")
    else:
        sub = (f"<span class='lb-sub'>return {lperf.pct(m.get('return_pct'))} · SPY "
               f"{lperf.pct(m.get('spy_return_pct'))}</span>" if v is not None else "")
    return ((f"<span class='lb-l'>Alpha vs SPY</span>" if label else "")
            + f"<span class='lb-v {_cls(v)}' data-tip='{_e(lperf.alpha_tip(m))}' "
              f"title='{_e(lperf.alpha_tip(m))}'>{lperf.pct(v)}</span>" + sub)


def _period_cell(m: dict, label: bool = True) -> str:
    """Backtest period instead of "Running" for kind='backtest' strategies."""
    if not m.get("start_date"):
        body = "<span class='lb-v'>—</span>"
    else:
        body = (f"<span class='lb-v' style='font-size:.9rem'>{_e(lperf.fmt_day(m['start_date']))} – "
                f"{_e(lperf.fmt_day(m['as_of']))}</span><span class='lb-sub'>backtest"
                + (f" · {m['trading_days']} trading days" if m.get("trading_days") else "") + "</span>")
    return (f"<span class='lb-l'>Backtest period</span>" if label else "") + body


def _bt_badge(s: dict) -> str:
    return ("<span class='lb-badge bt' title='Hypothetical backtest on historical data — never "
            "traded live'>Backtest</span>" if store.is_backtest(s) else "")


def _episodes(s: dict) -> list[dict]:
    bm = s.get("backtest_metrics") if isinstance(s.get("backtest_metrics"), dict) else {}
    return [e for e in (bm.get("episodes") or [])
            if isinstance(e, dict) and str(e.get("url", "")).startswith(("https://", "http://"))]


def _source(s: dict, full: bool = False) -> str:
    url = (s.get("source_url") or "").strip()
    if not url.startswith(("https://", "http://")):
        return ""
    label = s.get("source") or url.split("/")[2]
    eps = _episodes(s)
    if full and len(eps) > 1:
        links = " · ".join(f"<a href='{_e(e['url'])}' target='_blank' rel='noopener nofollow' "
                           f"title='{_e(e.get('title'))}'>ep. {_e(e.get('episode'))} ↗</a>" for e in eps)
        return f"<div class='lb-src'>Sources ({_e(label)}): {links}</div>"
    more = f" · {len(eps)} episodes" if len(eps) > 1 else ""
    return (f"<div class='lb-src'>Source: <a href='{_e(url)}' target='_blank' "
            f"rel='noopener nofollow'>{_e(label)} ↗</a>{more}</div>")


def _running_cell(m: dict, label: bool = True) -> str:
    if m.get("is_backtest"):
        return _period_cell(m, label)
    if not m.get("start_date"):
        body = "<span class='lb-v'>—</span>"
    else:
        d = m.get("days_running")
        body = (f"<span class='lb-v' style='font-size:.9rem'>Since {_e(lperf.fmt_day(m['start_date']))}</span>"
                f"<span class='lb-sub'>{d} day{'s' if d != 1 else ''} running"
                + (f" · {m['trading_days']} trading" if m.get("trading_days") else "") + "</span>")
    return (f"<span class='lb-l'>Running</span>" if label else "") + body


def _actions(s: dict, user: Optional[dict], *, wide_view: bool = False) -> str:
    sid = int(s["id"])
    from engine.web.ai_logos import ANTHROPIC_SVG, GROK_SVG, OPENAI_SVG
    out = [f"<a class='lb-btn view' href='/strategies/{sid}#details'>View more</a>",
           f"<button type='button' class='lb-btn ai' onclick='lbCopy({sid},\"chatgpt\")'>{OPENAI_SVG}Copy for ChatGPT</button>",
           f"<button type='button' class='lb-btn ai' onclick='lbCopy({sid},\"claude\")'>{ANTHROPIC_SVG}Copy for Claude</button>",
           f"<button type='button' class='lb-btn ai' onclick='lbCopy({sid},\"grok\")'>{GROK_SVG}Copy for Grok</button>"]
    own = bool(user and str(user.get("user_id")) == s.get("user_id"))
    if not own:
        out.append(f"<form method='post' action='/strategies/{sid}/clone'>"
                   "<button type='submit' class='lb-btn primary'>⑂ Clone into AlpaTrade</button></form>")
    if wide_view:
        out.append(f"<a class='lb-btn wide' href='/strategies/{sid}/skill.md'>Download .md</a>")
    return "<div class='lb-actions'>" + "".join(out) + "</div>"


def _row(rank: int, s: dict, m: dict, user: Optional[dict]) -> str:
    sid = int(s["id"])
    return (f"<div class='lb-row' id='strategy-{sid}'>"
            f"<div class='lb-rank'>{rank}</div>"
            f"<div class='lb-name'><a href='/strategies/{sid}'>{_e(s['name'])}</a>{_bt_badge(s)}"
            f"<div class='lb-desc'>{_e(s.get('description'))}</div>{_source(s)}</div>"
            f"<div class='lb-cell'><span class='lb-l'>User</span>{_e(s['author'])}</div>"
            f"<div class='lb-cell'>{_annualised_cell(m)}</div>"
            f"<div class='lb-cell'>{_running_cell(m)}</div>"
            f"<div class='lb-cell'>{_alpha_cell(m)}</div>"
            + _actions(s, user)
            + _json_script(f"lb-md-{sid}", copy_text(s))
            + "</div>")


_METHOD_NOTE = (
    "Annualised return = (1+r)^(252/d)−1, where r is the time-weighted return since the strategy "
    "went live (deposits and withdrawals excluded) and d the trading days; over a short period it "
    "is very sensitive (hover for the simple r×252/d figure). Alpha = strategy return minus "
    "SPY's return over the same period. Figures are computed live from each strategy's AlpaTrade "
    "live run (account equity and SPY at the latest session close; tap or hover a figure for the "
    "as-of date); \"—\" means no live track record yet. Past performance over a short period says "
    "little about the future. Strategies marked Backtest are hypothetical: their figures come "
    "from a daily-bar backtest (annualised = CAGR over the stated period, cash only, slippage "
    "included; alpha = CAGR minus SPY's CAGR over the same period), they were never traded live and "
    "are listed after live strategies. Backtests use today's S&P 500 members, which flatters "
    "momentum and relative-strength rules in particular (survivorship bias). Not investment advice.")


PAGE_SIZE = 25


def _src_label(s: dict) -> str:
    return (s.get("source") or "AlpaTrade").strip() or "AlpaTrade"


def filter_rows(rows, kind: str = "", source: str = "", q: str = ""):
    """(rank, strategy, metrics) after the Live/Backtest, source and text filters.
    Ranks are positions in the full Leaderboard, so they don't change with filters."""
    out = []
    q = (q or "").strip().lower()
    for i, (s, m) in enumerate(rows):
        if kind == "live" and store.is_backtest(s):
            continue
        if kind == "backtest" and not store.is_backtest(s):
            continue
        if source and _src_label(s) != source:
            continue
        if q and q not in f"{s.get('name', '')} {s.get('author', '')} {s.get('description', '')}".lower():
            continue
        out.append((i + 1, s, m))
    return out


def _qs(**kw) -> str:
    from urllib.parse import urlencode
    kv = {k: v for k, v in kw.items() if v not in (None, "", 1, "1")}
    return ("?" + urlencode(kv)) if kv else ""


def _filters_html(rows, kind, source, q) -> str:
    n_all = len(rows)
    n_bt = sum(1 for s, _ in rows if store.is_backtest(s))
    pills = []
    for val, label, n in (("", "All", n_all), ("live", "Live", n_all - n_bt), ("backtest", "Backtest", n_bt)):
        on = " on" if kind == val else ""
        pills.append(f"<a class='lb-pill{on}' href='/leaderboard{_qs(kind=val, source=source, q=q)}'>"
                     f"{label} <small>{n}</small></a>")
    sources = sorted({_src_label(s) for s, _ in rows})
    if len(sources) > 1:
        for src in sources:
            on = " on" if source == src else ""
            nxt = "" if source == src else src
            pills.append(f"<a class='lb-pill{on}' href='/leaderboard{_qs(kind=kind, source=nxt, q=q)}'>"
                         f"{_e(src)}</a>")
    form = ("<form method='get' action='/leaderboard' role='search'>"
            + (f"<input type='hidden' name='kind' value='{_e(kind)}'>" if kind else "")
            + (f"<input type='hidden' name='source' value='{_e(source)}'>" if source else "")
            + f"<input type='search' name='q' value='{_e(q)}' placeholder='Search trader or strategy' "
              "aria-label='Search strategies'></form>")
    return "<nav class='lb-filters' aria-label='Filter strategies'>" + "".join(pills) + form + "</nav>"


def leaderboard_html(rows: list[tuple[dict, dict]], user: Optional[dict], msg: str = "",
                     error: str = "", kind: str = "", source: str = "", q: str = "",
                     page: int = 1) -> str:
    kind = kind if kind in ("live", "backtest") else ""
    shown = filter_rows(rows, kind, source, q)
    pages = max(1, -(-len(shown) // PAGE_SIZE))
    page = min(max(1, int(page or 1)), pages)
    chunk = shown[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
    head = ("<div class='lb-row lb-head'><div>#</div><div>Strategy</div><div>User</div>"
            "<div>Annualised return</div><div>Running / period</div><div>Alpha vs SPY</div></div>")
    body = "".join(_row(r, s, m, user) for r, s, m in chunk) or \
        ("<div class='lb-empty'>No strategies match these filters.</div>" if rows
         else "<div class='lb-empty'>No public strategies yet.</div>")
    count = (f"<p class='lb-count'>{len(shown)} strateg{'y' if len(shown) == 1 else 'ies'}"
             + (f" · page {page} of {pages}" if pages > 1 else "") + "</p>")
    pager = ""
    if pages > 1:
        prev = (f"<a class='lb-btn' href='/leaderboard{_qs(kind=kind, source=source, q=q, page=page - 1)}'>← Previous</a>"
                if page > 1 else "")
        nxt = (f"<a class='lb-btn' href='/leaderboard{_qs(kind=kind, source=source, q=q, page=page + 1)}'>Next →</a>"
               if page < pages else "")
        pager = f"<nav class='lb-pager' aria-label='Pages'>{prev}<span>Page {page} of {pages}</span>{nxt}</nav>"
    as_ofs = sorted({m["as_of"] for _, m in rows if m.get("as_of") and not m.get("is_backtest")})
    latest = (f" Latest data: session close {lperf.fmt_day(as_ofs[-1])}." if as_ofs else "")
    flash = (f"<div class='flash err'>{_e(error)}</div>" if error else "") + \
            (f"<div class='flash'>{_e(msg)}</div>" if msg else "")
    if user:
        band = ("<div class='lb-band'><div><b>Your strategies</b><span>Add strategies, keep them "
                "private, or publish them here.</span></div>"
                "<a class='lb-btn primary' href='/strategies'>My strategies →</a></div>")
    else:
        band = ("<div class='lb-band'><div><b>Share your strategy</b><span>Sign in to clone "
                "strategies, add your own, keep them private or publish them here.</span></div>"
                "<a class='lb-btn primary' href='/signin'>Sign in</a></div>")
    return (f"<div class='lb' id='leaderboard'>{flash}<span class='eyebrow'>Strategies</span>"
            "<h1>Leaderboard</h1>"
            "<p class='lede'>Public trading strategies with a live track record, ranked by "
            "annualised return, followed by clearly marked backtests of strategies traders have "
            "described in public (e.g. on Chat With Traders). Copy any strategy into ChatGPT or Claude as a ready-made skill, or "
            "clone it into your own AlpaTrade strategies to backtest and paper-trade it.</p>"
            + _filters_html(rows, kind, source, q) + count
            + f"<div class='lb-list'>{head}{body}</div>{pager}"
            f"<p class='lb-note'>{_METHOD_NOTE}{latest}</p>{band}</div>{LB_JS}")


COPY_SVG = ("<svg viewBox='0 0 24 24' width='15' height='15' fill='none' stroke='currentColor' stroke-width='2' "
            "stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><rect x='9' y='9' width='13' height='13' "
            "rx='2' ry='2'></rect><path d='M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1'></path></svg>")

_PLOTLY = "<script src='https://cdn.plot.ly/plotly-2.35.2.min.js'></script>"


def detail_html(s: dict, m: dict, det: Optional[dict]) -> str:
    """'View more' section: equity vs SPY (base 100), drawdown, daily returns + trade markers,
    parameters, description/prompt and the copyable skill."""
    sid = int(s["id"])
    det = det or {}
    ser = det.get("series") or {}
    bt = bool(m.get("is_backtest"))
    parts = ["<section class='lb-det' id='details'><h2>Equity curve vs SPY "
             f"<span class='muted' style='font-weight:400;font-size:.78rem'>(base 100"
             f"{', deposit-adjusted time-weighted' if not bt else ', backtest'})</span></h2>"]
    if ser.get("dates"):
        payload = json.dumps({"s": ser, "trades": det.get("trades") or [], "bt": bt}).replace("</", "<\\/")
        parts.append(f"<div id='lb-eq-{sid}' class='chart'></div><h2>Drawdown</h2>"
                     f"<div id='lb-dd-{sid}' class='chart small'></div>"
                     + ("" if bt else f"<h2>Daily returns</h2><div id='lb-dr-{sid}' class='chart small'></div>")
                     + f"<script type='application/json' id='lb-det-{sid}'>{payload}</script>"
                     + _PLOTLY + _DETAIL_JS.replace("__SID__", str(sid)))
        if det.get("cash_flows_ok") is False:
            parts.append("<p class='lb-note'>Deposit/withdrawal history unavailable: the curve may include transfers.</p>")
    else:
        parts.append("<p class='lb-note'>No equity curve stored for this strategy yet.</p>")
    tr = det.get("trades") or []
    if tr:
        def _pl(v):
            return "—" if v is None else f"{v:+,.2f}"
        rows = "".join(f"<tr><td>{_e(t['symbol'])}</td><td>{_e(t.get('entry'))}</td><td>{_e(t.get('exit') or 'open')}</td>"
                       f"<td>{_pl(t.get('pnl'))}</td></tr>" for t in tr[-30:])
        parts.append(f"<h2>Trades ({len(tr)})</h2><table><tr><th>Symbol</th><th>Entry</th><th>Exit</th><th>P&amp;L $</th></tr>{rows}</table>")
    cfg = det.get("config") or {}
    if cfg.get("params"):
        src = (f"alpatrade.strategy_configs <code>{_e(cfg.get('name'))}</code> v{_e(cfg.get('version'))}"
               if cfg.get("version") else "skill Parameters block")
        parts.append(f"<h2>Parameters</h2><p class='lb-note' style='margin:0'>From {src}.</p>"
                     f"<pre>{_e(json.dumps({'params': cfg.get('params'), 'execution': cfg.get('execution')}, indent=2, default=str))}</pre>")
    parts.append(f"<h2>Strategy prompt</h2><p>{_e(s.get('description'))}</p>"
                 "<h2 class='lb-skill-h'>Skill (SKILL.md) "
                 f"<button type='button' class='lb-copy' onclick='lbCopyRaw({sid})' title='Copy SKILL.md to clipboard' "
                 f"aria-label='Copy SKILL.md to clipboard'>{COPY_SVG}<span>Copy</span></button></h2>"
                 "</section>")
    return "".join(parts)


_DETAIL_JS = """<script>(function(){var n=document.getElementById('lb-det-__SID__');if(!n||!window.Plotly)return;
var d=JSON.parse(n.textContent),s=d.s,L={margin:{l:40,r:10,t:10,b:30},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',
legend:{orientation:'h'},xaxis:{type:'date'}},C={displayModeBar:false,responsive:true};
var tr=[{x:s.dates,y:s.index,name:d.bt?'Strategy (backtest)':'Account (TWR)',line:{color:'#1F5D43',width:2}}];
if(s.spy_index&&s.spy_index.some(function(v){return v!=null}))tr.push({x:s.dates,y:s.spy_index,name:'SPY',line:{color:'#7A867E'}});
var pos={};s.dates.forEach(function(x,i){pos[x]=s.index[i]});var bx=[],by=[],bt=[],sx=[],sy=[],st=[];
(d.trades||[]).forEach(function(t){if(t.entry&&pos[t.entry]!=null){bx.push(t.entry);by.push(pos[t.entry]);bt.push('Buy '+t.symbol)}
 if(t.exit&&pos[t.exit]!=null){sx.push(t.exit);sy.push(pos[t.exit]);st.push('Sell '+t.symbol+(t.pnl!=null?' '+t.pnl.toFixed(2):''))}});
if(bx.length)tr.push({x:bx,y:by,text:bt,mode:'markers',name:'Buys',marker:{symbol:'triangle-up',color:'#147a4b',size:9},hoverinfo:'text+x'});
if(sx.length)tr.push({x:sx,y:sy,text:st,mode:'markers',name:'Sells',marker:{symbol:'triangle-down',color:'#b43b35',size:9},hoverinfo:'text+x'});
Plotly.newPlot('lb-eq-__SID__',tr,L,C);
Plotly.newPlot('lb-dd-__SID__',[{x:s.dates,y:s.drawdown_pct,fill:'tozeroy',name:'Drawdown %',line:{color:'#b43b35'}}],L,C);
if(document.getElementById('lb-dr-__SID__'))Plotly.newPlot('lb-dr-__SID__',[{x:s.dates,y:s.daily_return_pct,type:'bar',name:'Daily return %',
 marker:{color:s.daily_return_pct.map(function(v){return v>=0?'#147a4b':'#b43b35'})}}],L,C);})();</script>"""


def strategy_html(s: dict, m: dict, user: Optional[dict], msg: str = "", det: Optional[dict] = None) -> str:
    sid = int(s["id"])
    own = bool(user and str(user.get("user_id")) == s.get("user_id"))
    badges = ("<span class='lb-badge pub'>Public</span>" if s.get("is_public")
              else "<span class='lb-badge'>Private</span>")
    if s.get("live_strategy_slug") and m.get("has_data"):
        badges += "<span class='lb-badge live'>Live</span>"
    if s.get("cloned_from_id"):
        badges += f"<span class='lb-badge'>Clone of #{int(s['cloned_from_id'])}</span>"
    badges += _bt_badge(s)
    if m.get("is_backtest"):
        return _strategy_backtest_html(s, m, user, badges, msg, det)
    strip = ("<div class='lb-strip'>"
             f"<div class='lb-kpi'><div class='k'>Annualised return</div>{_annualised_cell(m, False)}</div>"
             f"<div class='lb-kpi'><div class='k'>Alpha vs SPY</div>{_alpha_cell(m, False)}</div>"
             f"<div class='lb-kpi'><div class='k'>Return since start</div><span class='lb-v {_cls(m.get('return_pct'))}'>"
             f"{lperf.pct(m.get('return_pct'))}</span><span class='lb-sub'>as of "
             f"{_e(lperf.fmt_day(m.get('as_of')))} close</span></div>"
             f"<div class='lb-kpi'><div class='k'>Running</div>{_running_cell(m, False)}</div></div>")
    owner_bar = ""
    if own:
        nxt = "false" if s.get("is_public") else "true"
        owner_bar = ("<div class='lb-actions' style='margin:.2rem 0 0'>"
                     f"<form method='post' action='/strategies/{sid}/visibility'>"
                     f"<input type='hidden' name='public' value='{nxt}'>"
                     f"<button class='lb-btn' type='submit'>{'Make private' if s.get('is_public') else 'Make public'}</button></form>"
                     f"<a class='lb-btn' href='/strategies/{sid}/edit'>Edit</a>"
                     f"<button type='button' class='lb-btn' onclick='lbChat({_e(json.dumps(chat_prompt(s)))})'>"
                     "Backtest in AlpaTrade chat</button></div>")
    flash = f"<div class='flash'>{_e(msg)}</div>" if msg else ""
    return (f"<div class='lb'>{flash}<a href='/leaderboard' style='font-size:.82rem'>← Leaderboard</a>"
            f"<h1>{_e(s['name'])}{badges}</h1>"
            f"<p class='lede' style='margin-bottom:.4rem'>by <b>{_e(s['author'])}</b> · {_e(s.get('description'))}</p>"
            + strip + _actions(s, user, wide_view=True).replace("class='lb-actions'", "class='lb-actions' style='margin:0'")
            + owner_bar
            + f"<div class='lb-md' data-md-render='lb-md-{sid}'><pre>{_e(copy_text(s))}</pre></div>"
            + _json_script(f"lb-md-{sid}", copy_text(s))
            + (detail_html(s, m, det) if det is not None else "")
            + f"<p class='lb-note'>{_METHOD_NOTE}</p></div>{LB_JS}")


def _strategy_backtest_html(s: dict, m: dict, user: Optional[dict], badges: str,
                            msg: str = "", det: Optional[dict] = None) -> str:
    """Strategy page for a kind='backtest' row: backtest KPIs, period and source link."""
    sid = int(s["id"])
    t = m.get("test") or {}
    num = lambda v, f="{:.2f}": "—" if v is None else f.format(v)  # noqa: E731
    strip = ("<div class='lb-strip'>"
             f"<div class='lb-kpi'><div class='k'>Annualised (CAGR, backtest)</div>{_annualised_cell(m, False)}"
             f"<span class='lb-sub'>SPY {lperf.pct(m.get('spy_annualised_pct'))}</span></div>"
             f"<div class='lb-kpi'><div class='k'>Alpha vs SPY</div>{_alpha_cell(m, False)}</div>"
             f"<div class='lb-kpi'><div class='k'>Sharpe · max drawdown</div><span class='lb-v'>"
             f"{num(m.get('sharpe'))}</span><span class='lb-sub'>max DD {lperf.pct(m.get('max_drawdown_pct'))}"
             f" · {m.get('trades') or 0} trades · win {num(m.get('win_rate_pct'), '{:.0f}%')}</span></div>"
             f"<div class='lb-kpi'><div class='k'>Backtest period</div>{_period_cell(m, False)}</div></div>")
    oos = ""
    if t.get("annualised_pct") is not None:
        oos = (f"<p class='lb-note' style='margin-top:0'>Out-of-sample test window "
               f"{_e(lperf.fmt_day(t.get('period_start')))} – {_e(lperf.fmt_day(t.get('period_end')))}: "
               f"CAGR {lperf.pct(t.get('annualised_pct'))} vs SPY {lperf.pct(t.get('spy_annualised_pct'))}, "
               f"Sharpe {num(t.get('sharpe'))}, max drawdown {lperf.pct(t.get('max_drawdown_pct'))}. "
               f"Universe: {_e(m.get('universe') or '—')}.</p>")
    warn = ("<div class='flash' style='background:#fff7e0;color:#5c4410'><b>Backtest, not a live "
            "track record.</b> These are hypothetical results of AlpaTrade's daily-bar interpretation "
            f"of rules {_e(s['author'])} described in public. They are not {_e(s['author'])}'s own "
            "trades or account, and the strategy has never been traded live on AlpaTrade.</div>")
    flash = f"<div class='flash'>{_e(msg)}</div>" if msg else ""
    return (f"<div class='lb'>{flash}<a href='/leaderboard' style='font-size:.82rem'>← Leaderboard</a>"
            f"<h1>{_e(s['name'])}{badges}</h1>"
            f"<p class='lede' style='margin-bottom:.4rem'>by <b>{_e(s['author'])}</b> · {_e(s.get('description'))}</p>"
            + _source(s, full=True) + warn + strip + oos
            + _actions(s, user, wide_view=True).replace("class='lb-actions'", "class='lb-actions' style='margin:0'")
            + (f"<div class='lb-actions' style='margin:.2rem 0 0'><a class='lb-btn' href='/strategies/{sid}/edit'>Edit</a></div>"
               if user and str(user.get("user_id")) == s.get("user_id") else "")
            + f"<div class='lb-md' data-md-render='lb-md-{sid}'><pre>{_e(copy_text(s))}</pre></div>"
            + _json_script(f"lb-md-{sid}", copy_text(s))
            + (detail_html(s, m, det) if det is not None else "")
            + f"<p class='lb-note'>{_METHOD_NOTE}</p></div>{LB_JS}")


def my_strategies_html(rows: list[tuple[dict, dict]], msg: str = "", error: str = "") -> str:
    flash = (f"<div class='flash err'>{_e(error)}</div>" if error else "") + \
            (f"<div class='flash'>{_e(msg)}</div>" if msg else "")
    items = []
    for s, m in rows:
        sid = int(s["id"])
        pub = bool(s.get("is_public"))
        items.append(
            f"<div class='lb-row' id='my-strategy-{sid}'><div class='lb-rank'>{'●' if pub else '○'}</div>"
            f"<div class='lb-name'><a href='/strategies/{sid}'>{_e(s['name'])}</a>"
            + ("<span class='lb-badge pub'>Public</span>" if pub else "<span class='lb-badge'>Private</span>")
            + f"<div class='lb-desc'>{_e(s.get('description'))}</div></div>"
            f"<div class='lb-cell'><span class='lb-l'>Shown as</span>{_e(s['author'])}</div>"
            f"<div class='lb-cell'>{_annualised_cell(m)}</div>"
            f"<div class='lb-cell'>{_running_cell(m)}</div>"
            f"<div class='lb-cell'>{_alpha_cell(m)}</div>"
            "<div class='lb-actions'>"
            f"<form method='post' action='/strategies/{sid}/visibility'>"
            f"<input type='hidden' name='public' value='{'false' if pub else 'true'}'>"
            f"<input type='hidden' name='back' value='/strategies'>"
            f"<button class='lb-btn' type='submit'>{'Make private' if pub else 'Make public'}</button></form>"
            f"<a class='lb-btn' href='/strategies/{sid}'>View</a>"
            f"<a class='lb-btn' href='/strategies/{sid}/edit'>Edit</a>"
            f"<form method='post' action='/strategies/{sid}/delete' "
            "onsubmit=\"return confirm('Delete this strategy? This cannot be undone.')\">"
            "<button class='lb-btn danger' type='submit'>Delete</button></form></div></div>")
    head = ("<div class='lb-row lb-head'><div></div><div>Strategy</div><div>Shown as</div>"
            "<div>Annualised return</div><div>Running</div><div>Alpha vs SPY</div></div>")
    body = "".join(items) or ("<div class='lb-empty'>No strategies yet. Clone one from the "
                              "<a href='/leaderboard'>Leaderboard</a> or create your own.</div>")
    return (f"<div class='lb'>{flash}<span class='eyebrow'>Strategies</span><h1>My strategies</h1>"
            "<p class='lede'>Strategies you own. Private ones are only visible to you; public ones "
            "appear on the <a href='/leaderboard'>Leaderboard</a>. Live figures appear only for "
            "strategies linked to your own live AlpaTrade run.</p>"
            "<div class='lb-actions' style='margin:0 0 1rem'><a class='lb-btn primary' "
            "href='/strategies/new'>＋ New strategy</a><a class='lb-btn' href='/leaderboard'>Leaderboard</a></div>"
            f"<div class='lb-list'>{head}{body}</div></div>{LB_JS}")


def form_html(action: str, s: Optional[dict] = None, error: str = "",
              default_author: str = "") -> str:
    """New / edit strategy form. "Shown as" is prefilled with the strategy's current public
    name (``author``), else the submitted value, else ``default_author`` (email local part)."""
    s = s or {}
    title = "Edit strategy" if s.get("id") else "New strategy"
    flash = f"<div class='flash err'>{_e(error)}</div>" if error else ""
    checked = " checked" if s.get("is_public") else ""
    if s.get("user_id"):  # a stored row: its effective public name
        shown_as = s.get("author") or s.get("author_name") or default_author
    else:  # new form, or a re-rendered submission after a validation error
        shown_as = (s.get("author_name") or "").strip() or default_author
    return (f"<div class='lb'>{flash}<a href='/strategies' style='font-size:.82rem'>← My strategies</a>"
            f"<h1>{title}</h1><form class='lb-form' method='post' action='{_e(action)}'>"
            f"<label>Name<input type='text' name='name' required maxlength='{store.MAX_NAME}' value='{_e(s.get('name'))}'></label>"
            f"<label for='lb-author'>Shown as <small>(your public user name on the Leaderboard and the "
            f"strategy page; up to {store.MAX_AUTHOR} characters — left blank, it reverts to "
            f"<b>{_e(default_author) or 'your email name'}</b>)</small>"
            f"<input type='text' id='lb-author' name='author_name' maxlength='{store.MAX_AUTHOR}' "
            f"autocomplete='nickname' placeholder='{_e(default_author)}' value='{_e(shown_as)}'></label>"
            f"<label>Description <small>(one or two sentences)</small><textarea name='description' rows='3' "
            f"maxlength='{store.MAX_DESC}'>{_e(s.get('description'))}</textarea></label>"
            "<label>Strategy skill (markdown) <small>— the rules prompt plus a fenced JSON Parameters "
            "block with a <code>params</code> object; this is what Copy for ChatGPT / Claude copies</small>"
            f"<textarea class='code' name='skill_md'>{_e(s.get('skill_md'))}</textarea></label>"
            f"<label class='chk'><input type='checkbox' name='is_public' value='1'{checked}> Public — list it on the Leaderboard</label>"
            "<div class='lb-actions' style='margin:0'><button class='lb-btn primary' type='submit'>Save</button>"
            "<a class='lb-btn' href='/strategies'>Cancel</a></div></form></div>")


# ── data ────────────────────────────────────────────────────────────────────
def public_rows() -> list[tuple[dict, dict]]:
    rows = [(s, lperf.strategy_metrics(s)) for s in store.list_public()]
    rows.sort(key=lambda r: (lperf.rank_key(r[1]), r[0]["id"]))
    return rows


def _not_found() -> HTMLResponse:
    return HTMLResponse("<!doctype html><title>Not found · AlpaTrade</title>"
                        "<p style='font-family:system-ui;padding:2rem'>Strategy not found. "
                        "<a href='/leaderboard'>Back to the Leaderboard</a></p>", status_code=404)


def _detail(s: dict, m: dict) -> dict:
    try:
        from engine.leaderboard.detail import detail
        return detail(s, m)
    except Exception as exc:  # noqa: BLE001 — never break the page
        log.warning("strategy detail failed: %s", type(exc).__name__)
        return {}


def _render(user, title: str, active: str, inner: str):
    if user:
        from engine.web.ph_layout import page
        return page(active, Style(LB_CSS), Div(NotStr(inner)), user=user, title=title,
                    right_news=False)
    from engine.web.ph_landing import _shell
    return _shell(title, Style(LB_CSS), Section(NotStr(inner)), active=active)


def _bool(v) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "on", "yes")


def _author(form, user: dict) -> str:
    """Submitted "Shown as" name, sanitised; blank falls back to the email local part."""
    return store.clean_author(form.get("author_name"), store.default_author(user))


def register(app, rt):
    from engine.web import ph_layout

    for entry in (("Leaderboard", "/leaderboard", "leaderboard"),
                  ("My strategies", "/strategies", "strategies")):
        if entry not in ph_layout.TRADE_PAGES:
            ph_layout.TRADE_PAGES.append(entry)

    @rt("/leaderboard", methods=["GET"])
    def leaderboard_get(session, msg: str = "", error: str = "", kind: str = "",
                        source: str = "", q: str = "", page: int = 1):
        user = _user(session)
        try:
            rows = public_rows()
        except Exception as exc:  # noqa: BLE001
            log.warning("leaderboard load failed: %s", type(exc).__name__)
            rows, error = [], error or "The Leaderboard is unavailable right now."
        return _render(user, "Strategy Leaderboard · AlpaTrade", "leaderboard",
                       leaderboard_html(rows, user, msg=msg, error=error, kind=kind,
                                        source=source, q=q, page=page))

    @rt("/leaderboard.json", methods=["GET"])
    def leaderboard_json():
        out = []
        for i, (s, m) in enumerate(public_rows()):
            out.append({"rank": i + 1, "id": s["id"], "name": s["name"], "user": s["author"],
                        "description": s.get("description") or "",
                        "url": f"/strategies/{s['id']}", "kind": s.get("kind") or "live",
                        "source": s.get("source"), "source_url": s.get("source_url"),
                        **{k: m.get(k) for k in (
                            "start_date", "days_running", "trading_days", "as_of", "return_pct",
                            "spy_return_pct", "alpha_pct", "annualised_pct",
                            "annualised_compound_pct")}})
        return JSONResponse({"strategies": out, "benchmark": "SPY",
                             "annualised": "simple: return x 252 / trading days"})

    @rt("/strategies", methods=["GET"])
    def strategies_get(session, msg: str = "", error: str = ""):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        rows = [(s, lperf.strategy_metrics(s)) for s in store.list_for_user(str(user["user_id"]))]
        return _render(user, "My strategies · AlpaTrade", "strategies",
                       my_strategies_html(rows, msg=msg, error=error))

    @rt("/strategies/new", methods=["GET"])
    def strategy_new_get(session):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        return _render(user, "New strategy · AlpaTrade", "strategies",
                       form_html("/strategies/new", default_author=store.default_author(user)))

    @app.post("/strategies/new")
    async def strategy_new_post(session, request):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        f = await request.form()
        try:
            sid = store.create(str(user["user_id"]), f.get("name"), f.get("description"),
                               f.get("skill_md"), _author(f, user), _bool(f.get("is_public")))
        except ValueError as exc:
            return _render(user, "New strategy · AlpaTrade", "strategies",
                           form_html("/strategies/new", dict(f), error=str(exc),
                                     default_author=store.default_author(user)))
        return RedirectResponse(f"/strategies/{sid}?msg=Strategy+saved", status_code=303)

    @rt("/strategies/{sid}", methods=["GET"])
    def strategy_get(session, sid: int, msg: str = ""):
        user = _user(session)
        s = store.get_visible(sid, str(user["user_id"]) if user else None)
        if not s:
            return _not_found()
        return _render(user, f"{s['name']} · AlpaTrade", "leaderboard",
                       strategy_html(s, m := lperf.strategy_metrics(s), user, msg=msg,
                                     det=_detail(s, m)))

    @rt("/strategies/{sid}/skill.md", methods=["GET"])
    def strategy_md(session, sid: int):
        user = _user(session)
        s = store.get_visible(sid, str(user["user_id"]) if user else None)
        if not s:
            return _not_found()
        return Response(copy_text(s), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'inline; filename="strategy-{sid}.md"'})

    @rt("/strategies/{sid}/edit", methods=["GET"])
    def strategy_edit_get(session, sid: int):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        s = store.get(sid)
        if not s or s["user_id"] != str(user["user_id"]):
            return _not_found()
        return _render(user, "Edit strategy · AlpaTrade", "strategies",
                       form_html(f"/strategies/{sid}/edit", s,
                                 default_author=store.default_author(user)))

    @app.post("/strategies/{sid}/edit")
    async def strategy_edit_post(session, request, sid: int):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        f = await request.form()
        try:
            ok = store.update(sid, str(user["user_id"]), f.get("name"), f.get("description"),
                              f.get("skill_md"), _author(f, user), _bool(f.get("is_public")))
        except ValueError as exc:
            return _render(user, "Edit strategy · AlpaTrade", "strategies",
                           form_html(f"/strategies/{sid}/edit", {**dict(f), "id": sid},
                                     error=str(exc), default_author=store.default_author(user)))
        if not ok:
            return _not_found()
        return RedirectResponse(f"/strategies/{sid}?msg=Strategy+saved", status_code=303)

    @app.post("/strategies/{sid}/visibility")
    async def strategy_visibility(session, request, sid: int):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        f = await request.form()
        public = _bool(f.get("public"))
        if not store.set_public(sid, str(user["user_id"]), public):
            return _not_found()
        msg = "Published+on+the+Leaderboard" if public else "Strategy+is+now+private"
        back = "/strategies" if f.get("back") == "/strategies" else f"/strategies/{sid}"
        return RedirectResponse(f"{back}?msg={msg}", status_code=303)

    @app.post("/strategies/{sid}/delete")
    async def strategy_delete(session, sid: int):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        if not store.delete(sid, str(user["user_id"])):
            return _not_found()
        return RedirectResponse("/strategies?msg=Strategy+deleted", status_code=303)

    @app.post("/strategies/{sid}/clone")
    async def strategy_clone(session, sid: int):
        user = _user(session)
        if not user:
            from urllib.parse import quote_plus
            return RedirectResponse(f"/signin?msg={quote_plus(_SIGNIN_MSG)}", status_code=303)
        new_id = store.clone(sid, str(user["user_id"]), author_name=store.default_author(user))
        if not new_id:
            return _not_found()
        return RedirectResponse(
            f"/strategies/{new_id}?msg=Cloned+into+your+strategies+%28private%29", status_code=303)

    return ["/leaderboard", "/leaderboard.json", "/strategies", "/strategies/new",
            "/strategies/{sid}", "/strategies/{sid}/skill.md", "/strategies/{sid}/edit"]
