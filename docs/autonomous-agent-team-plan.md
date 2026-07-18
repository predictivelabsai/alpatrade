# Autonomous Trading Agent Team — Plan

Status: **Phases A, B & C shipped; D–E proposed** · Author: session 2026-07 · Grounds:
AlpaTrade current architecture + patterns mined from `dev/plai/plai-crm` + `kaljuvee-chat`.

## Decisions locked

| Question | Decision |
|---|---|
| Real-money autonomy | **Paper-only autonomous.** The deployed system NEVER places live orders. `scan → backtest → paper-trade → validate → reconcile → report`; live is a human action outside the system. |
| Pluggable frameworks | **LangGraph, DeepAgents, Pydantic AI, Nous Hermes** — behind one adapter. LLM stays swappable independently (`engine.config`). |
| Trigger | **Continuous worker loop** (self-feeding scanner → run queue), like plai-crm `autonomy_worker`. |
| Durability | **Postgres-only.** Reuse existing Postgres + file message bus + `agent_state.json`; add run/checkpoint tables. No Redis. |

## 1. Guiding principles

1. **The autonomy engine is ours; the reasoning is pluggable.** The durable pipeline
   (sequencing, state, checkpoints, policy gate, persistence) is plain Python we own and
   test deterministically. Only the *per-role reasoning agent* (how a node plans and calls
   tools) is delegated to a pluggable framework. This is exactly plai-crm's split:
   `autonomy_graph.py` is a hand-built `StateGraph`; each node is an agent.
