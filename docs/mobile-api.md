# AlpaTrade Mobile API

Contract for the **alpatrade-mobile** (Flutter) client. Mirrors the kanvas-mobile
pattern: streaming chat over SSE + typed REST.

- **Base URL:** `https://api.alpatrade.chat`
- **Machine-readable spec:** [`docs/swagger.json`](./swagger.json) (OpenAPI 3.1, generated from the FastAPI app) — import it into Postman / codegen.
- **Auth:** JWT bearer. `Authorization: Bearer <token>` on protected calls.
- **Trading is paper-only** (simulated). The default account is the primary paper account (number ending **…8CR**).

---

## Auth

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/auth/register` | `{email, password, display_name?}` | `{access_token, token_type, user}` |
| POST | `/auth/login` | `{email, password}` | `{access_token, token_type, user}` |

Store `access_token` and send it as `Authorization: Bearer <token>` on later calls.
Auth is **optional** for `/v2/chat` (anonymous uses the shared demo account); required for per-user data.

---

## Chat (streaming) — `POST /v2/chat`

The heart of the app. Same router as the web chat: plain-English prompts are routed to
tools/commands (positions, account, P&L, news, quotes, backtests, reports, **paper orders**).

- **Content-Type:** `application/json` (or `application/x-www-form-urlencoded`)
- **Body:** `msg` (string, required) · `thread_id` (string, optional — keeps conversation history)
- **Auth:** optional bearer
- **Response:** `text/event-stream` (SSE). Keep the connection open and read events until `done`.

### SSE events

Each event is `event: <type>\n` + `data: <json>\n\n`.

| `event` | `data` | Meaning |
|---|---|---|
| `session` | `{sid}` | Stream opened; echoes the thread id. |
| `agent_route` | `{slug, agent}` | Which path handled it (`command` or `ai`). Show as a small label. |
| `token` | `{text}` | A chunk of the assistant reply. **Concatenate `text` across all `token` events** → the full markdown answer. |
| `tool_start` | `{name}` | A tool/data lookup began (e.g. `get_alpaca_positions`). Optional "thinking…" hint. |
| `tool_end` | `{name}` | That tool finished. |
| `error` | `{message}` | Something failed; stream will still send `done`. |
| `done` | `{}` | Stream complete. Close the reader. |

### Example (curl)

```bash
curl -N -X POST https://api.alpatrade.chat/v2/chat \
  -H "Content-Type: application/json" \
  -d '{"msg":"how large is my MSFT position?","thread_id":"m1"}'
```
```
event: session
data: {"sid": "m1"}

event: agent_route
data: {"slug": "ai", "agent": "AlpaTrade AI"}

event: tool_start
data: {"name": "get_alpaca_positions"}

event: token
data: {"text": "**MSFT position: 2 shares**"}
...
event: done
data: {}
```

### Example (Dart / http SSE)

```dart
final req = http.Request('POST', Uri.parse('$base/v2/chat'))
  ..headers['Content-Type'] = 'application/json'
  ..headers['Authorization'] = 'Bearer $token'          // optional
  ..body = jsonEncode({'msg': prompt, 'thread_id': threadId});
final res = await http.Client().send(req);
final buf = StringBuffer();
await for (final line in res.stream.transform(utf8.decoder).transform(const LineSplitter())) {
  if (line.startsWith('event:')) currentEvent = line.substring(6).trim();
  if (line.startsWith('data:')) {
    final data = jsonDecode(line.substring(5).trim());
    if (currentEvent == 'token') buf.write(data['text']);       // accumulate reply
    if (currentEvent == 'done')  break;
  }
}
// buf.toString() is the full markdown reply — render with a markdown widget.
```

### Placing trades from chat (2-step confirm)

Trading is **paper**. When the user asks to buy/sell (e.g. *"buy 1 share of TSLA"*), the
agent **first replies with a preview** ("BUY 1 TSLA @ ~$X — reply confirm to place, or
correct it") and **does not execute**. Only after the user sends a confirming message
(*"yes"* / *"confirm"*) in the same `thread_id` does it place the order. No special client
handling is required — just keep the same `thread_id`.

> There is also a legacy `GET /chat?question=…&thread_id=…` SSE endpoint (old agents). Prefer `POST /v2/chat`.

---

## Data (REST)

All return typed JSON (see `swagger.json` for schemas). Pass the bearer token to scope to the user.

| Method | Path | Purpose |
|---|---|---|
| GET | `/v2/positions` | Open Alpaca paper positions (symbol, qty, P&L). |
| GET | `/v2/trades` | Recent trades (`?trade_type=paper|backtest`). |
| GET | `/v2/runs` | Backtest / paper runs. |
| GET | `/v2/report` | Strategy summaries. |
| GET | `/v2/report/{run_id}` | One run's detail. |
| GET | `/v2/top` | Top strategies ranking. |
| GET | `/v2/pnl/{run_id}` | P&L breakdown for a run. |
| GET | `/v2/status` | Background agent status. |
| GET | `/v2/logs` | Recent agent logs. |
| GET | `/health` | Liveness. |

## Actions (REST)

| Method | Path | Purpose |
|---|---|---|
| POST | `/v2/backtest` | Start a backtest. |
| POST | `/v2/paper` | Start paper trading. |
| POST | `/v2/validate` | Validate a run. |
| POST | `/v2/reconcile` | Reconcile DB vs broker. |
| POST | `/v2/full` | Full cycle (backtest → validate → paper). |
| POST | `/v2/stop` | Stop a running agent. |

Market helpers: `GET /news`, `GET /price`, `GET /movers`, `GET /profile`.

---

## Notes

- **Regenerate `swagger.json`** whenever the API changes:
  `python -c "import json,api_app; open('docs/swagger.json','w').write(json.dumps(api_app.app.openapi(),indent=2,default=str))"`
  (or fetch the live spec at `https://api.alpatrade.chat/openapi.json`).
- SSE needs a client that streams the response body (Flutter: `http` `Client().send`, not `Dio` for the stream). Disable response buffering (the server already sets `X-Accel-Buffering: no`).
- Paper trading is simulated; results differ from live. This is not investment advice.
