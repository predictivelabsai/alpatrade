# AlpaTrade Mobile API

Contract for the **alpatrade-mobile** (Flutter) client. Mirrors the kanvas-mobile
pattern: streaming chat over SSE + typed REST.

- **Base URL:** `https://api.alpatrade.chat`
- **Developers:** `https://alpatrade.chat/developers`
- **Swagger / ReDoc:** `https://api.alpatrade.chat/docs` · `https://api.alpatrade.chat/redoc`
- **Machine-readable spec:** [`docs/swagger.json`](./swagger.json) (OpenAPI 3.1, generated from the FastAPI app) — import it into Postman / codegen.
- **Auth:** JWT bearer. `Authorization: Bearer <token>` on protected calls.
- **Trading is paper-only** (simulated) and uses the authenticated user's linked Alpaca paper account.

---

## Auth

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/auth/register` | `{email, password, display_name?}` | `{token, user_id, email}` |
| POST | `/auth/login` | `{email, password}` | `{token, user_id, email}` |

Store `token` and send it as `Authorization: Bearer <token>` on later calls.
Auth is **optional** for the compatibility `/v2/chat` endpoint. Anonymous chat is
restricted to public market/research tools and never receives account or action tools.
The canonical `/v2/deepagents` endpoint requires a JWT or a service key plus `X-User-Id`.

---

## Canonical DeepAgent — `POST /v2/deepagents`

This is the primary API for new clients. It always uses DeepAgents, appends new
messages to a durable caller-owned thread, and supports JSON or SSE from the same
request contract.

```json
{
  "messages": [
    {
      "id": "68d8968b-4ec1-44c3-9d0d-a3d519c8086b",
      "role": "user",
      "content": "Backtest buy the dip on AAPL and MSFT"
    }
  ],
  "thread_id": "optional-thread-uuid",
  "account_id": "optional-owned-account-uuid",
  "stream": false
}
```

- Message IDs are required UUIDs and are stable idempotency keys.
- `messages` contains only new messages to append, not the full transcript.
- Roles may be `user` or `assistant`; the final message must be `user`.
- Each call accepts at most 20 messages, 20,000 characters per message, and
  50,000 characters total.
- Omit `thread_id` to create one. A supplied thread/account must belong to the caller.
- A completed or failed duplicate is replayed with `cached: true`. A running
  duplicate or concurrent request on the thread returns `409 response_in_progress`.
  Reusing an ID with changed message content or account scope returns
  `409 message_id_conflict`.

JSON mode returns the assistant message plus sanitized tool/subagent traces:

```json
{
  "id": "response-uuid",
  "thread_id": "thread-uuid",
  "status": "completed",
  "framework": "deepagents",
  "model": {"provider": "xai", "name": "grok-4-1-fast-reasoning"},
  "messages": [{"id": "message-uuid", "role": "assistant", "content": "..."}],
  "tools": [{"call_id": "...", "name": "queue_backtest", "status": "completed"}],
  "subagents": [{"call_id": "...", "name": "strategy-lab", "status": "completed"}],
  "cached": false
}
```

Set `stream: true` for named SSE events: `session`, `agent_route`,
`message_start`, `token`, `tool_start`, `tool_end`, `subagent_start`,
`subagent_end`, `message_end`, `error`, periodic `ping`, and `done`. Tool and
subagent events contain IDs, names, status, and timestamps only; inputs,
results, credentials, and raw exceptions are never emitted.

Mutating tools require an explicit imperative request. They queue long backtest,
paper, full-cycle, and autonomy work and return a job ID immediately. Paper
orders use the caller's linked paper account. Hypothetical or advisory wording
cannot trigger an action.

The authenticated `trading-advisor` specialist can read the same persisted daily
reports used by the dashboard and email. `queue_advisor_backtest(report_id,
recommendation_id)` loads its stored grid server-side, and
`queue_paper_from_backtest(run_id, duration_seconds)` accepts only an owned,
completed, validated backtest. Both require a separate explicit imperative message.

---

## Compatibility chat (streaming) — `POST /v2/chat`

This older SSE shape remains for existing clients and now uses the shared
DeepAgents service. Authenticated callers receive tenant-scoped tools; anonymous
callers receive public market/research tools only.

- **Content-Type:** `application/json` (or `application/x-www-form-urlencoded`)
- **Body:** `msg` (string, required) · `thread_id` (string, optional). Authenticated
  calls use it for durable continuity; anonymous calls use it only as a correlation label.
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
  -d '{"msg":"what is the latest MSFT price?","thread_id":"m1"}'
```
```
event: session
data: {"sid": "m1"}

event: agent_route
data: {"slug": "ai", "agent": "AlpaTrade AI"}

event: tool_start
data: {"name": "get_market_price"}

event: token
data: {"text": "**MSFT** is trading at ..."}
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

### Placing trades from chat

Trading is paper-only. An authenticated caller's explicit imperative request may
execute a paper action; advisory or hypothetical wording cannot. Anonymous callers
never receive trading or portfolio tools. New integrations should use
`POST /v2/deepagents` for durable idempotency and full action/subagent traces.

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
| GET | `/v2/advisor/reports?account_id=&limit=` | Daily paper-advisor history. |
| GET | `/v2/advisor/reports/{report_id}` | One owned daily paper-advisor report. |
| GET | `/v2/top` | Top strategies ranking. |
| GET | `/v2/pnl/{run_id}` | P&L breakdown for a run. |
| GET | `/v2/status` | Background agent status. |
| GET | `/v2/logs` | Recent agent logs. |
| GET | `/health` | Liveness. |

## Trading (REST) — `POST /v2/order`

Place a **paper** (simulated) order directly, without going through chat, on the
authenticated user's linked paper account. No real money.

- **Body (JSON):**
  ```json
  { "symbol": "AAPL", "qty": 10, "side": "buy",
    "order_type": "limit", "limit_price": 180.0, "time_in_force": "day" }
  ```
  - `side`: `buy` | `sell` · `order_type`: `market` | `limit` (limit needs `limit_price`) · `time_in_force`: `day` | `gtc`
- **Auth:** required bearer.
- **Returns:**
  ```json
  { "ok": true, "order_id": "…", "symbol": "AAPL", "qty": 10, "side": "buy",
    "order_type": "limit", "limit_price": 180.0, "status": "PENDING_NEW", "paper": true }
  ```
  On error: `{ "ok": false, "error": "limit_price is required for a limit order" }`.

> Chat-driven ordering (`/v2/chat`, e.g. *"buy 10 AAPL with a $180 limit"*) does the same thing; use `/v2/order` when the client places orders from a form/button.

## Actions (REST)

| Method | Path | Purpose |
|---|---|---|
| POST | `/v2/backtest` | Start a backtest. |
| POST | `/v2/paper` | Start paper trading. |
| POST | `/v2/validate` | Validate a run. |
| POST | `/v2/reconcile` | Reconcile DB vs broker. |
| POST | `/v2/full` | Full cycle (backtest → validate → paper → validate → reconcile → report). |
| POST | `/v2/stop` | Stop a running agent. |

Market helpers: `GET /news`, `GET /price`, `GET /movers`, `GET /profile`.

## External agent APIs

`GET /v2/agents` is the public machine-readable catalog. The canonical typed agent
invocations are:

| Method | Path | Agent |
|---|---|---|
| POST | `/v2/deepagents` | **Canonical** authenticated DeepAgent; durable JSON or SSE. |
| POST | `/v2/agents/chat/invoke` | Compatibility non-streaming JSON chat response. |
| POST | `/v2/chat` | Compatibility SSE; anonymous public research only. |
| POST | `/v2/agents/premarket/invoke` | Read-only premarket scan. |
| POST | `/v2/agents/alpha-growth/invoke` | Growth research methodology. |
| POST | `/v2/agents/alpha-value/invoke` | Value research methodology. |
| POST | `/v2/agents/alpha-compare/invoke` | Combined Growth + Value report. |
| POST | `/v2/agents/autonomy-scout/invoke` | Queue the paper-only durable autonomy pipeline. |

The Backtest, Validation, Paper Trade, Reconciliation, Report, and Orchestrator agents
use the typed action/data endpoints above rather than duplicate wrapper routes.

Trusted services authenticate with `X-API-Key`. Set `API_SERVICE_KEY` or a comma-separated
`API_SERVICE_KEYS` value on the API deployment, then include `X-User-Id` for endpoints that
read or mutate one user's data. User-facing clients should continue to use JWT bearer auth.

---

## Notes

- **Regenerate `swagger.json`** whenever the API changes:
  `python -c "import json,api_app; open('docs/swagger.json','w').write(json.dumps(api_app.app.openapi(),indent=2,default=str))"`
  (or fetch the live spec at `https://api.alpatrade.chat/openapi.json`).
- SSE needs a client that streams the response body (Flutter: `http` `Client().send`, not `Dio` for the stream). Disable response buffering (the server already sets `X-Accel-Buffering: no`).
- Paper trading is simulated; results differ from live. This is not investment advice.
