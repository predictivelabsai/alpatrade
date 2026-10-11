"""Settings page for the merged AlpaTrade app (BYOK + provider preferences).

Reached from the left-menu "⚙ Settings" link. Renders through
:func:`engine.web.ph_layout.page` so the parchment / forest shell stays identical
(news pane dropped). Two forms:

* **Alpaca keys (BYOK)** — the user's own ``ALPACA_PAPER_API_KEY`` /
  ``ALPACA_PAPER_SECRET_KEY``, Fernet-encrypted into ``alpatrade.user_accounts``
  (:func:`engine.auth.store_alpaca_keys`). Because the web app and REST API are
  separate processes, the keys live in the DB, not process env.
* **Providers** — model / market-data / search / agent-framework selections stored
  in ``alpatrade.user_settings`` (:func:`engine.auth.store_user_settings`) and
  resolved by :mod:`engine.config`.
* **Email reports** — which daily emails the user receives (live / paper), stored
  in ``alpatrade.user_report_preferences``
  (:mod:`engine.reporting.preferences`) and honoured by the schedulers in
  :mod:`engine.autonomy.schedule`. An option is disabled when the user has no
  matching Alpaca account (no live link / no paper keys).

Feature-module contract: :func:`register(app, rt)` attaches the routes.
"""
from __future__ import annotations

import html

from fasthtml.common import (
    A, Button, Code, Div, Form, H2, H3, Input, Label, NotStr, Option, P, Select,
    Span, Style,
)
from starlette.responses import RedirectResponse

from engine.web.ph_layout import page

import logging
logger = logging.getLogger(__name__)
from typing import Optional
from engine.config import (
    get_settings, MODEL_PROVIDERS, MODEL_NAMES, MARKET_DATA_PROVIDERS,
    SEARCH_PROVIDERS, AGENT_FRAMEWORKS,
)

_SETTINGS_CSS = """

.settings{max-width:720px;margin:0 auto;width:100%;padding:0 1rem 3rem}
.settings h1{font-size:1.3rem;margin:.4rem 0 .2rem;color:var(--ink)}
.settings .s-sub{font-size:.82rem;color:var(--ink-muted);margin:0 0 1.4rem}
.settings .s-card{background:var(--bg-elev);border:1px solid var(--line);
  border-radius:.7rem;padding:1.1rem 1.3rem;margin-bottom:1.3rem}
.settings h3{margin:0 0 .2rem;font-size:1rem;color:var(--ink)}
.settings .s-hint{font-size:.76rem;color:var(--ink-dim);margin:.1rem 0 .9rem}
.settings .s-row{display:flex;flex-direction:column;gap:.25rem;margin-bottom:.8rem}
.settings .s-row label{font-size:.76rem;color:var(--ink-muted);font-weight:600}
.settings .s-row input,.settings .s-row select{font-family:var(--font-body);
  font-size:.86rem;color:var(--ink);background:var(--bg);border:1px solid var(--line-br);
  border-radius:.45rem;padding:.5rem .6rem;width:100%}
.settings .s-grid{display:grid;grid-template-columns:1fr 1fr;gap:.8rem}
@media(max-width:560px){.settings .s-grid{grid-template-columns:1fr}}
.settings .s-btn{font-size:.85rem;color:var(--bg);background:var(--accent);border:0;
  border-radius:.45rem;padding:.55rem 1.1rem;cursor:pointer;margin-top:.3rem}
.settings .s-btn:hover{opacity:.92}
.settings .s-status{font-size:.78rem;font-weight:600}
.settings .s-status.ok{color:var(--accent)}
.settings .s-status.no{color:#b0653f}
.settings .s-notice{border-radius:.5rem;padding:.6rem .8rem;margin-bottom:1rem;font-size:.82rem}
.settings .s-notice.ok{background:var(--accent-dim);color:var(--accent-deep)}
.settings .s-notice.err{background:#fff0ee;color:#9b302b}
.settings .s-section{font-size:1.05rem;margin:1.6rem 0 .6rem}
.settings .s-tblwrap{overflow-x:auto;margin:.3rem 0 .8rem}
.settings .s-accts{border-collapse:collapse;font-size:.8rem;width:100%}
.settings .s-accts th,.settings .s-accts td{text-align:left;padding:.35rem .6rem .35rem 0;border-bottom:1px solid var(--line);white-space:nowrap}
.settings .s-accts th{font-size:.66rem;text-transform:uppercase;letter-spacing:.06em;color:var(--ink-dim)}
.settings .s-readonly{font-size:.9rem;color:var(--ink)}
.settings .s-secret{display:flex;gap:.4rem;align-items:center}
.settings .s-secret input{flex:1}
.settings .s-eye{border:1px solid var(--line-br);background:var(--bg);color:var(--ink);
  border-radius:.45rem;padding:.5rem .65rem;cursor:pointer}
.settings .s-danger{background:transparent;color:#9b3c30;border:1px solid #c98b82}
.settings .s-check{display:flex;gap:.6rem;align-items:flex-start;margin-bottom:.8rem}
.settings .s-check input{margin-top:.2rem;width:1rem;height:1rem;accent-color:var(--accent)}
.settings .s-check .s-check-label{font-size:.88rem;color:var(--ink);font-weight:600}
.settings .s-check .s-check-note{display:block;font-size:.76rem;color:var(--ink-dim);
  font-weight:400;margin-top:.1rem}
.settings .s-check.off{opacity:.55}
.settings .s-check.off .s-check-label{cursor:not-allowed}
"""


