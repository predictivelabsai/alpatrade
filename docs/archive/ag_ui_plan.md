# AG-UI: Alternative 3-Pane Web Interface for AlpaTrade

## Overview

Replace the current single-column HTMX-polling UI (`web_app.py`) with a 3-pane WebSocket-streaming UI (`ag_ui.py`) powered by **ft-agui** + **pydantic-ai** + **AG-UI protocol**.

```
+------------------+----------------------------+---------------------+
|  LEFT PANE       |  CENTER PANE               |  RIGHT PANE         |
|  (280px fixed)   |  (flex: 1)                 |  (400px, toggle)    |
|                  |                            |                     |
|  [AlpaTrade]     |  Chat Messages             |  Thinking Trace     |
|                  |  - user commands           |  - tool calls       |
|  -- Auth --      |  - agent responses         |  - reasoning steps  |
|  Login/Register  |  - charts inline           |  - state snapshots  |
|  or              |  - tables inline           |                     |
|  Profile/Keys    |                            |  Artifact Canvas    |
|                  |                            |  - Plotly charts    |
|  -- Nav --       |                            |  - backtest tables  |
|  Home            |                            |  - trade details    |
|  Guide           |                            |                     |
|  Dashboard       |                            |                     |
|  Download        |                            |                     |
|                  |                            |                     |
|  -- Status --    |  +----------------------+  |                     |
|  Keys: OK/None   |  | > command input      |  |  [x] Close         |
|  Queries: 12/50  |  +----------------------+  |                     |
+------------------+----------------------------+---------------------+
```

---

## Architecture

```
Browser  <-- WebSocket -->  FastHTML (ag_ui.py)
                              |
                              +-- ft-agui routes (/agui/ws, /agui/ui)
                              |     |
                              |     +-- pydantic-ai Agent
                              |           |
                              |           +-- tools: backtest, paper_trade, report, etc.
                              |           +-- deps: user_id, alpaca_keys, session
                              |
                              +-- Custom routes (/register, /signin, /profile, etc.)
                              +-- Static routes (/guide, /download, /screenshots)
```

**Key shift:** Instead of CommandProcessor parsing text commands, a **pydantic-ai Agent** interprets user intent and calls tools. The CLI shortcut syntax (`agent:backtest lookback:1m`) still works -- the agent recognizes it and routes to the correct tool.

---

## Entry Point: `ag_ui.py`

```bash
python ag_ui.py          # Starts on port 5003
# or
uvicorn ag_ui:app --port 5003 --reload
```

Runs alongside existing `web_app.py` (port 5002) -- no disruption.

---

## Pane Details

### Left Pane (Settings/Auth Sidebar)

- **Brand**: "AlpaTrade" logo/text
- **Auth Section** (swaps based on login state):
  - Anonymous: Login form (email/password) + "Sign up" link + Google OAuth button
  - Logged in: Display name, email, Alpaca key status (green/red indicator)
  - Profile quick-edit: Set/update Alpaca keys inline
- **Navigation**: Home, Guide, Dashboard (external), Download, Screenshots
- **Session Status**: Query count badge, key status indicator
- **Collapsible on mobile** (hamburger menu)

### Center Pane (Chat)

- **Message history**: Scrollable, auto-scroll on new messages
- **User messages**: Right-aligned, monospace, command echo style
- **Agent responses**: Left-aligned, rendered markdown (tables, code blocks, lists)
- **Inline charts**: Plotly charts embedded directly in message flow
- **Input bar**: Bottom-anchored, Enter to send, Shift+Enter for newline
- **Suggestion chips**: Quick-access buttons for common commands
- **Streaming**: Token-by-token via WebSocket (AG-UI TextMessageContentEvent)

### Right Pane (Thinking Trace / Artifact Canvas)

- **Hidden by default**, slides in when agent starts tool calls or produces artifacts
- **Toggle button** in top bar or auto-show on activity
- **Two tabs**:
  1. **Thinking Trace**: Real-time display of tool calls, reasoning steps, state changes
  2. **Artifacts**: Full-size Plotly charts, backtest summary tables, trade details
