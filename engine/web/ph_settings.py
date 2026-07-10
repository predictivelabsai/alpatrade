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

Feature-module contract: :func:`register(app, rt)` attaches the routes.
"""
from __future__ import annotations

from fasthtml.common import (
    A, Button, Code, Div, Form, H2, H3, Input, Label, NotStr, Option, P, Select,
    Span, Style,
)
from starlette.responses import RedirectResponse

from engine.web.ph_layout import page
from engine.config import (
    get_settings, MODEL_PROVIDERS, MODEL_NAMES, MARKET_DATA_PROVIDERS,
    SEARCH_PROVIDERS, AGENT_FRAMEWORKS,
)

_SETTINGS_CSS = """
.app{padding-right:0}
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
.settings .s-readonly{font-size:.9rem;color:var(--ink)}
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
        key_status = Span("Not configured — using the server's default keys", cls="s-status no")

    notice = [Div("Saved.", cls="s-notice ok")] if msg == "saved" else []

    account_id = accounts[0]["account_id"] if accounts else ""

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

        # --- Alpaca keys (BYOK) -------------------------------------------
        Div(
            H3("Alpaca API keys (Paper)"),
            P(NotStr("Status: "), key_status, cls="s-hint"),
            Form(
                Input(name="account_id", type="hidden", value=account_id),
                Div(Label("ALPACA_PAPER_API_KEY"),
                    Input(name="api_key", type="password", autocomplete="off",
                          placeholder="PK…", required=True), cls="s-row"),
                Div(Label("ALPACA_PAPER_SECRET_KEY"),
                    Input(name="secret_key", type="password", autocomplete="off",
                          placeholder="••••••••", required=True), cls="s-row"),
                P("Keys are Fernet-encrypted at rest and never leave your account. "
                  "Paper trading only — enter your paper keys.", cls="s-hint"),
                Button("Save keys", type="submit", cls="s-btn"),
                method="post", action="/settings/keys",
            ),
            cls="s-card",
        ),

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
                                      labels={"hermes": "hermes (coming soon)",
                                              "deepagents": "deepagents (coming soon)"}),
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
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        form = await request.form()
        api_key = (form.get("api_key") or "").strip()
        secret_key = (form.get("secret_key") or "").strip()
        account_id = (form.get("account_id") or "").strip() or None
        if api_key and secret_key:
            from engine.auth import store_alpaca_keys
            store_alpaca_keys(user["user_id"], api_key, secret_key,
                              account_name="Default Account", account_id=account_id)
        return RedirectResponse("/settings?msg=saved", status_code=303)

    @app.post("/settings/preferences")
    async def settings_prefs(session, request):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        form = await request.form()
        from engine.auth import store_user_settings, USER_SETTING_FIELDS
        store_user_settings(user["user_id"],
                            **{f: (form.get(f) or "").strip() for f in USER_SETTING_FIELDS})
        return RedirectResponse("/settings?msg=saved", status_code=303)

    return ["/settings", "/settings/keys", "/settings/preferences"]