2. **Two tiers.** A **reactive** chat agent (today's `agui_app`/`ph_chat`) for humans, and a
   **durable autonomy engine** (new) for unattended work. They share tools, DB, `engine.config`.
3. **Paper is a hard wall.** No code path in the autonomy engine can submit a live order.
   "Promote to live" is only ever a *report/recommendation* for a human — enforced by a pure
   policy function AND by never wiring a live-broker tool into the autonomy engine.
4. **A run counts only with a verified receipt.** Adopt plai-crm's honest-benchmark discipline:
   a phase is "success" only with a stored artifact (fill id, equity row, reconciliation match),
   never "the agent said so."
5. **Two LLM guardrails from plai-crm:** DATA tools return numbers verbatim; ADVISOR tools
   return facts the model may rank — but the model may cite *only* figures a tool returned.

## 2. Two-tier architecture

```
                        ┌────────────────────────── Reactive tier (exists) ───────────────────────┐
 Human ── web /app ────▶│ ph_chat → agui_app.agent_for_user → tools (engine/, CommandProcessor)    │
        ── voice /ws ───▶│ LangGraph ReAct, streamed, per-user model (engine.config)                │
        ── Hermes/TG ───▶│ (optional) Hermes runtime front-end → same agentsvc entrypoint           │
                        └──────────────────────────────────────────────────────────────────────────┘
                                                     │ shares tools + DB + engine.config
                        ┌────────────────────────── Autonomy tier (new) ──────────────────────────┐
 continuous worker ────▶│ scanner → run queue (Postgres) → PIPELINE StateGraph (our own):          │
   (AUTONOMY_ENABLED)   │   scout → backtest → validate → paper-trade → validate → reconcile → report│
                        │ each node = an Agent via the AgentRuntime adapter (LangGraph/DeepAgents/…) │
                        │ deterministic RiskPolicy gate between nodes · Postgres checkpoint per step │
                        │ events → file message bus (UI/SSE) + durable run log · email via Postmark  │
                        └──────────────────────────────────────────────────────────────────────────┘
```

## 3. The pluggable layer (`engine/agents/runtime/`)

Two independent axes — keep them separate:

- **LLM axis (done):** `engine.config.build_chat_model(settings)` already yields a provider-agnostic
  chat model (xAI/OpenAI/Anthropic). Frameworks consume this.
- **Framework axis (new):** an `AgentRuntime` adapter selected by `AGENT_FRAMEWORK`.

```
engine/agents/runtime/
  base.py        # RoleSpec + AgentRuntime Protocol
  registry.py    # AGENT_FRAMEWORK → adapter (extends engine.config AGENT_FRAMEWORKS)
  langgraph_rt.py    # create_react_agent / StateGraph            (reference; ship first)
  deepagents_rt.py   # deepagents harness: planning + subagents + HITL middleware
  pydantic_rt.py     # pydantic-ai Agent (type-safe tools, native async stream)
  hermes_rt.py       # Nous Hermes runtime: front-end/notifier shim, not a pipeline engine
```

```python
# base.py — the whole contract the pipeline depends on (as shipped)
@dataclass
class RoleSpec:
    name: str
    instructions: str = ""
    tools: list = ...          # StructuredTool-like/callables; adapters translate
    model: Any = None          # from engine.config.build_chat_model; None → default
    subagents: list = ...       # optional (DeepAgents/LangGraph supervisor)

class AgentRuntime(Protocol):
    name: str
    def build(self, spec: RoleSpec) -> Any: ...
    def run(self, agent, prompt: str, *, history=None) -> RunResult: ...
    def stream(self, agent, prompt: str, *, history=None) -> Iterator[str]: ...
    def supports_subagents(self) -> bool: ...
    # each adapter also exposes staticmethod available() → bool for registry fallback
```

Registry: `get_runtime(name=None)` resolves `AGENT_FRAMEWORK` (aliases normalised,
e.g. `pydantic-ai`→`pydantic_ai`, `nous`→`hermes`) and **falls back to LangGraph** when the
requested backend's lib isn't installed (`available()` is False). `available_runtimes()`
reports the matrix. The Hermes adapter additionally exposes `notify(text)` (opt-in via
`HERMES_WEBHOOK_URL`) for pushing autonomy digests to a Hermes/Telegram channel.

Adapter notes:
- **LangGraph** — wrap `create_react_agent` (per-node reasoning) and expose `StateGraph` for the
  pipeline. This is what AlpaTrade + plai-crm already do; lowest risk; **ship first**.
- **DeepAgents** — use its planning + isolated-context subagents + **HITL middleware** for the
  "promotion recommendation review" and shell/file tools; great for the Scout/Researcher role.
- **Pydantic AI** — type-safe tool signatures + native async streaming; good for nodes where we
  want validated structured output (e.g. RiskPolicy inputs, backtest configs).
- **Hermes** — a *deployed runtime* you talk to (Telegram/CLI). Model it as an optional **front-end
  + notifier** adapter over the existing `agentsvc`-style entrypoint, NOT as the pipeline engine.

Registry falls back to LangGraph if a framework lib isn't installed (mirrors
`engine.config.build_chat_model`'s anthropic fallback), so `AGENT_FRAMEWORK` never hard-breaks.

## 4. The agent team (roles)

Build on today's five agents; add a Scout and make the Risk gate a first-class deterministic function.

| Role | New/exists | Job | Autonomy |
|---|---|---|---|
| **Scout / Researcher** | new | Scan the universe (movers, news via Tavily, valuation) → propose candidate symbols+strategies → enqueue runs | auto |
| **Backtester** | exists (`agents/backtest_agent.py`) | Grid-search backtest candidates, store runs/trades/summaries | auto |
| **Validator** | exists (`agents/validate_agent.py`) | Cross-check trades vs market data, self-correct | auto |
| **RiskPolicy gate** | new (pure fn) | Deterministic admission + sizing: PDT, exposure, per-strategy eligibility, **paper-only enforcement**, kill-switch | auto (deterministic) |
| **Paper Trader** | exists (`agents/paper_trade_agent.py`) | Execute strategies on the Alpaca **paper** account, poll fills | auto |
| **Reconciler** | exists (`agents/reconcile_agent.py`) | DB positions vs broker holdings; flag drift | auto |
| **Reporter / Notifier** | exists (`agents/report_agent.py`) + new notifier | Daily digest, top strategies, **live-promotion candidates** → email (Postmark) / Hermes | auto |
| **Supervisor** | thin | The pipeline graph + RiskPolicy IS the supervisor (no LLM router needed), matching plai-crm | deterministic |

**Live promotion is a report, not an action.** When a paper strategy clears a bar (Sharpe/return/
drawdown over a window with a verified equity trail), the Reporter emits a *"promotion candidate"*
with the evidence. A human decides and acts in their own broker. The system has no live-order tool.

## 5. Continuous worker + Postgres-only durability

Mirror plai-crm's `autonomy_worker` shape, Postgres-only (no Redis):

```
engine/autonomy/
  worker.py     # long loop, gated by AUTONOMY_ENABLED; every AUTONOMY_SCAN_SECONDS:
                #   requeue_unfinished(); scout.enqueue_candidates(); drain runnable rows
  graph.py      # our StateGraph pipeline (nodes call agents via AgentRuntime)
  policy.py     # pure RiskPolicy.evaluate(candidate, state) → admit/size/reject (replayable)
  store.py      # Postgres: agent_runs, agent_run_steps (checkpoint), agent_events, promotions
  queue.py      # DB-backed queue: claim/heartbeat/ack via SELECT … FOR UPDATE SKIP LOCKED
```

- **State & checkpoints in Postgres** (new `sql/15_autonomy.sql`): `agent_runs` (id, kind, status,
  attempt, heartbeat, user_id, account_id), `agent_run_steps` (run_id, node, input/output JSON,
  status) = the checkpoint, `agent_events` (streamed log), `promotions` (paper→live candidates).
- **Queue = a Postgres table** drained with `FOR UPDATE SKIP LOCKED` (no Redis). On restart,
  `requeue_unfinished()` re-claims rows whose heartbeat is stale — a lost worker never loses a run.
- **Events** publish to the existing file message bus (`engine.agents.message_bus`) so the web UI/SSE
  and `agent:status`/`agent:logs` commands render live, exactly as today.
- **Reuse** `agents/shared/state.py` for the coarse mode/state; add the per-run rows for durability.

## 6. Human-in-the-loop & safety gates

- **Hard wall:** the autonomy engine imports only the paper broker; there is no live-order code path.
  A regression test asserts no live-trading symbol is reachable from `engine/autonomy/`.
- **Deterministic policy** (`policy.py`, pure, unit-tested on replayed bars): position/exposure/PDT
  limits, per-strategy eligibility, max concurrent runs, global **kill-switch** (`AUTONOMY_ENABLED`
  + a DB flag). "The model extracts facts; the policy decides" (plai-crm principle).
- **Promotion review (optional DeepAgents/LangGraph interrupt):** if you later want gated live, it
  slots in as a durable `interrupt()` + approver — but that's a *future* phase, off by default.
- Reuse the session's credential discipline: BYOK keys stay Fernet-encrypted; no secrets in logs.

## 7. Evals & honest benchmarks

- Extend the DeepEval harness (`evals/run_evals.py`) with **autonomy cases**: scout proposes valid
  candidates; policy admits/rejects correctly on fixtures; a full pipeline run produces a stored
  equity trail.
- Add pure-function tests for `RiskPolicy` on **replayed historical bars** (deterministic), plus a
  `TestAutonomy` class in the regression suite (route table, queue claim/heartbeat, no-live-path).
- Adopt an **evidence benchmark doc** (`docs/autonomy_benchmark_<date>.md`) that records, per run,
  where it stopped and the verified artifact — and *retracts* any false "ready", like plai-crm's.

## 8. Config & deployment

- `AGENT_FRAMEWORK` (already an `engine.config` field/stub) selects the runtime adapter; default
  `langgraph`. `engine.config.MODEL_*` continues to pick the LLM. Both per-user overridable via the
  Settings page — a user could run their autonomy on `deepagents` + `claude-sonnet-5`.
- Deploy: add an **`autonomy` service** to `docker-compose.yaml` (own container running
  `python -m engine.autonomy.worker`), `AUTONOMY_ENABLED` off in prod until validated — mirrors
  plai-crm's local-only `autonomy` profile. No new infra (Postgres already there).

## 9. Phased rollout

- **Phase A — Adapter layer. ✅ SHIPPED.** `engine/agents/runtime/` with `base.py` (RoleSpec +
  AgentRuntime Protocol + `default_model`), `registry.py` (`AGENT_FRAMEWORK` select + alias + fallback),
  and four adapters: `langgraph_rt` (reference; build/run/stream verified end-to-end), `deepagents_rt`
  (subagents; falls back if `deepagents` absent), `pydantic_rt` (maps provider→`pydantic_ai` OpenAI model),
  `hermes_rt` (LangGraph-delegating + `notify()`). Covered by `TestAgentRuntime` (6 tests) → regression
  suite now **80/80**. *Remaining Phase-A polish: port `agui_app`/`ph_chat` to build through the adapter
  (currently they still call `create_react_agent` directly — no behavior change when they switch).*
- **Phase B — Durable run engine. ✅ SHIPPED.** `sql/15_autonomy.sql` (runs/steps/events/promotions),
  `engine/autonomy/`: `policy.py` (pure paper-only RiskPolicy), `store.py` (CRUD + checkpoints),
  `queue.py` (`FOR UPDATE SKIP LOCKED` claim + heartbeat + `requeue_unfinished`), `graph.py` (resumable
  checkpointed `Pipeline` wrapping the Orchestrator phases + `policy_gate`), `worker.py` (continuous loop,
  `AUTONOMY_ENABLED`-gated). Covered by `TestAutonomyPolicy`/`Engine`/`NoLivePath` (10 tests) →
  regression **90/90**. *Remaining: wire `default_pipeline` to a real end-to-end run + a `autonomy`
  compose service (both Phase C-adjacent).*
- **Phase C — Scout + promotion + notifier + agent evals. ✅ SHIPPED.** `scout.py` (portfolio state +
  deterministic candidate scan + `enqueue_run`), `promote.py` (pure `should_promote` + recorder),
  `notify.py` (Postmark + Hermes digest), wired into `default_pipeline` (scout→…→promote); worker
  self-feeds via the scout when idle. `autonomy` **compose service** (opt-in profile, `AUTONOMY_ENABLED`
  off in prod). **Agent-eval harness** `evals/run_agent_evals.py` + `evals/autonomy_cases.json`
  (risk_policy/promotion/scout dimensions, 17/17), pure `TestPromotion`, and a CRM-style evidence
  benchmark `docs/autonomy_benchmark_2026-07-18.md` (stage matrix 9/12, honest first-blocker + retraction
  section). *Remaining before "fully live team": run `default_pipeline` end-to-end via the worker and
  thread the gate's `sized_notional` into the paper order (Phase D).*
- **Phase D — Framework parity + front-ends.** Prove the pipeline runs identically under LangGraph
  vs DeepAgents; optional Hermes/Telegram notifier front-end; evidence benchmark.
- **Phase E (optional, later).** Gated live promotion via durable interrupt + approver — only if you
  decide to move past paper-only.

## 10. Reuse map

- **Reuse as-is:** `engine.config` (LLM + framework selection), `engine.brokers.alpaca` (paper),
  `engine.feeds.*`, `engine.db.pool`, `agents/{backtest,validate,paper_trade,reconcile,report}_agent.py`,
  `agents/shared/{message_bus,state}.py`, `evals/`, `utils/email_util.py` (Postmark notify).
- **New:** `engine/agents/runtime/*` (adapters), `engine/autonomy/*` (worker/graph/policy/store/queue),
  `sql/15_autonomy.sql`, autonomy evals + `TestAutonomy`.
- **From plai-crm, imitate the pattern (not the code):** deterministic policy separate from LLM
  (`autonomy_policy.py`), Postgres-state + DB-queue with `requeue_unfinished`, run state machine +
  dual event sink (SSE + durable log), self-feeding scan, config-as-data venue/capability registry,
  and the retract-false-positives evidence benchmark.

## Open follow-ups (not blockers)
- Add `langchain-anthropic` + `ANTHROPIC_API_KEY` so `claude-sonnet-5` is a real backend for any adapter.
- Swap Tavily news for grok native web search in the Scout (fewer keys).