def _user(session):
    uid = session.get("user_id") if session else None
    if not uid:
        return None
    try:
        from engine.auth import get_user_by_id
        return get_user_by_id(uid)
    except Exception:  # noqa: BLE001
        return None


def _opts(values, current, labels=None):
    labels = labels or {}
    return [Option(labels.get(v, v), value=v, selected=(v == current)) for v in values]


def _model_name_options(current):
    """Flat model list across providers; grok-4.5 flagged as region-locked."""
    labels = {"grok-4.5": "grok-4.5 (region-locked on some accounts)"}
    opts = []
    seen = set()
    for prov in MODEL_PROVIDERS:
        for m in MODEL_NAMES.get(prov, []):
            if m in seen:
                continue
            seen.add(m)
            opts.append(Option(labels.get(m, m), value=m, selected=(m == current)))
    return opts


def _has_live_account(user_id: str) -> bool:
    try:
        from engine.live_accounts import list_live_accounts
        return bool(list_live_accounts(user_id))
    except Exception:  # noqa: BLE001 — table missing / DB down
        return False


def _has_paper_keys(user_id: str) -> bool:
    try:
        from engine.auth import get_user_accounts
        return bool(get_user_accounts(user_id))
    except Exception:  # noqa: BLE001
        return False


def _report_option(field: str, title: str, when: str, checked: bool,
                   available: bool, missing_note):
    """One report checkbox; disabled (with a note) when the user lacks the keys."""
    box = Input(type="checkbox", id=f"pref-{field}", name=field, value="1",
                checked=bool(checked and available), disabled=not available)
    note = when if available else missing_note
    return Div(
        box,
        Label(Span(title, cls="s-check-label"), Span(note, cls="s-check-note"),
              fr=f"pref-{field}"),
        cls=f"s-check{'' if available else ' off'}",
    )


def _report_card(user_id: str, has_paper: bool, has_live: bool):
    from engine.reporting.preferences import LIVE, PAPER, get_report_preferences
    prefs = get_report_preferences(user_id)
    return Div(
        H3("Email reports"),
        P("Choose which daily reports are emailed to your sign-in address. "
          "You can turn both off.", cls="s-hint"),
        Form(
            _report_option(
                LIVE, "Daily live trading report",
                "Your linked live Alpaca account — fills, P&L, positions and orders. "
                "Sent after the US close on trading days (~23:20 Tallinn).",
                prefs[LIVE], has_live,
                NotStr("Needs a linked live Alpaca account — see "
                       "<a href='/live/account'>Live account</a>."),
            ),
            _report_option(
                PAPER, "Daily paper trading report",
                "Your paper Alpaca account — equity, day P&L, positions and the "
                "day's paper trades. Sent nightly.",
                prefs[PAPER], has_paper,
                "Needs your Alpaca paper keys — add them above to enable this report.",
            ),
            Button("Save email reports", type="submit", cls="s-btn"),
            method="post", action="/settings/reports",
        ),
        id="report-settings",
        cls="s-card",
    )


