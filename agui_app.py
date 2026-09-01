"""
AlpaTrade AG-UI — 3-pane chat interface powered by LangGraph + astream_events.

Left pane:  Auth / settings / navigation / help expanders
Center:     Chat (WebSocket streaming)
Right:      Thinking trace / artifact canvas (toggled)

Launch:  python agui_app.py          # port 5003
         uvicorn agui_app:app --port 5003 --reload
"""

import os
import sys
import uuid as _uuid
import logging
import contextvars
from pathlib import Path
from typing import Dict, Optional

sys.path.insert(0, str(Path(__file__).parent.absolute()))

from dotenv import load_dotenv

load_dotenv()

from fasthtml.common import *

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Google OAuth setup via authlib (optional — gracefully skip if no creds)
# ---------------------------------------------------------------------------

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
_oauth_enabled = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

_authlib_oauth = None
if _oauth_enabled:
    from authlib.integrations.starlette_client import OAuth as AuthlibOAuth
    _authlib_oauth = AuthlibOAuth()
    _authlib_oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

_GOOGLE_SVG = """<svg width="18" height="18" viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg">
<path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.615z" fill="#4285F4"/>
<path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 009 18z" fill="#34A853"/>
<path d="M3.964 10.71A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 000 9s.38 1.572.957 3.042l3.007-2.332z" fill="#FBBC05"/>
<path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/>
</svg>"""

from utils.agui import setup_agui, get_chat_styles, StreamingCommand, list_conversations
import threading


# ---------------------------------------------------------------------------
# Shared harness — moved verbatim to engine/ai/harness.py (Phase 7)
# ---------------------------------------------------------------------------
# ``import agui_app`` keeps its full historical surface: public names come via
# the star re-export, private names (tests/evals call or patch several) are
# listed explicitly. The legacy surface below imports the harness as-is, so
# contextvars and agent caches are shared, never duplicated.
from engine.ai.harness import *  # noqa: F401,F403
from engine.ai.harness import (  # noqa: F401
    _AGUI_HELP,
    _CLI_BASES,
    _CLI_EXACT,
    _NoLinkedAccount,
    _STREAMING_COMMANDS,
    _AppState,
    _alpaca_client,
    _app_states,
    _app_states_lock,
    _chat_role,
    _command_interceptor,
    _current_account_id,
    _current_user_id,
    agent_for_user,
    clear_agent_cache,
    get_app_state,
    set_request_user,
)


# ---------------------------------------------------------------------------
# FastHTML app
# ---------------------------------------------------------------------------

