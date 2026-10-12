""""Clone to Grok Bot" — public Grok Bot templates for Leaderboard strategies.

* ``/templates``: every public strategy as a Grok Bot template card (like skillsdojo.com/templates).
* ``/templates/grokbot/<slug>.json``: the template JSON (public, cached 5 min).
* ``POST /templates/grokbot/<id>/click``: anonymous per-strategy click counter.
* ``/admin/grokbot-clicks``: admin-only JSON totals.

Works signed out unless ``GROKBOT_CLONE_REQUIRES_LOGIN=1``.
"""
from __future__ import annotations

import html
import json
import logging
from typing import Optional

from fasthtml.common import Div, NotStr, Section, Style
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from engine.leaderboard import grokbot as gb
from engine.leaderboard import grokbot_clicks as clicks
from engine.leaderboard import store

log = logging.getLogger(__name__)

GB_SVG = ("<svg viewBox='0 0 24 24' width='14' height='14' aria-hidden='true'><rect x='4' y='7' width='16' height='12' rx='3' "
          "fill='none' stroke='currentColor' stroke-width='2'/><circle cx='9' cy='13' r='1.5' fill='currentColor'/>"
          "<circle cx='15' cy='13' r='1.5' fill='currentColor'/><path d='M12 3v4' stroke='currentColor' stroke-width='2'/></svg>")

GB_CSS = """
.lb-btn.ai.gb svg path{fill:none}
.gb-ov{position:fixed;inset:0;background:rgba(0,0,0,.55);display:none;align-items:center;justify-content:center;z-index:1000;padding:12px}
.gb-ov.show{display:flex}
.gb-m{background:#fff;color:#1a1f1c;border:1px solid rgba(127,127,127,.35);border-radius:14px;max-width:520px;width:100%;max-height:90vh;overflow:auto;padding:18px 18px 14px;box-sizing:border-box}
.gb-m h3{margin:0 0 4px;font-size:1.1rem}.gb-m p{margin:.4rem 0;font-size:.9rem;opacity:.9}
.gb-m ul{margin:.4rem 0 .8rem 1.1rem;padding:0;font-size:.88rem}.gb-m li{margin:.2rem 0}
.gb-row{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.gb-row a,.gb-row button{flex:1 1 140px;text-align:center;padding:9px 10px;border-radius:9px;border:1px solid rgba(127,127,127,.45);background:transparent;color:inherit;font:inherit;font-size:.88rem;cursor:pointer;text-decoration:none}
.gb-row .gb-go{background:#1f5135;color:#fff;border-color:#1f5135;font-weight:600}
.gb-x{float:right;background:none;border:0;color:inherit;font-size:1.3rem;cursor:pointer;line-height:1}
.gb-disc{font-size:.75rem!important;opacity:.7!important;margin-top:12px!important}
.gb-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;margin:16px 0}
.gb-card{border:1px solid rgba(127,127,127,.3);border-radius:12px;padding:14px;display:flex;flex-direction:column;gap:6px}
.gb-card h3{margin:0;font-size:1rem}.gb-card .by{font-size:.8rem;opacity:.7}.gb-card p{font-size:.86rem;margin:0;flex:1}
.gb-card .lb-btn{align-self:flex-start}
@media(max-width:760px){.gb-grid{grid-template-columns:1fr}.gb-row a,.gb-row button{flex:1 1 100%}}
"""

GB_JS = """
<script>
(function(){if(window.gbOpen)return;
function el(h){var d=document.createElement('div');d.innerHTML=h;return d.firstChild}
function esc(s){return String(s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function track(id,a){try{var b=new Blob([JSON.stringify({action:a})],{type:'application/json'});
 if(navigator.sendBeacon)navigator.sendBeacon('/templates/grokbot/'+id+'/click',b);
 else fetch('/templates/grokbot/'+id+'/click',{method:'POST',body:b,keepalive:true})}catch(e){}}
function cp(t,msg){var done=function(){(window.lbToast||alert)(msg)};
 if(navigator.clipboard&&window.isSecureContext)navigator.clipboard.writeText(t).then(done,done);else{var a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();try{document.execCommand('copy')}catch(e){}a.remove();done()}}
window.gbOpen=function(id,slug,name,share){var json=location.origin+'/templates/grokbot/'+slug+'.json';
 var prompt='Set yourself up from this AlpaTrade Grok Bot template: '+json+'\\nFetch the JSON, adopt its name and instructions, save the skill content as a skill, create the routines with their ET schedules, then ask me for my Alpaca keys via a secure secret request (never in chat).';
 var ov=document.getElementById('gb-ov');if(ov)ov.remove();
 var go=share?"<a class='gb-go' href='"+esc(share)+"' target='_blank' rel='noopener' data-a='share'>Open in Grok Bot</a>"
   :"<button type='button' class='gb-go' data-a='copy_prompt'>Copy setup prompt</button>";
 ov=el("<div class='gb-ov show' id='gb-ov' role='dialog' aria-modal='true' aria-label='Clone to Grok Bot'><div class='gb-m'>"+
  "<button class='gb-x' aria-label='Close' data-a='close'>&times;</button><h3>AlpaTrade "+esc(name)+"</h3>"+
  "<p>Clone this strategy into your own Grok Bot. No AlpaTrade account needed.</p><ul>"+
  "<li><b>Persona</b> &ldquo;AlpaTrade "+esc(name)+"&rdquo; that follows the strategy rules exactly</li>"+
  "<li><b>Skill</b>: the full strategy SKILL.md (rules + Parameters JSON)</li>"+
  "<li><b>Your Alpaca keys</b> (paper or live) via the bot's secure secret request, never in chat; checked with GET /v2/account</li>"+
  "<li><b>Routines (ET)</b>: entry 15:45&ndash;15:55, exits 09:31, close window 15:50, daily P&amp;L digest</li>"+
  "<li>Cash only, PDT-safe 3-day minimum hold, typed confirmation before any live trade</li></ul>"+
  (share?"":"<p>Paste the setup prompt into a new Grok Bot chat, or download the template JSON.</p>")+
  "<div class='gb-row'>"+go+"<button type='button' data-a='copy_link'>Copy template link</button>"+
  "<a href='"+json+"' download='alpatrade-"+esc(slug)+".json' data-a='download'>Download JSON</a></div>"+
  "<p class='gb-disc'>Research only, not investment advice. Predictive Labs Ltd. Orders run on your own Alpaca account at your own risk.</p></div></div>");
 document.body.appendChild(ov);track(id,'open');
 ov.addEventListener('click',function(e){var t=e.target.closest('[data-a]');if(e.target===ov){ov.remove();return}if(!t)return;var a=t.dataset.a;
  if(a==='close'){ov.remove();return}track(id,a);
  if(a==='copy_link')cp(share||json,'Template link copied');
  if(a==='copy_prompt'){cp(prompt,'Setup prompt copied \\u2014 paste it into Grok Bot');window.open('https://grok.com/','_blank','noopener')}});
 document.addEventListener('keydown',function k(e){if(e.key==='Escape'){ov.remove();document.removeEventListener('keydown',k)}})};
})();
</script>
"""