def _check_cell(mode: str, ref: str, last: Optional[dict]) -> str:
    """Check button + last read-only check result for one saved key."""
    res = ""
    if last:
        at = last["at"]
        when = at.strftime("%Y-%m-%d %H:%M UTC") if hasattr(at, "strftime") else str(at)[:16]
        res = (f"<div class='s-chk {'ok' if last.get('ok') else 'bad'}'>{'✓' if last.get('ok') else '✗'} "
               f"{html.escape(str(last.get('text') or ''))}<br><small>checked {html.escape(when)}</small></div>")
    return (f"<form method='post' action='/settings/keys/check' style='margin:0'>"
            f"<input type='hidden' name='mode' value='{mode}'><input type='hidden' name='ref' value='{html.escape(ref)}'>"
            f"<button type='submit' class='s-btn s-chkbtn'>Check</button></form>{res}")


def _connected_table(rows: list) -> str:
    if not rows:
        return "<p class='s-hint'>No account connected yet.</p>"
    body = "".join(f"<tr><td>{html.escape(r[0])}</td><td><code>{html.escape(r[1])}</code></td>"
                   f"<td>{html.escape(r[2])}</td>" + (f"<td>{r[3]}</td>" if len(r) > 3 else "") + "</tr>"
                   for r in rows)
    chk = "<th>Check</th>" if any(len(r) > 3 for r in rows) else ""
    return ("<style>.s-chk{font-size:.74rem;margin-top:.3rem;max-width:22rem;overflow-wrap:anywhere}"
            ".s-chk.ok{color:#147a4b}.s-chk.bad{color:#b43b35}.s-chkbtn{min-height:2rem;padding:.2rem .7rem;font-size:.78rem}"
            "@media(max-width:640px){.s-accts td{display:block;border:0;padding:.15rem 0}.s-accts thead{display:none}"
            ".s-accts tr{display:block;padding:.5rem 0;border-bottom:1px solid var(--line)}}</style>"
            "<div class='s-tblwrap'><table class='s-accts'><thead><tr><th>Account</th><th>Key</th>"
            f"<th>Connected</th>{chk}</tr></thead><tbody>{body}</tbody></table></div>")


def _paper_card(accounts: list, account_id: str, key_status, checks: Optional[dict] = None):
    checks = checks or {}
    rows = [(a.get("account_name") or "Paper", a.get("api_key_hint") or "****",
             str(a.get("created_at") or "")[:10],
             _check_cell("paper", str(a.get("account_id")), checks.get(("paper", str(a.get("account_id"))))))
            for a in accounts or []]
    return Div(
        H3("Alpaca paper"),
        P(NotStr("Status: "), key_status, cls="s-hint"),
        NotStr(_connected_table(rows)),
        Form(
            Input(name="account_id", type="hidden", value=account_id),
            Div(Label("ALPACA_PAPER_API_KEY", fr="paper-key"),
                Input(id="paper-key", name="api_key", type="password", autocomplete="off",
                      placeholder="PK…", required=True), cls="s-row"),
            Div(Label("ALPACA_PAPER_SECRET_KEY", fr="paper-secret"),
                Input(id="paper-secret", name="secret_key", type="password", autocomplete="off",
                      placeholder="••••••••", required=True), cls="s-row"),
            P("Checked read-only against Alpaca's paper API before saving, then Fernet-encrypted "
              "at rest; never sent back to the browser.", cls="s-hint"),
            Button("Save paper keys", type="submit", cls="s-btn"),
            method="post", action="/settings/keys",
        ),
        id="paper-keys", cls="s-card",
    )


