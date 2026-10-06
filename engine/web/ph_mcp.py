"""Signed-in MCP connection wizard for desktop AI clients."""
from __future__ import annotations

import json
import shlex

from fasthtml.common import (
    A, Button, Code, Div, Form, H1, H2, Input, Label, NotStr, P, Pre, Span,
    Strong, Style,
)
from starlette.responses import RedirectResponse

from engine.web.ph_layout import page


_CSS = """
.mcp-page{max-width:860px;margin:0 auto;width:100%;padding:0 1rem 3rem}
.mcp-page h1{font-size:1.45rem;margin:.4rem 0 .25rem;color:var(--ink)}
.mcp-lead{font-size:1rem;line-height:1.55;color:var(--ink-muted);margin:0 0 1.3rem}
.mcp-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:.75rem;margin:1rem 0}
.mcp-step,.mcp-card{background:var(--bg-elev);border:1px solid var(--line);border-radius:.7rem}
.mcp-step{padding:.85rem}.mcp-step strong{display:block;margin-bottom:.25rem;color:var(--ink)}
.mcp-step span{font-size:.78rem;line-height:1.45;color:var(--ink-dim)}
.mcp-card{padding:1.1rem 1.3rem;margin-bottom:1rem}
.mcp-card h2{font-size:1rem;margin:0 0 .3rem;color:var(--ink)}
.mcp-hint{font-size:.78rem;line-height:1.5;color:var(--ink-dim);margin:.2rem 0 .8rem}
.mcp-row{display:flex;flex-direction:column;gap:.3rem;margin:.8rem 0}
.mcp-row label{font-size:.78rem;font-weight:650;color:var(--ink-muted)}
.mcp-row input{font:inherit;font-size:1rem;color:var(--ink);background:var(--bg);border:1px solid var(--line-br);border-radius:.45rem;padding:.6rem;width:100%}
.mcp-btn{min-height:44px;border:0;border-radius:.45rem;padding:.58rem 1rem;background:var(--accent);color:var(--bg);font-weight:650;cursor:pointer;transition:opacity .18s ease}
.mcp-btn.secondary{background:var(--accent-dim);color:var(--accent-deep);border:1px solid var(--line-br);margin-top:.55rem}
.mcp-btn:hover{opacity:.88}
.mcp-btn:focus-visible,.mcp-row input:focus-visible{outline:3px solid var(--accent-dim);outline-offset:2px}
.mcp-secret{background:#fff8e6;border-left:4px solid #b7791f;padding:.75rem .9rem;border-radius:.35rem;font-size:.8rem;line-height:1.5;margin-bottom:1rem}
.mcp-code pre{overflow:auto;white-space:pre-wrap;word-break:break-word;background:#10281f;color:#f4f1e8;border-radius:.5rem;padding:.85rem;font-size:.76rem;line-height:1.45;margin:.6rem 0 0}
.mcp-ok{color:var(--accent-deep);font-size:.78rem;font-weight:650}
@media(max-width:680px){.mcp-grid{grid-template-columns:1fr}.mcp-page{padding:0 .75rem 2rem}}
@media(prefers-reduced-motion:reduce){.mcp-btn{transition:none}}
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


def _snippets(token: str, local_path: str) -> dict[str, str]:
    """Return copy-ready configurations without writing the token to disk here."""
    api_url = "https://api.alpatrade.chat"
    path = local_path.strip() or r"C:\path\to\alpatrade"
    quoted_path = shlex.quote(path)
    return {
        "Codex": (
            f"codex mcp add alpatrade --env ALPATRADE_API_URL={api_url} "
            f"--env ALPATRADE_ACCESS_TOKEN={token} -- uv run --directory "
            f"{quoted_path} alpatrade-mcp"
        ),
        "Claude Code": (
            f"claude mcp add alpatrade --scope user "
            f"-e ALPATRADE_API_URL={api_url} -e ALPATRADE_ACCESS_TOKEN={token} -- "
            f"uv run --directory {quoted_path} alpatrade-mcp"
        ),
        "Other MCP clients": json.dumps({
            "mcpServers": {"alpatrade": {
                "command": "uv",
                "args": ["run", "--directory", path, "alpatrade-mcp"],
                "env": {"ALPATRADE_API_URL": api_url,
                        "ALPATRADE_ACCESS_TOKEN": token},
            }}
        }, indent=2),
    }


def _copy_block(title: str, value: str, index: int):
    target = f"mcp-config-{index}"
    return Div(
        H2(title),
        Div(Pre(Code(value, id=target)), cls="mcp-code"),
        Button("Copy configuration", type="button", cls="mcp-btn secondary",
               aria_label=f"Copy {title} configuration",
               onclick=f"copyMcpConfig('{target}', this)"),
        cls="mcp-card",
    )


def _mcp_page(user, *, token: str = "", local_path: str = ""):
    if not user:
        return RedirectResponse("/signin", status_code=303)
    generated = []
    if token:
        generated = [
            Div(
                Strong("Connection token generated."),
                " It expires after seven days and is shown only in this response. "
                "Treat copied configuration as a secret.",
                cls="mcp-secret",
            ),
            *[_copy_block(name, value, i) for i, (name, value) in
              enumerate(_snippets(token, local_path).items())],
        ]
    body = Div(
        H1("Connect AlpaTrade to your AI client"),
        P("Use AlpaTrade research, portfolio and paper-trading tools from Codex, "
          "Claude Code or another MCP client. Live trading, arbitrary SQL and "
          "unrestricted HTTP are not exposed.", cls="mcp-lead"),
        Div(
            Div(Strong("1. Generate"), Span("Create a seven-day token for your account."), cls="mcp-step"),
            Div(Strong("2. Copy"), Span("Copy the command for your desktop client."), cls="mcp-step"),
            Div(Strong("3. Restart"), Span("Restart the client and ask it to use AlpaTrade."), cls="mcp-step"),
            cls="mcp-grid",
        ),
        Div(
            H2("Generate connection configuration"),
            P("Enter the repository folder on the computer where the AI client runs. "
              "A browser cannot edit desktop settings, so you will paste one generated "
              "command into PowerShell or Terminal.", cls="mcp-hint"),
            Form(
                Div(Label("Local AlpaTrade folder", fr="mcp-local-path"),
                    Input(id="mcp-local-path", name="local_path", value=local_path,
                          placeholder=r"C:\Users\you\projects\alpatrade", required=True,
                          autocomplete="off"), cls="mcp-row"),
                Button("Generate 7-day connection", type="submit", cls="mcp-btn"),
                method="post", action="/settings/mcp/token",
            ), cls="mcp-card",
        ),
        *generated,
        Div(
            H2("Test after connecting"),
            P(Code("Use AlpaTrade to show my recent runs."), cls="mcp-hint"),
            P(Code("Use AlpaTrade to compare Buy the Dip, Momentum and VIX using walk-forward validation."), cls="mcp-hint"),
            P("Paper orders still require explicit PAPER confirmation.", cls="mcp-ok"),
            cls="mcp-card",
        ),
        P(A("← Back to Settings", href="/settings"), cls="mcp-hint"),
        NotStr("""<script>
async function copyMcpConfig(id, button) {
  const text = document.getElementById(id).textContent;
  try {
    await navigator.clipboard.writeText(text);
    const old = button.textContent;
    button.textContent = 'Copied';
    setTimeout(() => { button.textContent = old; }, 1800);
  } catch (_) { button.textContent = 'Select and copy manually'; }
}
</script>"""),
        cls="mcp-page",
    )
    return page("mcp", Style(_CSS), body, user=user,
                title="MCP Connections · AlpaTrade", right_news=False)


def register(app, rt):
    @rt("/settings/mcp", methods=["GET"])
    def mcp_get(session):
        return _mcp_page(_user(session))

    @app.post("/settings/mcp/token")
    async def mcp_token(session, request):
        user = _user(session)
        if not user:
            return RedirectResponse("/signin", status_code=303)
        form = await request.form()
        local_path = str(form.get("local_path") or "").strip()[:500]
        if not local_path:
            return _mcp_page(user)
        from engine.auth import create_jwt_token
        token = create_jwt_token(str(user["user_id"]), str(user.get("email") or ""))
        return _mcp_page(user, token=token, local_path=local_path)

    return ["/settings/mcp", "/settings/mcp/token"]
