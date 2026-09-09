# Agent tracing & LLM cost visibility

Two complementary layers answer "where did the tokens go":

1. **Ledger (built-in, PR #55)** — every chat-model call is written to
   `alpatrade.llm_usage_logging` (`engine/ai/llm_usage.py`), with tokens,
   estimated cost, funding source (platform vs user BYOK), and
   `agent_framework`/`provider`/`model_name`. Hermes stream usage arrives via
   `stream_options: {"include_usage": true}` on the gateway call
   (`engine/agents/runtime/hermes_rt.py`).
2. **LangSmith (opt-in)** — full trace/span views (tools, retries, internal
   reasoning steps) at smith.langchain.com, enabled purely by environment
   variables; no code changes and zero cost when off.

## Enabling LangSmith

Set these in Coolify (never in `.env` committed to the repo):

| Variable | Value |
|---|---|
| `LANGSMITH_TRACING` | `true` |
| `LANGSMITH_API_KEY` | key from the Predictive Labs org (lsm-… token) |
| `LANGSMITH_PROJECT` | `alpatrade` |
| `LANGSMITH_ENDPOINT` | org region endpoint — **set explicitly if the org is not in the US region** (e.g. `https://eu.api.smith.langchain.com`); a wrong endpoint fails auth with 401 |

Then redeploy. The LangChain/LangGraph SDKs pick the variables up automatically
for every `astream_events` call, including the chat path
(`engine/web/ph_chat.py`, which passes `user_id`/`thread_id`/`framework` as
trace metadata so runs can be grouped per user thread in the LangSmith UI).

Scope in `docker-compose.yaml`: `api`, `agui` (web), `autonomy`. The Hermes
sidecar container deliberately does **not** get these variables — its internal
agent loop is a third-party image; seeing its traffic in LangSmith would need
OTel support inside that image (not verified).

Verification after deploy: send one chat message, then check
smith.langchain.com → project `alpatrade` for a new run with metadata
`thread_id`.

## Cost incident workflow (e.g. one-day xAI spend spike)

1. **Ledger first** — attribute the spend:
   ```sql
   SELECT agent_framework, model_name, SUM(estimated_cost_usd), SUM(total_tokens)
   FROM alpatrade.llm_usage_logging
   WHERE created_at::date = '<incident-date>'
   GROUP BY 1, 2;
   ```
   `funding_source = 'platform'` rows are paid by the platform key; BYOK rows
   are the user's own.
2. **LangSmith** — filter the same day for the slowest/most-iterated runs
   (`error` or high latency), open the trace, and look at tool-call loops.
3. **Hermes blind spot** — Hermes (`nousresearch/hermes-agent` pinned image)
   loops internally (`HERMES_MAX_ITERATIONS`, default 20) between the stream
   start and the first visible token; the ledger only sees the final usage
   report, not each internal iteration. Bounded by design; LangSmith will not
   see inside it either unless the image gains OTel export.
4. **Budget guard** — `engine.ai.llm_usage.enforce_daily_budget` (wired into
   the DeepAgents runtime) caps platform-funded spend per day and flags
   `budget_warning` in the ledger `metadata`.