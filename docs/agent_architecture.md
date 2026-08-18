# Agent Architecture

This document describes the implemented AlpaTrade agent surface. The canonical
machine-readable catalog is `engine/agents/catalog.py` and is exposed by
`GET /v2/agents`. `api_app.py` owns the typed REST contract; `agui_app.py` owns
the shared conversational harness. All trading performed by agents is paper-only.

## Architecture at a Glance

```mermaid
flowchart LR
    Client[Web, mobile, or API client]
    Auth[JWT or service authentication]
    API[FastAPI v2 API]
    Chat[DeepAgent chat harness]
    CP[CommandProcessor]
    Research[Research agents]
    Orch[Five-Agent Orchestrator]
    Auto[Durable autonomy worker]
    Engine[Canonical engine modules]
    DB[(PostgreSQL)]
    Alpaca[Alpaca paper account]
    Bus[JSON message bus]

    Client --> Auth --> API
    API --> Chat
    API --> Research
    API --> Orch
    API --> Auto
    Chat -->|recognized command| CP
    Chat -->|free-form request| Engine
    CP --> Orch
    Research --> Engine
    Orch --> Engine
    Auto --> Orch
    Orch <--> Bus
    Engine <--> DB
    Engine <--> Alpaca
```

## Public Agent Catalog

| Agent | Endpoint | Execution | Safety | Primary responsibility |
|---|---|---|---|---|
| DeepAgent Assistant | `POST /v2/agents/chat/invoke` | synchronous | paper-only | JSON chat response with route and tools used |
| DeepAgent Assistant SSE | `POST /v2/chat` | streaming | paper-only | Tokens, route events, tool events, and thread continuity |
| Premarket Agent | `POST /v2/agents/premarket/invoke` | synchronous | read-only | Movers, catalysts, rankings, and saved scans |
| Alpha Growth Agent | `POST /v2/agents/alpha-growth/invoke` | synchronous | read-only | Evidence-backed growth research |
| Alpha Value Agent | `POST /v2/agents/alpha-value/invoke` | synchronous | read-only | Valuation and margin-of-safety research |
| Alpha Comparison Agent | `POST /v2/agents/alpha-compare/invoke` | synchronous | read-only | Growth and value views over shared evidence |
| Backtest Agent | `POST /v2/backtest` | synchronous | read-only | Parameter sweeps and best-configuration selection |
| Validation Agent | `POST /v2/validate` | synchronous | read-only | Trade-price checks, anomalies, and corrections |
| Report Agent | `GET /v2/report` | synchronous | read-only | Run summaries, P&L, and strategy rankings |
| Paper Trade Agent | `POST /v2/paper` | asynchronous | paper-only | Durable background paper execution |
| Reconciliation Agent | `POST /v2/reconcile` | synchronous | paper-only | Database-versus-broker position checks |
| Five-Agent Orchestrator | `POST /v2/full` | synchronous | orchestration | End-to-end backtest-to-paper workflow |
| Autonomy Scout | `POST /v2/agents/autonomy-scout/invoke` | asynchronous | paper-only | Candidate scan and durable run enqueueing |

Except for the streaming `/v2/chat` interface, catalog operations require an
authenticated user. Account-scoped operations resolve that user's linked Alpaca
paper account; callers cannot select another user's account.

## Conversational Agent Flow

Web chat and both API chat forms reuse `engine/ai/chat_stream.py`. Per-user model
and framework settings are resolved by `agui_app.agent_for_user()`.

```mermaid
sequenceDiagram
    participant U as Client
    participant S as Chat stream
    participant I as Command interceptor
    participant C as CommandProcessor
    participant A as DeepAgent runtime
    participant T as Tools and engine

    U->>S: message, user ID, thread ID
    S-->>U: session event
    S->>I: inspect message
    alt Recognized CLI command
        I->>C: execute command
        C->>T: invoke tool or orchestrator
        T-->>C: result
        C-->>S: Markdown result
        S-->>U: route, token, done
    else Free-form request
        S->>A: messages plus thread history
        A->>T: structured tool calls
        S-->>U: tool_start and tool_end
        A-->>S: streamed model tokens
        S-->>U: route, tokens, done
    end
```

The runtime registry supports DeepAgents, LangGraph, Pydantic AI, and Hermes.
The default is DeepAgents; unavailable runtimes fall back in the order
DeepAgents → LangGraph → Hermes. Provider and model selection remain independent
of the agent framework.

### Are LangGraph and DeepAgents Both Used?

Yes, both are implemented, but only one configured runtime handles a given agent
invocation:

