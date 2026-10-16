# Streaming Chat Console

Real-time streaming trace for free-form AI chat queries in the FastHTML web UI and the FastAPI REST server.

## Problem

Free-form chat (e.g. "give me 5 top cyber security stocks with large losses") previously blocked until the full agent response was ready, showing only "Running..." for 10-30 seconds while the agent called multiple tools sequentially. No feedback was visible during that time.

## Solution

A streaming console (matching the existing backtest log console pattern) that shows the reasoning trace in real-time: tool calls, tool results, and the final rendered markdown answer.

### Architecture

```
User types free-form query
  → POST /cmd — not a structured command
  → _start_chat_stream() — returns chat-console div polling /chat-stream
  → Background asyncio.Task: async_stream_response() yields events
  → Browser polls every 500ms via HTMX:
      Poll 1: ">> Calling get_stock_price..."
      Poll 2: ">> Calling get_stock_price...\n<< get_stock_price returned data"
      Poll N: HTTP 286 → trace + final markdown rendered
```

**Why HTMX polling (not SSE)?** The codebase already has a battle-tested HTMX polling pattern with HTTP 286 termination, race condition handling, and auto-scroll. Reusing it is simpler and consistent.

## Files Modified

| File | What changed |
|------|-------------|
| `utils/research_agent.py` | Added `_get_streaming_model()`, `_get_streaming_graph()`, `async_stream_response()` |
| `utils/alpaca_agent.py` | Same streaming pattern as research agent |
| `web_app.py` | Chat state, `_start_chat_stream()`, `/chat-stream` polling endpoint, auto-scroll |
| `api_app.py` | `GET /chat` SSE endpoint for programmatic consumers |

## Agent Streaming (`async_stream_response`)

Both `research_agent.py` and `alpaca_agent.py` expose an `async_stream_response()` generator that uses LangGraph's `astream_events(version="v2")`. It yields structured event dicts:

```python
async def async_stream_response(question: str, thread_id: str):
    graph = _get_streaming_graph()
    input_msg = {"messages": [{"role": "user", "content": question}]}
    config = {"configurable": {"thread_id": thread_id}}

    async for event in graph.astream_events(input_msg, config=config, version="v2"):
        # Yields: tool_call, tool_result, token, done
```

### Event Types

| Event | Fields | Description |
|-------|--------|-------------|
| `tool_call` | `tool`, `args` | Agent is calling a tool |
| `tool_result` | `tool`, `result` (truncated to 500 chars) | Tool returned data |
| `token` | `content` | Streaming token from the LLM |
| `done` | `content` (full response) | Agent finished |
| `error` | `content` | Exception occurred |

### Separate Streaming Graph

The streaming model uses `streaming=True` on `ChatOpenAI` and a dedicated LangGraph compiled graph (`_streaming_graph`). This keeps it fully isolated from the sync `get_response()` path used by the Rich CLI, avoiding any interference with existing behavior.

## FastHTML Web UI (`web_app.py`)

### Routing

Free-form input is detected by `_is_structured_command()`, which checks against `_STRUCTURED_PREFIXES` (all known command prefixes like `news`, `agent:backtest`, `trades`, etc.). Anything that doesn't match is routed to `_start_chat_stream()`.

Broker vs. research agent routing uses `_is_broker_query()` (keyword set: buy, sell, order, positions, portfolio, account, etc.).

### State

```python
cli._chat_events   # collections.deque(maxlen=200) — event buffer
cli._chat_task      # asyncio.Task for current chat
cli._chat_done      # completion flag
cli._chat_final     # final markdown content
cli._chat_286_html  # cached 286 response for HTMX race
```

### `_start_chat_stream(command)`

1. Cancels any existing chat task
2. Clears state
3. Creates an `asyncio.Task` that iterates `async_stream_response()` and appends events to `cli._chat_events`
4. Returns an HTMX div polling `/chat-stream` every 500ms

### `GET /chat-stream`

- Reads events from `cli._chat_events`
- Renders tool calls as `>> Calling {tool}...` / `<< {tool} returned data`
- While running: returns `<pre>` with trace text
- When done: returns HTTP 286 with trace + final markdown, stopping HTMX polling
- Handles HTMX race condition (concurrent poll after 286) with cached response replay

### Auto-scroll

The existing `htmx:afterSwap` JS handler scrolls both `#log-console` (backtest) and `#chat-console` (chat).

## FastAPI SSE Endpoint (`api_app.py`)

```
GET /chat?question=what+is+AAPL+price&thread_id=my_session
```

Returns Server-Sent Events (SSE) via `StreamingResponse`:

```
data: {"type": "tool_call", "tool": "get_stock_price", "args": {"ticker": "AAPL"}}

data: {"type": "tool_result", "tool": "get_stock_price", "result": "..."}

data: {"type": "token", "content": "The"}

data: {"type": "token", "content": " current"}

data: {"type": "done", "content": "The current price of AAPL is..."}
```

### Usage

```bash
curl -N "http://localhost:5001/chat?question=what+is+AAPL+price"
```

```python
import httpx, json

with httpx.stream("GET", "http://localhost:5001/chat", params={"question": "NVDA price"}) as r:
    for line in r.iter_lines():
        if line.startswith("data: "):
            event = json.loads(line[6:])
            if event["type"] == "tool_call":
                print(f"Calling {event['tool']}...")
            elif event["type"] == "done":
                print(event["content"])
```

## Testing

1. **Web UI**: `python web_app.py` → type "give me 5 top cyber security stocks with large losses" → see streaming trace then final answer
2. **Structured commands still work**: `news:TSLA`, `agent:backtest lookback:1m`, `trades`, `help`
3. **API SSE**: `curl -N "http://localhost:5001/chat?question=what+is+AAPL+price"` → SSE stream
4. **Auto-scroll**: trace console scrolls during rendering
5. **Rate limiting**: anonymous free query limit still applies to chat queries