- **Resizable** via drag handle
- **Closeable** -- right pane collapses, center pane expands

---

## pydantic-ai Agent Design

```python
from pydantic_ai import Agent
from pydantic_ai.ui import StateDeps

class AlpaTradeState(BaseModel):
    """Shared state visible in right pane."""
    last_chart_json: Optional[str] = None
    last_backtest_summary: Optional[dict] = None
    active_paper_trades: Optional[list] = None
    portfolio_value: Optional[float] = None

    def __ft__(self):
        # Custom FastHTML rendering for state pane
        ...

agent = Agent(
    "xai:grok-3-mini",
    system_prompt="You are AlpaTrade assistant...",
    tools=[
        run_backtest,       # agent:backtest equivalent
        run_paper_trade,    # agent:paper equivalent
        show_trades,        # trades command
        show_runs,          # runs command
        get_price,          # price AAPL
        get_news,           # news AAPL
        show_report,        # agent:report
        manage_portfolio,   # buy/sell via Alpaca
        reconcile,          # agent:reconcile
    ],
    deps_type=AlpaTradeDeps,
    output_type=str,
)
```

Each tool wraps existing business logic (CommandProcessor methods, agent orchestrator calls). The LLM decides which tool to invoke based on user input. CLI shortcuts like `agent:backtest lookback:1m` are recognized by the system prompt.

---

## Pros & Cons

### Pros

| # | Advantage | Detail |
|---|-----------|--------|
| 1 | **Real-time streaming** | WebSocket replaces HTMX polling -- no 1s delay, instant token delivery |
| 2 | **Thinking trace visibility** | Users see tool calls, reasoning, and state changes in real time (right pane) |
| 3 | **Natural language + shortcuts** | Users can type "backtest AAPL last month" OR `agent:backtest lookback:1m` |
| 4 | **Artifact canvas** | Charts and tables get dedicated space, not squeezed into chat scroll |
| 5 | **Cleaner architecture** | pydantic-ai Agent replaces manual command routing logic (200+ lines of if/elif) |
| 6 | **State management** | AG-UI StateSnapshotEvent keeps client/server state in sync automatically |
| 7 | **Multi-thread support** | ft-agui manages conversation threads -- chat history persists per thread |
| 8 | **Modern UX** | 3-pane layout is familiar (Slack, Discord, Claude.ai, Cursor) |
| 9 | **Extensible** | Adding new tools = adding new pydantic-ai tool functions, agent handles routing |
| 10 | **Protocol standard** | AG-UI is an emerging open protocol (CopilotKit, Google, AWS, LangChain backing) |

### Cons / Risks

| # | Risk | Mitigation |
|---|------|------------|
| 1 | **ft-agui is v0.1.0** | Very early, API may break. Pin version, vendor critical parts if needed. |
| 2 | **No thinking trace rendering yet** | ft-agui doesn't patch `__ft__()` on ReasoningEvents. We must add custom patches. |
| 3 | **LLM cost per interaction** | Every message hits the LLM (even simple `trades` commands). Add shortcut bypass for known commands to skip LLM. |
| 4 | **In-memory state only** | ft-agui threads live in memory. Need to add DB persistence for thread history. |
| 5 | **WebSocket complexity** | More failure modes than HTTP polling (reconnection, state recovery). HTMX has a simpler model. |
| 6 | **Double maintenance** | Two web UIs (`web_app.py` + `ag_ui.py`) sharing auth/business logic. Extract shared module. |
| 7 | **No file upload in ft-agui** | Can't upload CSVs or screenshots yet. Would need custom extension. |
| 8 | **Latency for simple commands** | `trades` or `price AAPL` currently return in <1s. Going through LLM adds 2-5s. Mitigate with shortcut detection. |
| 9 | **pydantic-ai lock-in** | Agent framework choice. But tools are plain functions, easy to decouple. |
| 10 | **CSS from scratch** | ft-agui provides base styles, but 3-pane layout needs custom CSS. More upfront work than Pico CSS. |