- **DeepAgents is the default.** `agui_app.primary_agent` and per-user chat agents
  are built through the runtime registry with `deepagents` preferred.
- **LangGraph remains an active runtime and fallback.** A user can select it via
  `agent_framework`, and it is selected automatically when DeepAgents is not
  installed or available.
- **DeepAgents is LangGraph-compatible.** `DeepAgentsRuntime` extends the shared
  `LangGraphRuntime` adapter because DeepAgents compiles to a compatible graph.
  This is shared execution infrastructure, not two agents answering in parallel.
- **Autonomy reasoning uses the same registry.** Optional LLM annotations use the
  configured framework, while checkpointing, risk gates, sizing, execution, and
  promotion gates remain framework-neutral and deterministic.
- **The five specialist agents are ordinary Python classes.** Backtest,
  validation, paper trading, reconciliation, and reporting are coordinated by
  `Orchestrator`; they do not require either graph framework to execute.

```mermaid
flowchart LR
    Request[Agent invocation]
    Settings[Per-user agent framework]
    Registry[Runtime registry]
    DA[DeepAgents default]
    LG[LangGraph selected or fallback]
    H[Hermes fallback]
    Graph[One LangGraph-compatible execution interface]

    Request --> Settings --> Registry
    Registry -->|preferred| DA --> Graph
    Registry -->|configured or fallback| LG --> Graph
    Registry -->|fallback| H --> Graph
```

## Five-Agent Orchestrator Flow

`agents/orchestrator.py` coordinates specialist classes and persists run state.
Validation can use `warn` mode or halt progression in `strict` mode.

```mermaid
flowchart TD
    Start[Create full run]
    BT[Backtest Agent]
    VB[Validation Agent: backtest trades]
    Gate1{Strict validation passed?}
    PT[Paper Trade Agent]
    VP[Validation Agent: paper trades]
    Gate2{Strict validation passed?}
    RC[Reconciliation Agent]
    RP[Report Agent]
    Done[Persist final result]
    Fail[Persist failed phase]

    Start --> BT
    BT -->|error| Fail
    BT --> VB --> Gate1
    Gate1 -->|no| Fail
    Gate1 -->|yes or warn mode| PT
    PT -->|error| Fail
    PT --> VP --> Gate2
    Gate2 -->|no| Fail
    Gate2 -->|yes or warn mode| RC --> RP --> Done
```

Agents publish requests and updates through `engine/agents/message_bus.py`, backed
by `data/agent_messages/`. Coarse state is stored in `data/agent_state.json`;
run, trade, validation, and account data are stored in PostgreSQL with `user_id`
and `account_id` scope.

## Durable Autonomy Flow

The autonomy worker is separate from the synchronous orchestrator. It claims a
PostgreSQL queue row, heartbeats ownership, and checkpoints every node so stale
or interrupted runs can resume without repeating completed work.

```mermaid
flowchart TD
    Tick[Worker tick]
    Requeue[Requeue stale runs]
    Pending{Queue empty?}
    Scout[Scout and enqueue]
    Claim[Claim with SKIP LOCKED]
    S[Scout candidates]
    B[Backtest]
    P{Deterministic paper risk gate}
    V[Validate backtest]
    T[Bounded paper trade]
    R[Reconcile]
    F[Refit from paper drift]
    M[Promotion evidence and notification]
    Ack[Acknowledge run]
    Retry[Retry or mark failed]

    Tick --> Requeue --> Pending
    Pending -->|yes| Scout --> Claim
    Pending -->|no| Claim
    Claim --> S --> B --> P
    P -->|admitted| V --> T --> R --> F --> M --> Ack
    P -->|none admitted| V
    S -. node error .-> Retry
    B -. node error .-> Retry
    T -. node error .-> Retry
```

The hard safety boundary is `engine/autonomy/policy.py`: live candidates are
rejected, sizing is deterministic, and the autonomy package only wires the paper
trading phase. LLM reasoning may annotate scouting, selection, refit, and
promotion decisions, but it cannot override the deterministic risk or promotion
gates.

## Operational Entry Points

```bash
python agents/orchestrator.py --mode full
python agents/orchestrator.py --mode validate --run-id <uuid>
python -m engine.autonomy.worker
```

Inspect REST schemas at `/docs`, `/redoc`, or `/openapi.json`. Monitor durable
runs in the authenticated Agent Pipeline page and in the `autonomy_runs`,
`autonomy_run_steps`, `autonomy_events`, and `autonomy_promotions` tables.