def _live_card(links: list, checks: Optional[dict] = None):
    checks = checks or {}
    rows = [(f"{l.get('label') or 'Alpaca live'} · {l.get('account_number')}", l.get("api_key_hint") or "",
             str(l.get("updated_at") or "")[:10],
             _check_cell("live", str(l.get("account_number")), checks.get(("live", str(l.get("account_number"))))))
            for l in links or []]
    status = (Span(f"Connected · {len(links)} account{'s' if len(links) != 1 else ''}", cls="s-status ok")
              if links else Span("Not connected", cls="s-status no"))
    unlink = [Form(Input(name="account_number", type="hidden", value=str(l.get("account_number"))),
                   Button(f"Disconnect {l.get('account_number')}", type="submit", cls="s-btn s-danger"),
                   method="post", action="/settings/live-keys/remove") for l in links or []]
    return Div(
        H3("Alpaca live (real money)"),
        P(NotStr("Status: "), status, cls="s-hint"),
        NotStr(_connected_table(rows)),
        Form(
            Div(Label("ALPACA_LIVE_API_KEY", fr="live-key"),
                Input(id="live-key", name="api_key", type="password", autocomplete="off",
                      placeholder="AK…", required=True), cls="s-row"),
            Div(Label("ALPACA_LIVE_SECRET_KEY", fr="live-secret"),
                Input(id="live-secret", name="secret_key", type="password", autocomplete="off",
                      placeholder="••••••••", required=True), cls="s-row"),
            P("Validated with one read-only request to Alpaca's live API (account details only), then "
              "Fernet-encrypted at rest exactly like paper keys. Saving keys never trades: a live "
              "strategy only runs after you press Activate Live and confirm it (cash only).",
              cls="s-hint"),
            Button("Save live keys", type="submit", cls="s-btn"),
            method="post", action="/settings/live-keys",
        ),
        *unlink,
        id="live-keys", cls="s-card",
    )


def _live_strategies_card(rows: list):
    if not rows:
        return Div()
    from engine.leaderboard.activate import STATUS_LABEL
    items = []
    for r in rows:
        st = r.get("status")
        btns = []
        for act, label, show in (("pause", "Pause", st in ("pending_runner", "active")),
                                 ("resume", "Resume", st == "paused"),
                                 ("deactivate", "Deactivate", st != "deactivated")):
            if show:
                btns.append(Form(Button(label, type="submit", cls="s-btn" + (" s-danger" if act == "deactivate" else "")),
                                 method="post", action=f"/settings/live-strategies/{int(r['id'])}/{act}",
                                 style="display:inline-block;margin:.3rem .4rem 0 0"))
        items.append(Div(
            NotStr(f"<b>{html.escape(str(r.get('name') or ''))}</b> · account {html.escape(str(r.get('account_ref')))} · "
                   f"${float(r.get('allocation_usd') or 0):,.2f} cash only · orders <code>{html.escape(str(r.get('cid_prefix')))}-…</code>"
                   f"<br><span class='s-hint'>{html.escape(STATUS_LABEL.get(st, str(st)))}</span>"),
            *btns, style="padding:.6rem 0;border-bottom:1px solid var(--line)"))
    return Div(H3("Live strategies"),
               P("Each runs in its own process on your own account. Pause stops new buys (open positions keep "
                 "their exits); Deactivate stops the strategy.", cls="s-hint"),
               *items, id="live-strategies", cls="s-card")


