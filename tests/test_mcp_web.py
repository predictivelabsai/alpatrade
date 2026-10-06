"""DB-free tests for the signed-in MCP connection wizard."""
from fasthtml.common import fast_app, to_xml
from starlette.testclient import TestClient

from engine.web import ph_mcp


USER = {"user_id": "11111111-1111-1111-1111-111111111111",
        "email": "user@example.com"}


def test_mcp_page_explains_local_step_without_exposing_token_on_get():
    html = to_xml(ph_mcp._mcp_page(USER))
    assert "Connect AlpaTrade to your AI client" in html
    assert "Generate 7-day connection" in html
    assert "browser cannot edit desktop settings" in html
    assert "ALPATRADE_ACCESS_TOKEN" not in html
    assert "PAPER confirmation" in html


def test_generated_config_supports_codex_claude_and_json():
    snippets = ph_mcp._snippets("signed-test-token", r"C:\projects\alpatrade")
    assert set(snippets) == {"Codex", "Claude Code", "Other MCP clients"}
    assert "codex mcp add alpatrade" in snippets["Codex"]
    assert "claude mcp add alpatrade" in snippets["Claude Code"]
    assert "ALPATRADE_API_URL=https://api.alpatrade.chat" in snippets["Codex"]
    assert all("signed-test-token" in value for value in snippets.values())
    assert '"mcpServers"' in snippets["Other MCP clients"]


def test_generated_page_marks_token_as_show_once_and_copyable():
    html = to_xml(ph_mcp._mcp_page(
        USER, token="signed-test-token", local_path=r"C:\projects\alpatrade"
    ))
    assert "shown only in this response" in html
    assert html.count("signed-test-token") == 3
    assert html.count("Copy configuration") == 3
    assert "copyMcpConfig" in html


def test_mcp_token_route_requires_login(monkeypatch):
    app, rt = fast_app()
    ph_mcp.register(app, rt)
    monkeypatch.setattr(ph_mcp, "_user", lambda _session: None)
    response = TestClient(app).post(
        "/settings/mcp/token", data={"local_path": r"C:\repo"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/signin"


def test_mcp_token_route_generates_token_for_current_user(monkeypatch):
    app, rt = fast_app()
    ph_mcp.register(app, rt)
    monkeypatch.setattr(ph_mcp, "_user", lambda _session: USER)
    monkeypatch.setattr("engine.auth.create_jwt_token",
                        lambda uid, email: f"token-for-{uid}-{email}")
    response = TestClient(app).post(
        "/settings/mcp/token", data={"local_path": r"C:\repo"}
    )
    assert response.status_code == 200
    assert "token-for-11111111-1111-1111-1111-111111111111-user@example.com" in response.text
    assert "C:\\repo" in response.text