def button(s: dict, user: Optional[dict]) -> str:
    if gb.requires_login() and not user:
        return (f"<a class='lb-btn ai gb' href='/signin?next=/leaderboard' rel='nofollow'>{GB_SVG}Clone to Grok Bot</a>")
    args = json.dumps([int(s["id"]), gb.slug_for(s), s.get("name") or "", gb.share_url(s) or ""])[1:-1]
    return (f"<button type='button' class='lb-btn ai gb' onclick='gbOpen({html.escape(args, quote=True)})' "
            f"title='Clone this strategy into your own Grok Bot'>{GB_SVG}Clone to Grok Bot</button>")


def assets() -> str:
    return f"<style>{GB_CSS}</style>{GB_JS}"


def _user(session):
    from engine.web.ph_leaderboard import _user as u
    return u(session)


def _base(request) -> str:
    return f"{request.url.scheme}://{request.url.netloc}" if request else "https://alpatrade.chat"


def templates_html(rows: list[dict], user: Optional[dict]) -> str:
    cards = "".join(
        f"<article class='gb-card' id='template-{html.escape(gb.slug_for(s))}'><h3>AlpaTrade {html.escape(s['name'])}</h3>"
        f"<span class='by'>by {html.escape(s.get('author') or 'AlpaTrade')}</span>"
        f"<p>{html.escape((s.get('description') or '')[:260])}</p>"
        f"<div class='lb-actions'>{button(s, user)}<a class='lb-btn view' href='/strategies/{int(s['id'])}'>View strategy</a></div></article>"
        for s in rows)
    return (f"<div class='lb-wrap'><h1>Grok Bot Templates</h1>"
            "<p class='lb-sub'>Every public AlpaTrade strategy as a ready-made Grok Bot: rules skill, Alpaca setup "
            "via secure secrets, and ET trading routines. Clone it, connect your own Alpaca keys inside the bot, done.</p>"
            f"<div class='gb-grid'>{cards or '<p>No public strategies yet.</p>'}</div>"
            f"<p class='lb-note'>{html.escape(gb.DISCLAIMER)}</p></div>{assets()}")


def register(app, rt):
    @rt("/templates", methods=["GET"])
    def templates_get(session):
        from engine.web.ph_leaderboard import _render
        user = _user(session)
        try:
            rows = store.list_public()
        except Exception as exc:  # noqa: BLE001
            log.warning("templates load failed: %s", type(exc).__name__)
            rows = []
        return _render(user, "Grok Bot Templates · AlpaTrade", "leaderboard", templates_html(rows, user))

    @rt("/templates/grokbot/{slug}", methods=["GET"])
    def template_json(session, request, slug: str):
        if gb.requires_login() and not _user(session):
            return JSONResponse({"error": "sign in required"}, status_code=401)
        sid = gb.id_from_slug(slug)
        s = store.get(sid) if sid else None
        if not s or not s.get("is_public"):
            return JSONResponse({"error": "template not found"}, status_code=404)
        if not slug.endswith(".json"):
            return RedirectResponse(f"/templates#template-{gb.slug_for(s)}", status_code=302)
        clicks.record(sid, "json")
        body = json.dumps(gb.template(s, _base(request)), indent=2, ensure_ascii=False)
        return Response(body, media_type="application/json; charset=utf-8",
                        headers={"Cache-Control": "public, max-age=300",
                                 "Access-Control-Allow-Origin": "*",
                                 "Content-Disposition": f'inline; filename="alpatrade-{gb.slug_for(s)}.json"'})

    @rt("/templates/grokbot/{sid}/click", methods=["POST"])
    async def template_click(request, sid: int):
        try:
            action = str((json.loads(await request.body() or b"{}") or {}).get("action") or "")
        except ValueError:
            action = ""
        ok = clicks.record(int(sid), action) if action in clicks.ACTIONS else False
        return JSONResponse({"ok": ok})

    @rt("/admin/grokbot-clicks", methods=["GET"])
    def admin_clicks(session):
        user = _user(session)
        from engine.rbac import is_admin
        if not (user and is_admin(user)):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        return JSONResponse({"clicks": clicks.totals()})
