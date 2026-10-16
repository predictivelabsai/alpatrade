# AlpaTrade Mobile API

Contract for the **alpatrade-mobile** (Flutter) client. Mirrors the kanvas-mobile
pattern: streaming chat over SSE + typed REST.

- **Base URL:** `https://api.alpatrade.chat`
- **Machine-readable spec:** [`docs/swagger.json`](./swagger.json) (OpenAPI 3.1, generated from the FastAPI app) — import it into Postman / codegen.
- **Auth:** JWT bearer. Protected account data and paper orders require `Authorization: Bearer <token>`.
- **Trading is paper-only** (simulated) and uses the authenticated user's linked paper account.

---

## Auth

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/auth/register` | `{email, password, display_name?}` | `{token, user_id, email}` |
| POST | `/auth/login` | `{email, password}` | `{token, user_id, email}` |

The app stores `token` in local preferences and sends it as
`Authorization: Bearer <token>`. Chat and market-news helpers remain public;
positions, trades, runs, reports, status, agent actions, and orders require a
signed-in user. A `401` clears the expired local session and prompts sign-in.

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
  ..headers['Authorization'] = 'Bearer $token'          // when signed in
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

All return typed JSON (see `swagger.json` for schemas) and require the bearer token.

| Method | Path | Purpose |
|---|---|---|
| GET | `/v2/positions` | Live open Alpaca paper positions by default; supports `?run_id=` and `?status=` for ledger queries. |
| GET | `/v2/trades` | Recent trades (`?type=paper|backtest`). |
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

## Research (mobile 1.1.0 / API 0.36.0)

The new screens are under **More**. Deploy the updated sister-repo API before
using them against the production base URL. Local builds can target a local API
using `--dart-define=API_BASE_URL=http://127.0.0.1:5055` and `adb reverse tcp:5055 tcp:5055`.

| Method | Path | Authentication / result |
|---|---|---|
| GET | `/v2/leaderboard?q=&kind=live|backtest&limit=100` | Public; `strategies`, `total`; global ranks retained when filtering |
| GET | `/v2/strategies` | Bearer; your strategy library |
| GET | `/v2/strategies/{id}` | Public or owner-only; private entries return 404 to others |
| POST / PUT | `/v2/strategies[/{id}]` | Bearer; name, description, skill_md, author_name, is_public |
| DELETE | `/v2/strategies/{id}` | Owner only |
| POST | `/v2/strategies/{id}/clone` | Bearer; returns id and created; reuses the existing clone |
| GET | `/v2/hedge-funds` | Bearer; 13F screener rows, period and available periods |
| GET | `/v2/hedge-funds/performance?method=quarter_end|follow_filing` | Bearer; funds, labels, benchmark, computed_at |
| GET | `/v2/hedge-funds/activists?ticker=` | Bearer; filings |
| GET | `/v2/ipos` | Bearer; listed IPOs |
| GET | `/v2/ipos/pipeline` | Bearer; upcoming/private pipeline |
| GET | `/v2/advisor/reports` | Bearer; existing tenant-scoped daily advisor reports |

Screener filters: `q`, `period`, `min_aum`, `pos`, `rtype`, `holds`, `perf_only`,
`sort`, `limit`. Leaderboard metrics are percentage points; 13F return values are
fractions (0.125 renders as 12.5%). Missing metrics remain unavailable, never zero.
Cloning does not place orders or start a backtest. API strategy CRUD is available
for other clients; mobile currently browses and clones strategies.

Strategy backtests: `POST /v2/strategies/{id}/backtest` returns HTTP 202 with
`job_id`; poll `GET /v2/strategy-backtests/{job_id}` for `state`, `message`,
`markdown`, and `strategy_id`. Both routes require the owner. Jobs currently use
the existing in-process clone-backtest worker; restarting the API loses job
status, while completed strategy metrics remain in the database.

Android integration smoke test:
`flutter test integration_test/research_smoke_test.dart -d emulator-5554 --dart-define-from-file=/path/to/local-test-defines.json`.
The private define file supplies `API_BASE_URL` and `LOCAL_TEST_TOKEN` for a
short-lived synthetic identity. The test reads research only; no orders, strategy
writes or backtests are executed. HTTP is enabled only in the debug manifest.