def _settings_page(user, msg: str = ""):
    if not user:
        return RedirectResponse("/signin", status_code=303)

    s = get_settings(user["user_id"])

    # Alpaca key status
    try:
        from engine.auth import get_user_accounts
        accounts = get_user_accounts(user["user_id"])
    except Exception:  # noqa: BLE001
        accounts = []
    if accounts:
        hint = accounts[0].get("api_key_hint", "****")
        key_status = Span(f"Configured · {hint}", cls="s-status ok")
    else:
        key_status = Span("Not connected — add your Alpaca paper keys below to trade",
                          cls="s-status no")

    if msg == "saved":
        notice = [Div("Saved.", cls="s-notice ok")]
    elif msg:
        bad = msg.lower().startswith(("could not", "alpaca", "these are", "both", "error", "add your"))
        notice = [Div(msg[:300], cls=f"s-notice {'err' if bad else 'ok'}")]
    else:
        notice = []
    try:
        from engine.live_accounts import list_live_accounts
        live_links = list_live_accounts(user["user_id"])
    except Exception:  # noqa: BLE001
        live_links = []
    try:
        from engine.key_check import last_results
        key_checks = last_results(user["user_id"])
    except Exception:  # noqa: BLE001
        key_checks = {}
    try:
        from engine.leaderboard.activate import list_live
        live_strats = list_live(str(user["user_id"]))
    except Exception:  # noqa: BLE001
        live_strats = []

    account_id = accounts[0]["account_id"] if accounts else ""

    try:
        from engine.auth import get_provider_key_status
        xai_status = get_provider_key_status(user["user_id"], "xai")
    except Exception:  # migration may not have been applied yet
        xai_status = {"configured": False, "hint": ""}
    xai_label = (
        f"Configured · {xai_status['hint']}"
        if xai_status["configured"] else
        "Not configured — the first 5 AI queries use the platform allowance"
    )

    body = Div(
        Div("Settings", cls="chat-header-title", style="display:none"),
        NotStr('<h1>Settings</h1>'),
        P("Connect your own Alpaca keys and choose your providers. "
          "Everything besides your email is optional.", cls="s-sub"),
        *notice,

        # --- Account ------------------------------------------------------
        Div(
            H3("Account"),
            P("Signed in as", cls="s-hint"),
            P(user.get("email", ""), cls="s-readonly"),
            cls="s-card",
        ),

        # --- AI provider key (BYOK) --------------------------------------
        Div(
            H3("AI provider key (BYOK)"),
            P(NotStr("Status: "),
              Span(xai_label, cls=f"s-status {'ok' if xai_status['configured'] else 'no'}"),
              cls="s-hint"),
            Form(
                Input(name="provider", type="hidden", value="xai"),
                Div(
                    Label("PROVIDER_KEY (xAI)", fr="provider-key"),
                    Div(
                        Input(id="provider-key", name="provider_key", type="password",
                              autocomplete="new-password", placeholder="xai-…", required=True),
                        Button("Show", type="button", cls="s-eye",
                               onclick="toggleSecret('provider-key', this)"),
                        cls="s-secret",
                    ),
                    cls="s-row",
                ),
                P("Use your own xAI API key after the platform-funded allowance. "
                  "It is Fernet-encrypted at rest and never sent back to the browser; "
                  "Show only reveals what you are typing.", cls="s-hint"),
                Button("Save provider key", type="submit", cls="s-btn"),
                method="post", action="/settings/provider-key",
            ),
            *(
                [Form(Input(name="provider", type="hidden", value="xai"),
                      Button("Remove saved key", type="submit", cls="s-btn s-danger"),
                      method="post", action="/settings/provider-key/remove")]
                if xai_status["configured"] else []
            ),
            NotStr("""<script>
function toggleSecret(id, button) {
  const field = document.getElementById(id);
  const showing = field.type === 'text';
  field.type = showing ? 'password' : 'text';
  button.textContent = showing ? 'Show' : 'Hide';
}
</script>"""),
            id="provider-key-settings",
            cls="s-card",
        ),

        # --- Integrations: Alpaca paper + live ---------------------------
        NotStr("<h2 id='integrations' class='s-section'>Integrations</h2>"),
        _paper_card(accounts, account_id, key_status, key_checks),
        _live_card(live_links, key_checks),
        _live_strategies_card(live_strats),

        # --- Email reports ------------------------------------------------
        _report_card(user["user_id"], has_paper=bool(accounts),
                     has_live=_has_live_account(user["user_id"])),

        # --- Providers ----------------------------------------------------
        Div(
            H3("Providers"),
            P("Model and data providers used by the AI. Defaults come from the "
              "server; your choices here override them.", cls="s-hint"),
            Form(
                Div(
                    Div(Label("Model provider"),
                        Select(*_opts(MODEL_PROVIDERS, s.model_provider), name="model_provider"),
                        cls="s-row"),
                    Div(Label("Model name"),
                        Select(*_model_name_options(s.model_name), name="model_name"),
                        cls="s-row"),
                    Div(Label("Market data provider"),
                        Select(*_opts(MARKET_DATA_PROVIDERS, s.market_data_provider),
                               name="market_data_provider"),
                        cls="s-row"),
                    Div(Label("Search provider"),
                        Select(*_opts(SEARCH_PROVIDERS, s.search_provider,
                                      labels={"exa": "exa (coming soon)"}),
                               name="search_provider"),
                        cls="s-row"),
                    Div(Label("Agent framework"),
                        Select(*_opts(AGENT_FRAMEWORKS, s.agent_framework,
                                      labels={"deepagents": "deepagents (default — planning + subagents)",
                                              "hermes": "hermes (LangGraph reasoning + notifier)"}),
                                name="agent_framework"),
                        cls="s-row"),
                    cls="s-grid",
                ),
                Button("Save providers", type="submit", cls="s-btn"),
                method="post", action="/settings/preferences",
            ),
            cls="s-card",
        ),
        P(A("← Back to chat", href="/app"), cls="s-hint"),
        cls="settings",
    )
    return page("settings", Style(_SETTINGS_CSS), body,
                user=user, title="Settings · AlpaTrade", right_news=False)