---

## Hybrid Approach: Shortcut Bypass

To avoid LLM overhead for known commands, intercept at the input layer:

```python
_SHORTCUT_MAP = {
    "trades": show_trades_direct,
    "runs": show_runs_direct,
    "agent:backtest": run_backtest_direct,
    "agent:paper": run_paper_direct,
    "price": get_price_direct,
    "news": get_news_direct,
    # ... all ~30 structured commands
}

def route_input(text: str):
    first_word = text.strip().split()[0].lower()
    if first_word in _SHORTCUT_MAP:
        return _SHORTCUT_MAP[first_word](text)  # Direct execution, no LLM
    else:
        return agent.run(text)  # Free-form → LLM
```

This preserves CLI-speed for power users while enabling natural language for new users.

---

## Implementation Phases

### Phase 1: Scaffold & Basic Chat (2-3 hours)
- Create `ag_ui.py` with FastHTML app on port 5003
- Install ft-agui, pydantic-ai
- Set up basic pydantic-ai Agent with system prompt
- Wire `setup_agui()` for center pane chat
- 3-pane CSS layout (left sidebar, center chat, right hidden)
- Left pane: static nav links only

### Phase 2: Tools & Command Mapping (3-4 hours)
- Create tool functions wrapping existing business logic:
  - `run_backtest()` → calls Orchestrator
  - `show_trades()` → calls agent_storage queries
  - `show_runs()` → calls agent_storage queries
  - `get_price()` → calls data_loader
  - `get_news()` → calls research_agent
  - `manage_portfolio()` → calls alpaca_agent
- Implement shortcut bypass for CLI commands
- Test all command paths

### Phase 3: Auth & Left Pane (2-3 hours)
- Port register/signin/profile routes from web_app.py
- Inline auth forms in left pane (not separate pages)
- Per-user session state (reuse UserSessionState pattern)
- Alpaca key management in sidebar
- Query counter display

### Phase 4: Right Pane — Thinking Trace (2-3 hours)
- Custom `__ft__()` patches for ReasoningEvents
- Tool call visualization (name, args, result)
- State snapshot rendering
- Auto-show on agent activity, manual toggle button
- Collapsible/resizable

### Phase 5: Right Pane — Artifact Canvas (2-3 hours)
- Plotly chart rendering in artifact tab
- Backtest summary tables
- Trade detail views
- Full-screen toggle for charts

### Phase 6: Polish & Mobile (2 hours)
- Responsive layout (collapse to single column on mobile)
- Dark/light theme toggle
- Loading states and error handling
- Suggestion chips for common commands
- Session TTL eviction

### Phase 7: Docker & Deploy (1 hour)
- `Dockerfile.agui`
- Update `docker-compose.yaml` with `agui` service on port 9003
- Add to Coolify deployment

---

## New Dependencies

```
ft-agui>=0.1.0
pydantic-ai>=1.34.0
ag-ui-core>=0.1.0
```

(pydantic>=2.12 already satisfied by existing deps)

---

## File Structure

```
ag_ui.py                    # Entry point (FastHTML app, port 5003)
agents/alpatrade_agent.py   # pydantic-ai Agent + tools
static/ag_ui.css            # 3-pane layout styles (or inline)
Dockerfile.agui             # Docker build
```

Reuses: `utils/auth.py`, `utils/agent_storage.py`, `utils/alpaca_agent.py`, `utils/research_agent.py`, `tui/command_processor.py`, `agents/orchestrator.py`

---

## Decision Points

1. **TailwindCSS vs custom CSS?** — Tailwind adds build step complexity. Recommend custom CSS (like current approach) unless you want utility classes.
2. **Keep HTMX for left pane forms?** — Yes, ft-agui already uses HTMX. Auth forms can use standard HTMX post without WebSocket.
3. **Thread persistence?** — Start with in-memory (like current web_app.py), add DB persistence later if needed.
4. **Which LLM for agent?** — Use XAI/Grok (already configured) for tool routing. Cheap and fast for structured commands.