app, rt = fast_app(
    exts="ws",
    secret_key=os.getenv("JWT_SECRET", os.urandom(32).hex()),
    hdrs=[
        Script(src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"),
        Script(src="https://cdn.plot.ly/plotly-2.35.2.min.js"),
        Script(src="/static/voice.js"),
    ],
)

# Voice mode: /ws/voice proxy to the x.ai realtime agent (with the get_positions tool).
from engine.voice import register_voice_routes  # noqa: E402

register_voice_routes(app)


agui = setup_agui(app, primary_agent, command_interceptor=_command_interceptor)


# ---------------------------------------------------------------------------
# CSS — 3-pane layout
# ---------------------------------------------------------------------------

LAYOUT_CSS = """
/* === Layout — Light Only === */

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: #f8fafc;
  color: #1e293b;
  height: 100vh;
  overflow: hidden;
}

/* === 3-Pane Grid === */
.app-layout {
  display: grid;
  grid-template-columns: 260px 1fr;
  height: 100vh;
  transition: grid-template-columns 0.3s ease;
}

.app-layout .right-pane {
  display: none;
}

.app-layout.right-open {
  grid-template-columns: 260px 1fr 380px;
}

.app-layout.right-open .right-pane {
  display: flex;
}

/* === Left Pane (Sidebar) === */
.left-pane {
  background: var(--bg-primary, #ffffff);
  border-right: 1px solid var(--border-color, #e2e8f0);
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  padding: 1rem;
  gap: 1.25rem;
}

.brand {
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--text-primary, #1e293b);
  text-decoration: none;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid var(--border-color, #e2e8f0);
}

.brand:hover { color: var(--accent, #3b82f6); }

.sidebar-section { display: flex; flex-direction: column; gap: 0.5rem; }

.sidebar-section h4 {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--text-secondary, #64748b);
  margin-bottom: 0.25rem;
}

.sidebar-section a {
  color: var(--text-muted, #94a3b8);
  text-decoration: none;
  font-size: 0.85rem;
  padding: 0.35rem 0.5rem;
  border-radius: 0.375rem;
  transition: all 0.15s;
}

.sidebar-section a:hover {
  background: var(--bg-tertiary, #f1f5f9);
  color: var(--text-primary, #1e293b);
}

.sidebar-section a.active {
  background: var(--accent, #3b82f6);
  color: white;
}

/* Auth forms in sidebar */
.sidebar-auth { display: flex; flex-direction: column; gap: 0.75rem; }

.sidebar-auth input {
  width: 100%;
  padding: 0.5rem 0.6rem;
  background: var(--bg-secondary, #f8fafc);
  border: 1px solid var(--border-color, #e2e8f0);
  border-radius: 0.375rem;
  color: var(--text-primary, #1e293b);
  font-family: inherit;
  font-size: 0.8rem;
}

.sidebar-auth input:focus {
  outline: none;
  border-color: var(--accent, #3b82f6);
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.15);
}

.sidebar-auth button {
  width: 100%;
  padding: 0.5rem;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 0.375rem;
  font-family: inherit;
  font-size: 0.8rem;
  cursor: pointer;
}

.sidebar-auth button:hover { background: #2563eb; }

.sidebar-auth .google-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  width: 100%;
  padding: 0.5rem;
  background: #4285f4;
  color: #fff;
  border: none;
  border-radius: 0.375rem;
  font-family: inherit;
  font-size: 0.8rem;
  cursor: pointer;
  text-decoration: none;
  text-align: center;
}

.sidebar-auth .google-btn:hover { background: #3367d6; }

.sidebar-auth .divider {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.7rem;
  color: #94a3b8;
}

.sidebar-auth .divider::before,
.sidebar-auth .divider::after {
  content: '';
  flex: 1;
  border-bottom: 1px solid #e2e8f0;
}

.alt-link { font-size: 0.75rem; color: #64748b; }
.alt-link a { color: #3b82f6; }

.error-msg { color: #dc2626; font-size: 0.8rem; }
.success-msg { color: #16a34a; font-size: 0.8rem; }

.user-info {
  background: var(--bg-secondary, #f8fafc);
  border: 1px solid var(--border-color, #e2e8f0);
  border-radius: 0.5rem;
  padding: 0.75rem;
  font-size: 0.8rem;
}

.user-info .name { font-weight: 600; color: var(--text-primary, #1e293b); }
.user-info .email { color: var(--text-secondary, #64748b); font-size: 0.75rem; }

.key-status {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 1rem;
  font-size: 0.7rem;
  font-weight: 500;
}
.key-status.configured { background: #dcfce7; color: #166534; }
.key-status.not-configured { background: #fef2f2; color: #991b1b; }

.keys-form input {
  width: 100%;
  padding: 0.5rem 0.6rem;
  background: var(--bg-secondary, #f8fafc);
  border: 1px solid var(--border-color, #e2e8f0);
  border-radius: 0.375rem;
  color: var(--text-primary, #1e293b);
  font-family: inherit;
  font-size: 0.8rem;
  margin-bottom: 0.5rem;
}

.keys-form input:focus { outline: none; border-color: var(--accent, #3b82f6); }

.keys-form button {
  width: 100%;
  padding: 0.5rem;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
  font-family: inherit;
  font-size: 0.8rem;
}

/* Logout */
.logout-btn {
  display: block;
  padding: 0.35rem 0.5rem;
  color: #dc2626;
  text-decoration: none;
  font-size: 0.85rem;
  border-radius: 0.375rem;
}
.logout-btn:hover { background: rgba(220, 38, 38, 0.08); }

/* === Center Pane (Chat) === */
.center-pane {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--bg-secondary, #f8fafc);
  overflow: hidden;
}

.center-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1rem;
  background: var(--bg-primary, #ffffff);
  border-bottom: 1px solid var(--border-color, #e2e8f0);
  min-height: 3rem;
}

.center-header h2 {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary, #1e293b);
}

.toggle-trace-btn {
  padding: 0.3rem 0.7rem;
  background: transparent;
  color: #64748b;
  border: 1px solid #e2e8f0;
  border-radius: 0.375rem;
  font-family: inherit;
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.2s;
}

.toggle-trace-btn:hover {
  background: #f1f5f9;
  color: #3b82f6;
  border-color: #3b82f6;
}

.center-chat {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.center-chat > div {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
}

/* Override agui chat styles for layout integration */
.center-chat .chat-container {
  height: 100%;
  flex: 1;
  border: none;
  border-radius: 0;
  background: var(--bg-secondary, #f8fafc);
  display: flex;
  flex-direction: column;
}

.center-chat .chat-messages {
  background: var(--bg-secondary, #f8fafc);
  flex: 1;
}

.center-chat .chat-input {
  background: var(--bg-secondary, #f8fafc);
  border-top: 1px solid var(--border-color, #e2e8f0);
}

.center-chat .chat-input-form {
  background: var(--bg-primary, #ffffff);
  border-color: var(--border-color, #e2e8f0);
}

.center-chat .chat-input-form:focus-within {
  border-color: var(--accent, #3b82f6);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.center-chat .chat-input-field {
  background: transparent;
  color: #1e293b;
}

.center-chat .chat-message.chat-assistant .chat-message-content {
  background: #f8fafc;
  color: #1e293b;
}

.center-chat .chat-message.chat-user .chat-message-content {
  background: #3b82f6;
  color: white;
}

.center-chat .chat-message.chat-tool .chat-message-content {
  background: #e2e8f0;
  color: #64748b;
}

/* === Right Pane (Trace / Artifacts) === */
.right-pane {
  background: var(--bg-primary, #ffffff);
  border-left: 1px solid var(--border-color, #e2e8f0);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.right-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border-color, #e2e8f0);
}

.right-header h3 {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text-primary, #1e293b);
}

.close-trace-btn {
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  font-size: 1.1rem;
  padding: 0.2rem;
}
.close-trace-btn:hover { color: #1e293b; }

.right-tabs {
  display: flex;
  border-bottom: 1px solid #e2e8f0;
}

.right-tab {
  flex: 1;
  padding: 0.5rem;
  text-align: center;
  font-size: 0.75rem;
  color: #64748b;
  cursor: pointer;
  border: none;
  background: none;
  font-family: inherit;
}

.right-tab:hover { color: #94a3b8; }
.right-tab.active { color: #3b82f6; border-bottom: 2px solid #3b82f6; }

.right-content {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
  display: flex;
  flex-direction: column;
}

/* === Trace Entries === */
.trace-entry {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.5rem 0.75rem;
  margin-bottom: 0.5rem;
  border-left: 3px solid #e2e8f0;
  border-radius: 0 0.25rem 0.25rem 0;
  background: #f1f5f9;
  font-size: 0.8rem;
  animation: trace-in 0.2s ease-out;
}

@keyframes trace-in {
  from { opacity: 0; transform: translateX(-0.5rem); }
  to { opacity: 1; transform: translateX(0); }
}

.trace-label {
  color: #94a3b8;
  font-weight: 500;
}

.trace-detail {
  color: #64748b;
  font-size: 0.75rem;
  font-family: ui-monospace, monospace;
  word-break: break-all;
}

.trace-run-start { border-left-color: #3b82f6; }
.trace-run-start .trace-label { color: #3b82f6; }

.trace-run-end { border-left-color: #16a34a; }
.trace-run-end .trace-label { color: #16a34a; }

.trace-streaming { border-left-color: #7c3aed; }
.trace-streaming .trace-label { color: #7c3aed; }

.trace-tool-active { border-left-color: #d97706; }
.trace-tool-active .trace-label { color: #d97706; }

.trace-tool-done { border-left-color: #16a34a; }
.trace-tool-done .trace-label { color: #16a34a; }

.trace-done { border-left-color: #16a34a; }
.trace-done .trace-label { color: #16a34a; }

.trace-error { border-left-color: #dc2626; }
.trace-error .trace-label { color: #dc2626; }

#trace-content {
  font-size: 0.8rem;
  color: #94a3b8;
  overflow-y: auto;
  flex: 1;
}

/* === Artifact Pane === */
#artifact-content {
  display: none;
}

#detail-content {
  display: none;
}

#artifact-content .artifact-chart {
  width: 100%;
  min-height: 300px;
  border-radius: 0.5rem;
  overflow: hidden;
}

#artifact-content .artifact-table {
  width: 100%;
  overflow-x: auto;
  font-size: 0.8rem;
}

/* === Query Badge === */
.query-badge {
  font-size: 0.7rem;
  color: #64748b;
  padding: 0.2rem 0.5rem;
}

/* === Sidebar Header === */
.sidebar-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid #e2e8f0;
}

.sidebar-header .brand {
  border-bottom: none;
  padding-bottom: 0;
}

.chat-badge {
  font-size: 0.6rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  background: #3b82f6;
  color: white;
  padding: 0.15rem 0.4rem;
  border-radius: 0.25rem;
}

/* === New Chat Button === */
.new-chat-btn {
  width: 100%;
  padding: 0.5rem;
  background: transparent;
  border: 1px dashed #cbd5e1;
  border-radius: 0.5rem;
  color: #3b82f6;
  font-family: inherit;
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.2s;
}

.new-chat-btn:hover {
  background: #eff6ff;
  border-color: #93c5fd;
}

/* === Conversation List === */
.conv-section {
  flex: 1;
  min-height: 200px;
  max-height: 35vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.conv-section::-webkit-scrollbar { width: 8px; }
.conv-section::-webkit-scrollbar-track { background: #f1f5f9; border-radius: 4px; }
.conv-section::-webkit-scrollbar-thumb { background: #94a3b8; border-radius: 4px; }
.conv-section::-webkit-scrollbar-thumb:hover { background: #64748b; }

.conv-section h4 {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: #64748b;
  margin-bottom: 0.25rem;
}

.conv-item {
  display: block;
  font-size: 0.8rem;
  padding: 0.5rem 0.6rem;
  color: #475569;
  text-decoration: none;
  border-radius: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: all 0.15s;
}

.conv-item:hover { background: #f1f5f9; color: #1e293b; }
.conv-active { background: #eff6ff; border-left: 2px solid #3b82f6; color: #1e293b; }
.conv-empty { font-style: italic; color: #94a3b8; font-size: 0.75rem; padding: 0.5rem; }

/* === Sidebar Nav === */
.sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding-top: 0.5rem;
  border-top: 1px solid #e2e8f0;
}

.sidebar-nav a {
  color: #64748b;
  text-decoration: none;
  font-size: 0.8rem;
  padding: 0.35rem 0.5rem;
  border-radius: 0.375rem;
  transition: all 0.15s;
}

.sidebar-nav a:hover { background: #f1f5f9; color: #1e293b; }

/* === Sidebar User Compact === */
.sidebar-user-compact {
  margin-top: auto;
  border-top: 1px solid #e2e8f0;
  padding-top: 0.75rem;
}

.sidebar-user-compact .name {
  font-size: 0.8rem;
  font-weight: 600;
  color: #1e293b;
}

.sidebar-user-compact .email {
  font-size: 0.7rem;
  color: #64748b;
}

/* === Sidebar Footer === */
.sidebar-footer {
  font-size: 0.7rem;
  color: #94a3b8;
  text-align: center;
  padding-top: 0.5rem;
}

/* === Help Expanders (sidebar command reference) === */
.help-section {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid #e2e8f0;
}

.help-toggle {
  display: flex;
  align-items: center;
  width: 100%;
  padding: 0.35rem 0.5rem;
  background: none;
  border: none;
  border-radius: 0.375rem;
  color: #475569;
  font-family: inherit;
  font-size: 0.8rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
  text-align: left;
}

.help-toggle:hover { background: var(--bg-tertiary, #f1f5f9); color: var(--text-primary, #1e293b); }

.help-cnt {
  margin-left: auto;
  margin-right: 0.35rem;
  font-size: 0.65rem;
  color: var(--text-muted, #94a3b8);
  background: var(--bg-tertiary, #f1f5f9);
  padding: 0.1rem 0.4rem;
  border-radius: 1rem;
}

.help-arrow {
  color: #94a3b8;
  font-size: 0.65rem;
  transition: transform 0.2s;
}

.help-toggle.open .help-arrow { transform: rotate(90deg); }

.help-list {
  display: none;
  flex-direction: column;
  gap: 0.1rem;
  padding-left: 0.5rem;
}

.help-list.open { display: flex; }

.help-item {
  display: block;
  width: 100%;
  padding: 0.3rem 0.5rem;
  background: none;
  border: none;
  border-radius: 0.25rem;
  color: #3b82f6;
  font-family: ui-monospace, monospace;
  font-size: 0.7rem;
  cursor: pointer;
  text-align: left;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: all 0.15s;
}

.help-item:hover {
  background: var(--table-hover, #eff6ff);
  color: var(--accent-hover, #2563eb);
}

/* === Profile Page === */
.profile-container {
  max-width: 600px;
  margin: 2rem auto;
  padding: 2rem;
  background: var(--bg-primary, #ffffff);
  border-radius: 0.75rem;
  border: 1px solid var(--border-color, #e2e8f0);
  color: var(--text-primary, #1e293b);
}

.profile-container h2 {
  font-size: 1.25rem;
  color: var(--text-primary, #1e293b);
  margin-bottom: 1.5rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid var(--border-color, #e2e8f0);
}

.profile-container h3 {
  font-size: 1rem;
  color: var(--text-primary, #1e293b);
  margin-top: 1.5rem;
  margin-bottom: 0.75rem;
}

.profile-info {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.5rem 1rem;
  font-size: 0.85rem;
  margin-bottom: 1rem;
}

.profile-info dt { color: #64748b; font-weight: 500; }
.profile-info dd { color: #1e293b; margin: 0; }

.profile-container .accounts-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
  margin-bottom: 1rem;
}

.profile-container .accounts-table th {
  text-align: left;
  color: #64748b;
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.5rem;
  border-bottom: 1px solid #e2e8f0;
}

.profile-container .accounts-table td {
  padding: 0.5rem;
  border-bottom: 1px solid #f1f5f9;
  color: #1e293b;
}

.profile-container .keys-form {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.profile-container .keys-form input {
  width: 100%;
  padding: 0.5rem 0.6rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 0.375rem;
  color: #1e293b;
  font-family: inherit;
  font-size: 0.8rem;
}

.profile-container .keys-form input:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.15);
}

.profile-container .keys-form button {
  padding: 0.5rem;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
  font-family: inherit;
  font-size: 0.8rem;
}

.profile-container .keys-form button:hover { background: #2563eb; }

.btn-sm { padding: 0.25rem 0.5rem; font-size: 0.7rem; border-radius: 0.25rem; cursor: pointer; border: none; }
.btn-danger { background: #fee2e2; color: #dc2626; }
.btn-danger:hover { background: #fecaca; }

.profile-container .back-link {
  display: inline-block;
  margin-top: 1.5rem;
  color: #3b82f6;
  text-decoration: none;
  font-size: 0.85rem;
}

.profile-container .back-link:hover { text-decoration: underline; }

/* === Responsive === */
@media (max-width: 768px) {
  .app-layout {
    grid-template-columns: 1fr !important;
  }
  .left-pane { display: none; }
  .right-pane { display: none; }
}
"""


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

FREE_QUERY_LIMIT = 50


def _session_login(session, user: Dict):
    display = user.get("display_name") or ""
    if display.startswith("$2") or not display.strip():
        display = user.get("email", "user").split("@")[0]
    session["user"] = {
        "user_id": str(user["user_id"]),
        "email": user["email"],
        "display_name": display,
    }
    session["query_count"] = 0


# ---------------------------------------------------------------------------
# Help expanders — collapsible command reference in sidebar
# ---------------------------------------------------------------------------

_HELP_CATEGORIES = [
    ("Backtest", [
        ("agent:backtest lookback:1m", "1-month backtest"),
        ("agent:backtest symbols:AAPL,TSLA", "custom symbols"),
        ("agent:backtest hours:extended", "pre/after-market"),
        ("agent:backtest intraday_exit:true", "5-min TP/SL bars"),
        ("agent:backtest pdt:false", "disable PDT rule"),
    ]),
    ("Validate", [
        ("agent:validate run-id:<uuid>", "validate a run"),
        ("agent:reconcile window:14d", "DB vs Alpaca"),
    ]),
    ("Reconcile", [
        ("agent:reconcile window:7d", "7-day reconcile"),
        ("agent:reconcile window:30d", "30-day reconcile"),
    ]),
    ("Paper Trade", [
        ("agent:paper duration:7d", "paper trade 7 days"),
        ("agent:paper symbols:AAPL,MSFT", "custom symbols"),
        ("agent:paper poll:60", "60-second poll"),
        ("agent:paper hours:extended", "extended hours"),
        ("agent:stop", "stop paper trading"),
    ]),
    ("Full Cycle", [
        ("agent:full lookback:1m duration:1m", "backtest + validate + paper"),
        ("agent:full lookback:3m duration:7d", "3-month + 7-day paper"),
    ]),
    ("Trades", [
        ("trades:backtest", "backtest trades"),
        ("trades:paper", "paper trades"),
        ("trades:all", "all types + accounts"),
        ("trades:backtest slug:btd", "filter by slug"),
        ("trades:paper run-id:<uuid>", "specific run"),
    ]),
    ("Runs & Reports", [
        ("runs:backtest", "backtest runs"),
        ("runs:paper", "paper runs"),
        ("report:backtest", "backtest summary"),
        ("report:paper", "paper summary"),
        ("report run-id:<uuid>", "single run detail"),
    ]),
    ("Rankings & P&L", [
        ("top:backtest", "rank backtest strategies"),
        ("top:paper", "rank paper strategies"),
        ("top:all", "all types + accounts"),
        ("pnl run-id:<uuid>", "P&L breakdown"),
    ]),
    ("Monitor", [
        ("positions", "Alpaca positions"),
        ("agent:status", "agent states"),
        ("agent:logs", "log tail"),
        ("agent:stop", "stop background task"),
    ]),
    ("Research", [
        ("load:AAPL", "quote + inline chart"),
        ("load:TSLA period:1y", "custom period"),
        ("news:TSLA", "company news"),
        ("price:AAPL", "stock quote"),
        ("profile:MSFT", "company profile"),
        ("analysts:GOOGL", "analyst ratings"),
        ("financials:AAPL", "income & balance sheet"),
        ("valuation:AAPL,MSFT", "valuation comparison"),
        ("movers", "top gainers & losers"),
        ("chart:AAPL period:1y", "stock chart"),
    ]),
    ("Charts & Equity", [
        ("equity", "latest run equity curve"),
        ("equity backtest", "latest backtest equity"),
        ("equity paper", "latest paper equity"),
        ("equity paper btd", "paper + slug"),
    ]),
    ("Accounts", [
        ("accounts", "list linked accounts"),
        ("account:add <KEY> <SECRET>", "add new account"),
        ("account:switch <num>", "switch active account"),
    ]),
    ("Options", [
        ("hours:extended", "pre/after-market hours"),
        ("pdt:false", "disable PDT rule"),
        ("intraday_exit:true", "intraday TP/SL exits"),
    ]),
]


def _help_expanders():
    """Build collapsible help category groups for the sidebar."""
    groups = []
    for cat_name, items in _HELP_CATEGORIES:
        cat_id = f"help-{cat_name.lower().replace(' ', '-').replace('&', '')}"
        toggle_btn = Button(
            cat_name,
            Span(f"{len(items)}", cls="help-cnt"),
            Span(">", cls="help-arrow"),
            cls="help-toggle",
            onclick=f"toggleGroup('{cat_id}')",
        )
        tool_items = []
        for cmd, desc in items:
            tool_items.append(
                Button(
                    cmd,
                    cls="help-item",
                    onclick=f"fillChat({repr(cmd)})",
                    title=desc,
                )
            )
        tool_list = Div(*tool_items, cls="help-list", id=cat_id)
        groups.append(toggle_btn)
        groups.append(tool_list)

    return Div(*groups, cls="help-section")


# ---------------------------------------------------------------------------
# Left pane builder
# ---------------------------------------------------------------------------

def _left_pane(session):
    """Build the left sidebar: brand, new chat, conversations, nav, auth/user."""
    user = session.get("user")
    thread_id = session.get("thread_id", "")

    parts = []

    # Header: Brand + CHAT badge
    parts.append(
        Div(
            A("AlpaTrade", href="/", cls="brand"),
            Span("CHAT", cls="chat-badge"),
            cls="sidebar-header",
        )
    )

    # New Chat button
    parts.append(
        Button(
            "+ New Chat",
            cls="new-chat-btn",
            onclick="window.location.href='/?new=1'",
        )
    )

    # Help expanders — collapsible command reference
    parts.append(_help_expanders())

    # Conversation list
    parts.append(
        Div(
            H4("Recent"),
            Div(
                id="conv-list",
                hx_get="/agui-conv/list",
                hx_trigger="load",
                hx_swap="innerHTML",
            ),
            cls="conv-section",
        )
    )

    # Navigation
    nav = Div(cls="sidebar-nav")
    nav_links = [A("Dashboard", href="https://alpatrade.dev", target="_blank")]
    if user:
        nav_links.append(A("Profile", href="/profile"))
        nav_links.append(A("Logout", href="/logout", cls="logout-btn"))
    nav = Div(*nav_links, cls="sidebar-nav")
    parts.append(nav)

    # Auth section (compact, at bottom) or user info
    if user:
        name = user.get("display_name") or user.get("email", "user")
        email = user.get("email", "")

        account_count = 0
        try:
            from utils.auth import get_user_accounts
            account_count = len(get_user_accounts(user["user_id"]))
        except Exception:
            pass

        key_badge = (
            Span(f"{account_count} account{'s' if account_count != 1 else ''}", cls="key-status configured")
            if account_count > 0
            else Span("No keys", cls="key-status not-configured")
        )

        parts.append(
            Div(
                Div(name, cls="name"),
                Div(email, cls="email"),
                Div(key_badge, style="margin-top: 0.35rem;"),
                cls="sidebar-user-compact",
            )
        )
    else:
        parts.append(
            Div(
                Div(
                    id="auth-forms",
                    hx_get="/agui-auth/login-form",
                    hx_trigger="load",
                    hx_swap="innerHTML",
                ),
                cls="sidebar-section",
                style="margin-top: auto;",
            )
        )

    # Footer
    parts.append(Div("Powered by AlpaTrade", cls="sidebar-footer"))

    return Div(*parts, cls="left-pane", id="left-pane")


# ---------------------------------------------------------------------------
# Right pane builder
# ---------------------------------------------------------------------------

def _right_pane():
    """Build the right pane: Market News (default) + agent Trace, tabbed."""
    return Div(
        Div(
            H3("Market"),
            Div(
                Button(
                    "↻",
                    cls="close-trace-btn",
                    title="Refresh news",
                    onclick="loadNews(true)",
                    style="margin-right: 0.5rem; font-size: 0.8rem;",
                ),
                Button("x", cls="close-trace-btn", onclick="toggleRightPane()"),
                style="display: flex; align-items: center;",
            ),
            cls="right-header",
        ),
        Div(
            Span("News", cls="right-tab active", id="tab-news",
                 onclick="showRightTab('news')"),
            Span("Trace", cls="right-tab", id="tab-trace",
                 onclick="showRightTab('trace')"),
            cls="right-tabs",
        ),
        Div(
            Div(
                Div("Loading market news…", style="color:#475569;font-style:italic;"),
                id="news-content",
            ),
            Div(
                Div("Tool calls and reasoning will appear here during agent runs.",
                    style="color: #475569; font-style: italic;"),
                id="trace-content",
                style="display:none;",
            ),
            cls="right-content",
        ),
        cls="right-pane",
    )


# ---------------------------------------------------------------------------
# Layout JS
# ---------------------------------------------------------------------------

LAYOUT_JS = """
function toggleRightPane() {
    var layout = document.querySelector('.app-layout');
    layout.classList.toggle('right-open');
}

/* Help expander toggle */
function toggleGroup(catId) {
    var list = document.getElementById(catId);
    if (!list) return;
    list.classList.toggle('open');
    // Find the toggle button (previous sibling)
    var btn = list.previousElementSibling;
    if (btn) btn.classList.toggle('open');
}

/* Fill chat input from sidebar help item */
function fillChat(cmd) {
    if (window._aguiProcessing) return;
    var ta = document.getElementById('chat-input');
    var fm = document.getElementById('chat-form');
    if (ta && fm) {
        ta.value = cmd;
        ta.focus();
    }
}

/* Switch between the News and Trace tabs in the right pane */
function showRightTab(tab) {
    var news = document.getElementById('news-content');
    var trace = document.getElementById('trace-content');
    var tabNews = document.getElementById('tab-news');
    var tabTrace = document.getElementById('tab-trace');
    var isNews = (tab === 'news');
    if (news) news.style.display = isNews ? 'block' : 'none';
    if (trace) trace.style.display = isNews ? 'none' : 'block';
    if (tabNews) tabNews.classList.toggle('active', isNews);
    if (tabTrace) tabTrace.classList.toggle('active', !isNews);
}

/* Load market news into the News tab (cached unless force=true) */
window._newsLoaded = false;
function loadNews(force) {
    var el = document.getElementById('news-content');
    if (!el) return;
    if (window._newsLoaded && !force) return;
    el.innerHTML = '<div style="color:#475569;font-style:italic;">Loading market news…</div>';
    fetch('/news').then(function(r){ return r.text(); }).then(function(md){
        el.innerHTML = (window.marked ? marked.parse(md) : md);
        window._newsLoaded = true;
    }).catch(function(e){
        el.innerHTML = '<div style="color:#ef4444;">Could not load news: ' + e + '</div>';
    });
}

/* A trace arrived — surface the Trace tab so streaming is visible */
function showTab(tab) {
    showRightTab('trace');
}

document.addEventListener('DOMContentLoaded', function() {
    /* Open the right pane and load news by default */
    var layout = document.querySelector('.app-layout');
    if (layout && !layout.classList.contains('right-open')) {
        layout.classList.add('right-open');
    }
    loadNews(false);
});

/* renderChart is a no-op — charts are rendered inline in chat only */
function renderChart(chartJson) {}

/* Download a Plotly chart as PNG */
function downloadChart(chartDiv, filename) {
    if (!window.Plotly || !chartDiv) return;
    Plotly.downloadImage(chartDiv, {format: 'png', width: 1200, height: 600, filename: filename || 'chart'});
}

/* Chart marker cleanup is handled by extractAndRenderCharts() in renderMarkdown() */
"""

VOICE_CSS = """
.voice-btn.active { background:#DC2626 !important; color:#fff !important; border-color:#DC2626 !important; }
.voice-panel { display:flex; align-items:center; gap:12px; margin:0 1rem .5rem; padding:10px 14px;
  border:1px solid #1E293B; border-radius:12px; background:#111A2E; }
.voice-orb { width:12px; height:12px; border-radius:50%; background:#9CA3AF; flex-shrink:0; }
.voice-panel[data-state="listening"] .voice-orb { background:#3B82F6; animation:voicePulse 1.2s infinite; }
.voice-panel[data-state="speaking"]  .voice-orb { background:#10B981; animation:voicePulse .8s infinite; }
.voice-panel[data-state="thinking"]  .voice-orb { background:#F59E0B; animation:voicePulse 1s infinite; }
.voice-panel[data-state="error"]     .voice-orb { background:#DC2626; }
@keyframes voicePulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.4;transform:scale(1.6)} }
.voice-status { flex:1; font-size:13px; color:#E5E7EB; font-weight:500; }
.voice-stop { padding:5px 12px; font-size:12px; font-weight:600; color:#fff; background:#334155;
  border:none; border-radius:8px; cursor:pointer; }
.voice-stop:hover { background:#475569; }
"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@rt("/")
def get(session, new: str = "", thread: str = ""):
    # Force new thread
    if new == "1":
        thread_id = str(_uuid.uuid4())
        session["thread_id"] = thread_id
    elif thread:
        # Resume a specific thread
        thread_id = thread
        session["thread_id"] = thread_id
    else:
        thread_id = session.get("thread_id")
        if not thread_id:
            thread_id = str(_uuid.uuid4())
            session["thread_id"] = thread_id

    return (
        Title("AlpaTrade"),
        Style(LAYOUT_CSS),
        Style(VOICE_CSS),
        Div(
            _left_pane(session),
            Div(
                Div(
                    H2("AlpaTrade Chat"),
                    Button(
                        "🎙 Voice",
                        id="voice-btn",
                        cls="toggle-trace-btn voice-btn",
                        onclick="toggleVoice()",
                        title="Talk to AlpaTrade — ask for your positions",
                        type="button",
                    ),
                    Button(
                        "News",
                        cls="toggle-trace-btn",
                        onclick="toggleRightPane()",
                    ),
                    cls="center-header",
                ),
                Div(agui.chat(thread_id), cls="center-chat"),
                cls="center-pane",
            ),
            _right_pane(),
            cls="app-layout right-open",
        ),
        Script(LAYOUT_JS),
    )


# ---------------------------------------------------------------------------
# Market news feed (right-pane News tab)
# ---------------------------------------------------------------------------

@rt("/news")
def get(ticker: str = ""):
    """Return market news as markdown (rendered client-side via marked.js)."""
    try:
        from utils.market_research_util import MarketResearch
        return MarketResearch().news(ticker=(ticker.upper() or None), limit=12)
    except Exception as e:  # noqa: BLE001
        return f"Could not load news: {e}"


# ---------------------------------------------------------------------------
# Conversation list route
# ---------------------------------------------------------------------------

@rt("/agui-conv/list")
def get(session):
    """Return the conversation list for the sidebar (DB-backed)."""
    current_tid = session.get("thread_id", "")
    user_id = session.get("user", {}).get("user_id") if session.get("user") else None

    try:
        convs = list_conversations(user_id=user_id, limit=20)
    except Exception:
        convs = []

    if not convs:
        return Div(Span("No conversations yet", cls="conv-empty"))

    items = []
    for c in convs:
        tid = c["thread_id"]
        title = c.get("first_msg") or c.get("title") or "New chat"
        if len(title) > 40:
            title = title[:40] + "..."
        cls = "conv-item conv-active" if tid == current_tid else "conv-item"
        items.append(A(title, href=f"/?thread={tid}", cls=cls))

    return Div(*items)


# ---------------------------------------------------------------------------
# Detail panel route — shows run + backtest summary + trades
# ---------------------------------------------------------------------------

@rt("/agui/detail/{run_id}")
def get(run_id: str, session):
    """Fetch run details for the right-pane detail panel."""
    try:
        from utils.db.db_pool import DatabasePool
        from sqlalchemy import text
        pool = DatabasePool()

        with pool.get_session() as db:
            # Fetch run info
            run = db.execute(
                text("SELECT run_id, mode, strategy, status, started_at, completed_at FROM alpatrade.runs WHERE run_id = :rid"),
                {"rid": run_id},
            ).fetchone()

            if not run:
                return Div(P(f"Run {run_id[:8]}... not found.", style="color: #dc2626;"))

            # Fetch backtest summary
            summary = db.execute(
                text("""SELECT sharpe_ratio, total_return, annualized_return, total_pnl,
                               win_rate, total_trades, max_drawdown
                        FROM alpatrade.backtest_summaries WHERE run_id = :rid LIMIT 1"""),
                {"rid": run_id},
            ).fetchone()

            # Fetch trades count
            trade_count = db.execute(
                text("SELECT count(*) FROM alpatrade.trades WHERE run_id = :rid"),
                {"rid": run_id},
            ).scalar() or 0

        # Build detail HTML
        sections = []

        # Key info
        sections.append(Div(
            H4("Run Info", style="font-size: 0.8rem; color: #64748b; margin-bottom: 0.5rem;"),
            Div(
                Div(Span("ID: ", style="color: #64748b;"), Span(str(run[0])[:8], style="font-family: monospace;")),
                Div(Span("Mode: ", style="color: #64748b;"), Span(str(run[1]))),
                Div(Span("Strategy: ", style="color: #64748b;"), Span(str(run[2] or "-"))),
                Div(Span("Status: ", style="color: #64748b;"), Span(str(run[3]))),
                Div(Span("Started: ", style="color: #64748b;"), Span(str(run[4])[:19] if run[4] else "-")),
                style="display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.8rem;",
            ),
            style="margin-bottom: 1rem;",
        ))

        # Metrics (if backtest)
        if summary:
            metrics = [
                ("Sharpe", f"{float(summary[0] or 0):.2f}"),
                ("Return", f"{float(summary[1] or 0):.2f}%"),
                ("Ann. Return", f"{float(summary[2] or 0):.2f}%"),
                ("P&L", f"${float(summary[3] or 0):,.2f}"),
                ("Win Rate", f"{float(summary[4] or 0):.1f}%"),
                ("Trades", str(summary[5] or 0)),
                ("Max DD", f"{float(summary[6] or 0):.2f}%"),
            ]
            metric_els = []
            for label, value in metrics:
                val_style = "font-weight: 600; font-size: 0.85rem;"
                try:
                    num = float(value.replace('%', '').replace(',', '').replace('$', ''))
                    if label in ('Sharpe', 'Return', 'Ann. Return', 'P&L'):
                        val_style += f" color: {'#16a34a' if num >= 0 else '#dc2626'};"
                except ValueError:
                    pass
                metric_els.append(Div(
                    Div(label, style="font-size: 0.65rem; color: #64748b; text-transform: uppercase;"),
                    Div(value, style=val_style),
                ))

            sections.append(Div(
                H4("Metrics", style="font-size: 0.8rem; color: #64748b; margin-bottom: 0.5rem;"),
                Div(
                    *metric_els,
                    style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem;",
                ),
                style="margin-bottom: 1rem;",
            ))

        # Trade count
        sections.append(Div(
            Span(f"{trade_count} trades", style="font-size: 0.8rem; color: #64748b;"),
        ))

        return Div(*sections, id="detail-content", hx_swap_oob="innerHTML")

    except Exception as e:
        return Div(P(f"Error loading details: {e}", style="color: #dc2626; font-size: 0.8rem;"))


# ---------------------------------------------------------------------------
# Auth routes (sidebar-based, return HTML fragments)
# ---------------------------------------------------------------------------

@rt("/agui-auth/login-form")
def login_form_fragment():
    """Return the login form for the sidebar."""
    parts = []
    if _oauth_enabled:
        parts.append(A(NotStr(_GOOGLE_SVG), "Sign in with Google", href="/login", cls="google-btn"))
        parts.append(Div("or", cls="divider"))
    parts.extend([
        Form(
            Input(type="email", name="email", placeholder="Email", required=True),
            Input(type="password", name="password", placeholder="Password", required=True),
            Button("Login", type="submit"),
            hx_post="/agui-auth/login",
            hx_target="#auth-forms",
            hx_swap="innerHTML",
            cls="sidebar-auth",
        ),
        Div(
            "No account? ",
            A("Sign up", href="#", hx_get="/agui-auth/register-form",
              hx_target="#auth-forms", hx_swap="innerHTML"),
            cls="alt-link",
        ),
    ])
    return Div(*parts, cls="sidebar-auth")


@rt("/agui-auth/register-form")
def register_form_fragment():
    """Return the register form for the sidebar."""
    parts = []
    if _oauth_enabled:
        parts.append(A(NotStr(_GOOGLE_SVG), "Sign up with Google", href="/login", cls="google-btn"))
        parts.append(Div("or", cls="divider"))
    parts.extend([
        Form(
            Input(type="email", name="email", placeholder="Email", required=True),
            Input(type="password", name="password", placeholder="Password (min 8 chars)",
                  required=True, minlength="8"),
            Input(type="text", name="display_name", placeholder="Display name (optional)"),
            Button("Create Account", type="submit"),
            hx_post="/agui-auth/register",
            hx_target="#auth-forms",
            hx_swap="innerHTML",
            cls="sidebar-auth",
        ),
        Div(
            "Have an account? ",
            A("Login", href="#", hx_get="/agui-auth/login-form",
              hx_target="#auth-forms", hx_swap="innerHTML"),
            cls="alt-link",
        ),
    ])
    return Div(*parts, cls="sidebar-auth")


@rt("/agui-auth/login")
def auth_login(session, email: str = "", password: str = ""):
    if not email or not password:
        return Div(P("Email and password required.", cls="error-msg"),
                   login_form_fragment())
    from utils.auth import authenticate
    user = authenticate(email, password)
    if not user:
        return Div(P("Invalid email or password.", cls="error-msg"),
                   login_form_fragment())
    _session_login(session, user)
    # Refresh the whole page to update sidebar
    return Div(
        P("Logged in!", cls="success-msg"),
        Script("setTimeout(function(){ window.location.reload(); }, 500);"),
    )


@rt("/agui-auth/register")
def auth_register(session, email: str = "", password: str = "", display_name: str = ""):
    if not email or not password:
        return Div(P("Email and password required.", cls="error-msg"),
                   register_form_fragment())
    if len(password) < 8:
        return Div(P("Password must be at least 8 characters.", cls="error-msg"),
                   register_form_fragment())
    from utils.auth import create_user, get_user_by_email
    existing = get_user_by_email(email)
    if existing:
        return Div(
            P("An account with this email already exists. Please sign in instead.", cls="error-msg"),
            login_form_fragment(),
        )
    user = create_user(email=email, password=password, display_name=display_name or None)
    if not user:
        return Div(P("Unable to create account. Please try again.", cls="error-msg"),
                   register_form_fragment())
    _session_login(session, user)
    return Div(
        P("Account created!", cls="success-msg"),
        Script("setTimeout(function(){ window.location.reload(); }, 500);"),
    )


@rt("/logout")
def logout(session):
    session.clear()
    return RedirectResponse("/", status_code=307)


@rt("/profile")
def profile(session, msg: str = ""):
    user = session.get("user")
    if not user:
        return RedirectResponse("/")

    # Fetch all accounts for this user (includes keys added from CLI)
    accounts = []
    try:
        from utils.auth import get_user_accounts
        accounts = get_user_accounts(user["user_id"])
    except Exception:
        pass

    account_count = len(accounts)
    key_badge = (
        Span(f"{account_count} account{'s' if account_count != 1 else ''}", cls="key-status configured")
        if account_count > 0
        else Span("Not configured", cls="key-status not-configured")
    )

    # Check if user has a password set (Google-only users may not)
    user_has_password = False
    try:
        from utils.auth import has_password
        user_has_password = has_password(user["user_id"])
    except Exception:
        pass

    parts = [
        H2("Profile"),
    ]

    if msg:
        parts.append(P(msg, cls="success-msg"))

    # --- Display Name & Email section ---
    parts.extend([
        H3("Account Info"),
        Form(
            Label("Email", For="email"),
            Input(type="email", id="email", value=user.get("email", ""), disabled=True,
                  style="background: #e2e8f0; cursor: not-allowed;"),
            Label("Display Name", For="display_name"),
            Input(type="text", id="display_name", name="display_name",
                  value=user.get("display_name", ""), placeholder="Your display name", required=True),
            Button("Update Name", type="submit"),
            method="post", action="/profile/name", cls="keys-form",
        ),
    ])

    # --- Password section ---
    parts.append(H3("Change Password" if user_has_password else "Set Password"))
    if user_has_password:
        parts.append(
            Form(
                Input(type="password", name="current_password",
                      placeholder="Current password", required=True),
                Input(type="password", name="new_password",
                      placeholder="New password (min 8 chars)", required=True, minlength="8"),
                Input(type="password", name="confirm_password",
                      placeholder="Confirm new password", required=True, minlength="8"),
                Button("Change Password", type="submit"),
                method="post", action="/profile/password", cls="keys-form",
            )
        )
    else:
        parts.append(
            Form(
                P("You signed in with Google. Set a password to also log in with email.",
                  style="color: #64748b; font-size: 0.85rem;"),
                Input(type="password", name="new_password",
                      placeholder="New password (min 8 chars)", required=True, minlength="8"),
                Input(type="password", name="confirm_password",
                      placeholder="Confirm new password", required=True, minlength="8"),
                Button("Set Password", type="submit"),
                method="post", action="/profile/password", cls="keys-form",
            )
        )

    # --- Alpaca accounts badge ---
    parts.append(H3("Alpaca Accounts"))
    parts.append(P(key_badge))

    # Show existing accounts table (synced from CLI and web)
    if accounts:
        rows = []
        for i, acct in enumerate(accounts, 1):
            rows.append(Tr(
                Td(str(i)),
                Td(acct.get("account_name", "—")),
                Td(Code(acct.get("api_key_hint", "****"))),
                Td(
                    Form(
                        Input(type="hidden", name="account_id", value=acct["account_id"]),
                        Button("Remove", type="submit", cls="btn-sm btn-danger"),
                        method="post", action="/profile/keys/remove",
                    )
                ),
            ))
        parts.extend([
            H3("Your Alpaca Accounts"),
            P("Accounts added from the web, chat, or CLI all appear here. Keys are encrypted at rest.",
              style="color: #64748b; font-size: 0.8rem;"),
            Table(
                Thead(Tr(Th("#"), Th("Name"), Th("API Key"), Th(""))),
                Tbody(*rows),
                cls="accounts-table",
            ),
        ])

    # Add new account form
    parts.extend([
        H3("Add Alpaca Account"),
        Form(
            Input(type="text", name="account_name",
                  placeholder="Account name (optional)", value=""),
            Input(type="password", name="api_key",
                  placeholder="Alpaca Paper API Key", required=True),
            Input(type="password", name="secret_key",
                  placeholder="Alpaca Paper Secret Key", required=True),
            Button("Save Keys", type="submit"),
            method="post", action="/profile/keys", cls="keys-form",
        ),
    ])

    return (
        Title("Profile — AlpaTrade"),
        Style(LAYOUT_CSS),
        Div(
            Div(
                A("← Back to Chat", href="/", cls="back-link"),
                *parts,
                A("← Back to Chat", href="/", cls="back-link", style="margin-top: 1.5rem;"),
                cls="profile-container",
            ),
            style="height: 100vh; overflow-y: auto; background: #f8fafc; padding: 1rem;",
        ),
    )


@rt("/profile/name")
def profile_name(session, display_name: str = ""):
    user = session.get("user")
    if not user:
        return RedirectResponse("/")
    if not display_name.strip():
        return RedirectResponse("/profile?msg=Display+name+cannot+be+empty", status_code=303)
    try:
        from utils.auth import update_display_name
        if update_display_name(user["user_id"], display_name):
            session["user"]["display_name"] = display_name.strip()
            return RedirectResponse("/profile?msg=Display+name+updated", status_code=303)
        return RedirectResponse("/profile?msg=Failed+to+update+name", status_code=303)
    except Exception as e:
        logger.error(f"Failed to update display name: {e}")
        return RedirectResponse("/profile?msg=Error+updating+name", status_code=303)


@rt("/profile/password")
def profile_password(session, current_password: str = "", new_password: str = "", confirm_password: str = ""):
    user = session.get("user")
    if not user:
        return RedirectResponse("/")
    if new_password != confirm_password:
        return RedirectResponse("/profile?msg=Passwords+do+not+match", status_code=303)
    if len(new_password) < 8:
        return RedirectResponse("/profile?msg=Password+must+be+at+least+8+characters", status_code=303)
    try:
        from utils.auth import has_password, verify_password, get_user_by_email, update_password
        # If user already has a password, verify the current one
        if has_password(user["user_id"]):
            if not current_password:
                return RedirectResponse("/profile?msg=Current+password+is+required", status_code=303)
            db_user = get_user_by_email(user["email"])
            if not db_user or not verify_password(current_password, db_user["password_hash"]):
                return RedirectResponse("/profile?msg=Current+password+is+incorrect", status_code=303)
        if update_password(user["user_id"], new_password):
            return RedirectResponse("/profile?msg=Password+updated+successfully", status_code=303)
        return RedirectResponse("/profile?msg=Failed+to+update+password", status_code=303)
    except Exception as e:
        logger.error(f"Failed to update password: {e}")
        return RedirectResponse("/profile?msg=Error+updating+password", status_code=303)


@rt("/profile/keys")
def profile_keys(session, api_key: str = "", secret_key: str = "", account_name: str = ""):
    user = session.get("user")
    if not user:
        return RedirectResponse("/")
    if not api_key or not secret_key:
        return RedirectResponse("/profile?msg=Both+keys+are+required", status_code=303)
    try:
        from utils.auth import store_alpaca_keys
        name = account_name.strip() or "Default Account"
        store_alpaca_keys(user["user_id"], api_key, secret_key, account_name=name)
        return RedirectResponse("/profile?msg=Alpaca+keys+saved+successfully", status_code=303)
    except Exception as e:
        logger.error(f"Failed to store Alpaca keys: {e}")
        return RedirectResponse("/profile?msg=Error+saving+keys", status_code=303)


@rt("/profile/keys/remove")
def profile_keys_remove(session, account_id: str = ""):
    user = session.get("user")
    if not user:
        return RedirectResponse("/")
    if not account_id:
        return RedirectResponse("/profile", status_code=303)
    try:
        from utils.db.db_pool import DatabasePool
        from sqlalchemy import text
        pool = DatabasePool()
        with pool.get_session() as db:
            db.execute(
                text("""
                    UPDATE alpatrade.user_accounts
                    SET is_active = FALSE, updated_at = NOW()
                    WHERE account_id = :account_id AND user_id = :user_id
                """),
                {"account_id": account_id, "user_id": user["user_id"]},
            )
        return RedirectResponse("/profile?msg=Account+removed", status_code=303)
    except Exception as e:
        logger.error(f"Failed to remove account: {e}")
        return RedirectResponse("/profile?msg=Error+removing+account", status_code=303)


# ---------------------------------------------------------------------------
# Static content routes (open in new tabs from sidebar)
# ---------------------------------------------------------------------------

@rt("/guide")
def guide(session):
    """Minimal guide redirect — full guide lives on web_app.py."""
    return (
        Title("Guide — AlpaTrade"),
        Style(LAYOUT_CSS),
        Div(
            Div(
                A("AlpaTrade", href="/", cls="brand"),
                Div(
                    H4("Quick Reference"),
                    P("Full guide available at ",
                      A("alpatrade.chat/guide", href="https://alpatrade.chat/guide",
                        target="_blank"),
                      style="font-size: 0.85rem; color: #94a3b8;"),
                    cls="sidebar-section",
                ),
                Div(
                    H4("Common Commands"),
                    P("agent:backtest lookback:1m", style="font-size: 0.8rem;"),
                    P("agent:paper duration:7d", style="font-size: 0.8rem;"),
                    P("price AAPL", style="font-size: 0.8rem;"),
                    P("news TSLA", style="font-size: 0.8rem;"),
                    P("trades / runs / status", style="font-size: 0.8rem;"),
                    cls="sidebar-section",
                ),
                Div(A("Back to Chat", href="/"), cls="sidebar-section"),
                cls="left-pane",
                style="max-width: 400px; margin: 2rem auto; height: auto;",
            ),
            style="display: flex; justify-content: center; min-height: 100vh; background: #0f172a;",
        ),
    )


@rt("/screenshots")
def screenshots():
    """Redirect to main app screenshots."""
    return RedirectResponse("https://alpatrade.chat/screenshots", status_code=307)


# ---------------------------------------------------------------------------
# Google OAuth routes
# ---------------------------------------------------------------------------

if _oauth_enabled:
    @rt("/login")
    async def login_get(request):
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("host", request.url.netloc)
        redirect_uri = f"{scheme}://{host}/auth/callback"
        return await _authlib_oauth.google.authorize_redirect(request, redirect_uri)

    @rt("/auth/callback")
    async def auth_callback(request, session):
        try:
            token = await _authlib_oauth.google.authorize_access_token(request)
        except Exception as e:
            logger.error(f"OAuth token exchange failed: {e}")
            return RedirectResponse("/?error=Google+login+failed")

        userinfo = token.get("userinfo", {})
        if not userinfo:
            userinfo = await _authlib_oauth.google.userinfo(token=token)

        google_id = userinfo.get("sub", "")
        email = userinfo.get("email", "")
        name = userinfo.get("name", "")

        if not email:
            return RedirectResponse("/?error=Google+did+not+provide+email")

        from utils.auth import get_user_by_google_id, get_user_by_email, create_user, link_google_id

        user = get_user_by_google_id(google_id) if google_id else None

        if not user:
            user = get_user_by_email(email)
            if user and google_id:
                link_google_id(email, google_id)
            elif not user:
                user = create_user(email=email, google_id=google_id, display_name=name)

        if user:
            _session_login(session, user)
        else:
            return RedirectResponse("/?error=Could+not+create+account")

        return RedirectResponse("/")

if not _oauth_enabled:
    @rt("/login")
    def login_get():
        return RedirectResponse("/")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import socket
    import uvicorn

    DEFAULT_PORT = 5003
    MAX_TRIES = 10

    def _port_free(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return True
            except OSError:
                return False

    port = DEFAULT_PORT
    for p in range(DEFAULT_PORT, DEFAULT_PORT + MAX_TRIES):
        if _port_free(p):
            port = p
            break

    if port != DEFAULT_PORT:
        print(f"Port {DEFAULT_PORT} in use, using port {port}")

    reload = os.environ.get("AGUI_RELOAD", "true").lower() == "true"
    uvicorn.run(
        "agui_app:app",
        host="0.0.0.0",
        port=port,
        reload=reload,
    )