def register(app, rt):
    """Attach the Settings page + its POST handlers."""

    @rt("/settings", methods=["GET"])
    def settings_get(session, msg: str = ""):
        return _settings_page(_user(session), msg=msg)

    @app.post("/settings/keys")
    async def settings_keys(session, request):
        from urllib.parse import quote_plus
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        form = await request.form()
        api_key = (form.get("api_key") or "").strip()
        secret_key = (form.get("secret_key") or "").strip()
        account_id = (form.get("account_id") or "").strip() or None
        from engine.live_accounts import KeyValidationError, validate_paper_keys
        try:
            validate_paper_keys(api_key, secret_key)
            from engine.auth import store_alpaca_keys
            store_alpaca_keys(user["user_id"], api_key, secret_key,
                              account_name="Default Account", account_id=account_id)
        except (KeyValidationError, ValueError) as exc:
            return RedirectResponse(f"/settings?msg={quote_plus(str(exc))}#integrations", status_code=303)
        try:
            from engine.web.onboarding import record_event
            record_event(user["user_id"], "keys_connected", {"account_id": account_id})
        except Exception:  # noqa: BLE001
            pass
        return RedirectResponse(f"/settings?msg={quote_plus('Paper keys verified and saved.')}#integrations",
                                status_code=303)

    @app.post("/settings/keys/check")
    async def settings_keys_check(session, request):
        from urllib.parse import quote_plus
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        form = await request.form()
        mode, ref = str(form.get("mode") or ""), str(form.get("ref") or "").strip()
        if mode not in ("paper", "live") or not ref:
            return RedirectResponse("/settings#integrations", status_code=303)
        from engine import key_check
        try:
            res = key_check.check(mode, str(user["user_id"]), ref)
        except Exception as exc:  # noqa: BLE001
            logger.warning("key check failed: %s", type(exc).__name__)
            res = {"ok": False, "text": "Check failed, please try again."}
        m = f"{mode.title()} key check: {res['text']}"
        return RedirectResponse(f"/settings?msg={quote_plus(m)}#integrations", status_code=303)

    @app.post("/settings/live-keys")
    async def settings_live_keys(session, request):
        """Any signed-in user may link their own LIVE account: validated read-only, encrypted."""
        from urllib.parse import quote_plus
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        form = await request.form()
        from engine.live_accounts import KeyValidationError, store_live_account, validate_live_keys
        try:
            info = validate_live_keys(form.get("api_key") or "", form.get("secret_key") or "")
            store_live_account(str(user["user_id"]), info["account_number"],
                               (form.get("api_key") or "").strip(), (form.get("secret_key") or "").strip())
        except KeyValidationError as exc:
            return RedirectResponse(f"/settings?msg={quote_plus(str(exc))}#integrations", status_code=303)
        except Exception as exc:  # noqa: BLE001
            logger.warning("live key save failed: %s", type(exc).__name__)
            return RedirectResponse("/settings?msg=Could+not+save+the+live+keys%2C+please+try+again.#integrations",
                                    status_code=303)
        try:
            from engine.web.onboarding import record_event
            record_event(user["user_id"], "live_keys_connected", {"account_number": info["account_number"]})
        except Exception:  # noqa: BLE001
            pass
        ok = f"Live account {info['account_number']} verified and connected (read-only until you activate a strategy)."
        return RedirectResponse(f"/settings?msg={quote_plus(ok)}#integrations", status_code=303)

    @app.post("/settings/live-strategies/{aid}/{action}")
    async def settings_live_strategy(session, aid: int, action: str):
        from urllib.parse import quote_plus
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        from engine.leaderboard.activate import set_status
        ok = set_status(str(user["user_id"]), aid, action)
        m = {"pause": "Live strategy paused.", "resume": "Live strategy resumed.",
             "deactivate": "Live strategy deactivated."}.get(action, "Unknown action.") if ok else "Could not change that strategy."
        return RedirectResponse(f"/settings?msg={quote_plus(m)}#live-strategies", status_code=303)

    @app.post("/settings/live-keys/remove")
    async def settings_live_keys_remove(session, request):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        form = await request.form()
        from engine.live_accounts import deactivate_live_account
        deactivate_live_account(str(user["user_id"]), str(form.get("account_number") or ""))
        return RedirectResponse("/settings?msg=Live+account+disconnected.#integrations", status_code=303)

    @app.post("/settings/preferences")
    async def settings_prefs(session, request):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        form = await request.form()
        from engine.auth import store_user_settings, USER_SETTING_FIELDS
        preferences = {
            f: (form.get(f) or "").strip() for f in USER_SETTING_FIELDS
        }
        provider = preferences.get("model_provider")
        allowed_models = MODEL_NAMES.get(provider, [])
        if allowed_models and preferences.get("model_name") not in allowed_models:
            preferences["model_name"] = allowed_models[0]
        store_user_settings(user["user_id"], **preferences)
        # Phase 3b: evict cached chat + reasoning agents so the new framework/model
        # takes effect on the next message/reasoning call (no process restart).
        try:
            from agui_app import clear_agent_cache
            clear_agent_cache()
        except Exception:  # noqa: BLE001
            pass
        try:
            from engine.autonomy.reason import clear_reasoning_cache
            clear_reasoning_cache()
        except Exception:  # noqa: BLE001
            pass
        return RedirectResponse("/settings?msg=saved", status_code=303)

    @app.post("/settings/reports")
    async def settings_reports(session, request):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        form = await request.form()
        from engine.reporting.preferences import LIVE, PAPER, store_report_preferences
        # Unchecked (and disabled) checkboxes are simply absent from the form, so
        # only write the options the user could actually toggle; a disabled one
        # keeps its stored value until the matching account is connected.
        updates = {}
        if _has_live_account(user["user_id"]):
            updates[LIVE] = form.get(LIVE) == "1"
        if _has_paper_keys(user["user_id"]):
            updates[PAPER] = form.get(PAPER) == "1"
        store_report_preferences(user["user_id"], **updates)
        return RedirectResponse("/settings?msg=saved", status_code=303)

    @app.post("/settings/provider-key")
    async def settings_provider_key(session, request):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        form = await request.form()
        provider_key = (
            form.get("provider_key") or form.get("api_key") or ""
        ).strip()
        if provider_key:
            from engine.auth import store_provider_api_key
            store_provider_api_key(user["user_id"], "xai", provider_key)
            try:
                from agui_app import clear_agent_cache
                clear_agent_cache()
            except Exception:  # noqa: BLE001
                pass
        return RedirectResponse("/settings?msg=saved", status_code=303)

    @app.post("/settings/provider-key/remove")
    async def settings_provider_key_remove(session, request):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        form = await request.form()
        provider = (form.get("provider") or "").strip().lower()
        if provider == "xai":
            from engine.auth import clear_provider_api_key
            clear_provider_api_key(user["user_id"], provider)
            try:
                from agui_app import clear_agent_cache
                clear_agent_cache()
            except Exception:  # noqa: BLE001
                pass
        return RedirectResponse("/settings?msg=saved", status_code=303)

    return ["/settings", "/settings/keys", "/settings/preferences", "/settings/reports",
            "/settings/provider-key", "/settings/provider-key/remove"]
