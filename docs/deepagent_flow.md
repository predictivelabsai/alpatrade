# DeepAgent End-to-End Flow

This is the source-of-truth flow for the implemented AlpaTrade DeepAgent
integration in version 0.10.0. It covers the canonical API, compatibility chat
transports, specialist routing, tenant and action safety, durable jobs, and the
daily paper-trading advisor.

Two graphs have deliberately different jobs:

- The **interactive coordinator** answers authenticated chat/API requests,
  delegates to six specialists, and may call tenant-scoped tools.
- The **scheduled daily advisor** is read-only and stateless. It receives a
  deterministic evidence package and can only rank server-created candidate IDs.

The legacy five-agent `Orchestrator` and the autonomy worker are execution
services called below the DeepAgent tool layer. They are not additional native
DeepAgent subagents.

## Complete System Map

```mermaid
flowchart TB
    subgraph Entry["Client entry points"]
        Canonical["POST /v2/deepagents<br/>JSON or SSE"]
        Web["Web free-form chat"]
        Mobile["POST /v2/chat"]
        CompatJson["POST /v2/agents/chat/invoke"]
        Command["Recognized web CLI command"]
    end

    Auth["FastAPI authentication<br/>JWT, service identity, or signed internal identity"]
    CommandProcessor["CommandProcessor<br/>outside the DeepAgent graph"]
    Compat["Compatibility event adapter"]
    PublicGraph["Anonymous stateless graph<br/>public research only"]
    Service["DeepAgentService<br/>durable interactive coordinator"]

    subgraph Interactive["Interactive DeepAgent graph"]
        Coordinator["AlpaTrade coordinator"]
        Specialists["Six named specialists"]
        ReadTools["Public and tenant-scoped read tools"]
        ActionTools["Explicit-intent paper-only tools"]
    end

    Transcript[("Chat transcripts and<br/>DeepAgent response records")]
    Checkpoints[("PostgreSQL LangGraph<br/>checkpoints")]
    Market["Market, research, and SEC providers"]
    Broker["Owned Alpaca paper account"]
    TradingDB[("Tenant-scoped trading data")]
    ActionLedger[("DeepAgent action ledger")]
    JobQueue[("PostgreSQL autonomy queue")]
    Worker["Autonomy worker<br/>checkpointed job pipelines"]
    Orchestrator["Backtest, validate, paper,<br/>reconcile, and report services"]

    Scheduler["NYSE-aware advisor scheduler<br/>session close plus delay"]
    Evidence["Deterministic advisor evidence,<br/>severity, and candidate engine"]
    AdvisorGraph["Read-only scheduled DeepAgent<br/>structured AdvisorDraft"]
    Reports[("Persisted advisor reports<br/>and delivery state")]
    Surfaces["Dashboard, advisor API,<br/>email, and DeepAgent chat"]

    Canonical --> Auth --> Service
    Web -->|"free-form text"| Compat
    Web -->|"known command"| Command --> CommandProcessor
    Mobile --> Compat
    CompatJson --> Compat
    Compat -->|"authenticated"| Service
    Compat -->|"anonymous"| PublicGraph

    Service <--> Transcript
    Service <--> Checkpoints
    Service --> Coordinator
    Coordinator --> Specialists
    Coordinator --> ReadTools
    Specialists --> ReadTools
    Specialists --> ActionTools
    ReadTools --> Market
    ReadTools --> TradingDB
    ReadTools --> Broker
    ActionTools --> ActionLedger
    ActionTools -->|"immediate idempotent paper order"| Broker
    ActionTools -->|"durable job"| JobQueue
    JobQueue --> Worker --> Orchestrator
    Orchestrator --> TradingDB
    Orchestrator --> Broker

    Scheduler --> JobQueue
    Worker --> Evidence --> AdvisorGraph --> Reports
    Evidence -->|"model unavailable or rejected"| Reports
    Reports --> Surfaces
    Specialists -->|"trading-advisor reads stored reports"| Reports
```

The canonical endpoint always builds with `create_deep_agent`. It does not switch
to LangGraph, Pydantic AI, or Hermes when DeepAgents is unavailable. The selected
model still comes from the caller's settings, and the graph cache is keyed by the
effective provider, actual model name, and public/authenticated mode.

## Entry and Authentication Routing

```mermaid
flowchart TD
    Request["Incoming chat request"] --> Route{"Which transport?"}

    Route -->|"POST /v2/deepagents"| TenantAuth["Require concrete tenant identity"]
    TenantAuth -->|"JWT"| Canonical["Canonical durable request"]
    TenantAuth -->|"service key plus X-User-Id"| Canonical
    TenantAuth -->|"signed internal identity"| Canonical
    TenantAuth -->|"missing tenant identity"| Reject401["Reject before graph execution"]

    Route -->|"web or compatibility API"| UserKnown{"Authenticated user ID?"}
    UserKnown -->|"yes"| CompatDurable["Create deterministic compatibility thread UUID<br/>then use canonical durable service"]
    UserKnown -->|"no"| Anonymous["Fresh stateless public-only graph"]

    Anonymous --> PublicTools["Market-research specialist and public research tools only"]
    Anonymous --> NoPrivate["No accounts, portfolio, reports,<br/>actions, or durable checkpoint"]
```

For web chat, known CLI commands are intercepted before this routing and sent to
`CommandProcessor`. Free-form text uses the compatibility adapter. The canonical
`POST /v2/deepagents` endpoint never passes through the command interceptor.

## Canonical Request Lifecycle

The final client message UUID is the response idempotency key. A request
fingerprint also covers the complete submitted message batch and selected
`account_id`.

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant API as FastAPI
    participant S as DeepAgentService
    participant D as DeepAgent store
    participant P as Postgres checkpointer
    participant G as create_deep_agent graph
    participant T as Specialist or tool

    C->>API: messages, optional thread and account, stream flag
    API->>API: validate schema and authenticate tenant
    API->>S: initialize and prepare request
    S->>P: initialize strict PostgreSQL checkpointer
    S->>D: close stale running response records
    S->>S: resolve per-user provider and model, then get cached graph
    S->>D: validate account ownership and ensure thread ownership
    S->>D: reserve response by final message UUID and fingerprint

    alt terminal response already recorded with same fingerprint
        D-->>S: completed or failed payload
        S-->>API: replay payload with cached true
        API-->>C: identical JSON or reconstructed SSE events
    else response or thread is already running
        D-->>API: in-progress conflict
        API-->>C: HTTP 409
    else message UUID was reused with different content
        D-->>API: fingerprint conflict
        API-->>C: HTTP 409
    else new response reserved
        S->>D: append request messages atomically
        S->>P: look up tenant-qualified graph thread
        alt no graph checkpoint exists
            S->>D: load full owned transcript
            D-->>S: user and assistant history
        else checkpoint exists
            S->>S: submit only the new message batch
        end
        S->>G: stream graph events with trusted DeepAgentContext
        G->>T: call common tool or named specialist
        T-->>G: scoped and sanitized result
        G-->>S: tokens plus tool lifecycle events
        S->>D: persist metadata-only event envelopes
        opt no event before heartbeat interval
            S->>D: update response heartbeat
            S-->>C: SSE ping
        end
        S-->>C: stream coordinator tokens when SSE is enabled
        G-->>S: final graph state
        S->>D: save assistant message and terminal payload
        S-->>API: completed response
        API-->>C: JSON response or SSE done event
    end
```

The checkpoint thread key is tenant-qualified as `user_id:thread_id`, while
application transcripts and response records retain explicit ownership columns.
Only coordinator output is emitted as the final answer; nested specialist model
tokens are not leaked directly into the client stream.

If execution fails, the service persists a terminal failed payload. Replaying the
same message returns that failure instead of rerunning tools. If an SSE client
disconnects before completion, the response is marked failed so a possibly
completed side effect is not silently repeated.

## Coordinator and Specialist Routing

The general-purpose DeepAgents subagent is disabled. The coordinator can use a
small set of fast reads directly or delegate through `task` to exactly these six
specialists.

```mermaid
flowchart LR
    User["User request"] --> Coordinator["Coordinator<br/>plan, route, synthesize"]

    Coordinator --> Common["Common fast reads<br/>price, news, accounts, account summary,<br/>positions, recent runs, job status, latest advisor report"]
    Coordinator --> Task["task with a named specialist"]

    Task --> Research["market-research<br/>public market, company, SEC,<br/>fund, IPO, SPAC, and prediction research"]
    Task --> Portfolio["portfolio-analyst<br/>owned positions, trades, profit and loss,<br/>runs, reports, jobs, and advisor history"]
    Task --> Strategy["strategy-lab<br/>queue backtests, queue stored advisor tests,<br/>validate owned runs, compare results"]
    Task --> Paper["paper-trader<br/>paper orders and sessions, contracts,<br/>reconciliation, cancellation, monitoring"]
    Task --> Orch["orchestrator<br/>queue full cycle or autonomy scout,<br/>inspect and cancel owned jobs"]
    Task --> Advisor["trading-advisor<br/>read-only latest and historical<br/>persisted daily reports"]

    Research --> PublicData["Public providers"]
    Portfolio --> TenantData["Tenant-scoped database and paper broker"]
    Strategy --> SafeActions["Explicit-intent action boundary"]
    Paper --> SafeActions
    Orch --> SafeActions
    Advisor --> StoredReports[("advisor_reports")]
```

The `trading-advisor` specialist is intentionally read-only. Executing one of its
stored recommendations belongs to `strategy-lab` or `paper-trader` and requires a
later imperative user message.

## Tenant, Tool, and Action Safety

`DeepAgentContext` is constructed by the application and injected through
`ToolRuntime`; the model cannot choose its `user_id`, `account_id`, thread,
response, or request message. Middleware carries that trusted context into nested
specialist calls.

```mermaid
flowchart TD
    Call["Model requests a tool"] --> Blocked{"Filesystem or shell tool?"}
    Blocked -->|"yes"| RejectTool["Return blocked ToolMessage"]
    Blocked -->|"no"| Context["Read trusted DeepAgentContext"]
    Context --> Tenant{"Tool needs tenant access?"}
    Tenant -->|"yes, but anonymous or missing user"| RejectTenant["Reject without data access"]
    Tenant -->|"no or authenticated"| Mutating{"Tool can change state?"}

    Mutating -->|"no"| ScopedRead["Query public data or filter every read<br/>by trusted user and account"]
    Mutating -->|"yes"| Intent{"Final user text has explicit action intent<br/>and is not hypothetical or advisory?"}
    Intent -->|"no"| RejectAction["Reject and report that no action occurred"]
    Intent -->|"yes"| Ownership["Validate owned account, report, run,<br/>credentials, and action-specific preconditions"]
    Ownership --> Allowed{"Permitted server-side test<br/>or paper-only execution path?"}
    Allowed -->|"no"| RejectLive["Reject live execution"]
    Allowed -->|"yes"| Mode{"Execution mode"}

    Mode -->|"queued job"| ReserveJob["Reserve idempotent action row"]
    ReserveJob --> QueueDedupe["Enqueue with deterministic dedupe key"]
    Mode -->|"immediate paper order"| ReserveOrder["Reserve action and deterministic client order ID"]
    ReserveOrder --> AlpacaPaper["Submit once to Alpaca paper API"]
    Mode -->|"synchronous validation or reconciliation"| Sync["Run tenant-scoped service"]
```

The host tools `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`, and
`execute` are excluded from the harness and rejected by middleware. API traces
store tool name, call ID, status, and timestamps only; arguments, results,
credentials, and raw exceptions are excluded.

## Durable Action Jobs

Long-running work is queued in PostgreSQL. A worker atomically claims the oldest
eligible row with `FOR UPDATE SKIP LOCKED`, heartbeats it, and checkpoints every
pipeline node. The dedicated advisor lane can claim daily reports while the
general lane is occupied by a long paper session.

```mermaid
flowchart TD
    Tool["Explicit-intent DeepAgent tool"] --> Action[("deepagent_actions")]
    Action --> Queue[("autonomy_runs<br/>queued and deduplicated")]
    Scheduler["Daily advisor scheduler"] --> Queue
    Queue --> Claim["Worker claim with SKIP LOCKED"]
    Claim --> Kind{"Job kind"}

    Kind -->|"deepagent_backtest"| Backtest["Pipeline definition<br/>Backtest"]
    Kind -->|"deepagent_paper"| Paper["Pipeline definition<br/>Bounded paper session"]
    Kind -->|"deepagent_full"| Full["Pipeline definition<br/>Backtest, validate, paper, validate,<br/>reconcile, report"]
    Kind -->|"deepagent_advisor"| Daily["Pipeline definition<br/>One tenant daily-advisor batch"]
    Kind -->|"full autonomy"| Auto["Pipeline definition<br/>Scout, backtest, risk gate, validate,<br/>paper, reconcile, refit, promotion evidence"]

    Backtest --> Next["Run next unfinished pipeline node"]
    Paper --> Next
    Full --> Next
    Daily --> Next
    Auto --> Next
    Next --> Save["Persist node result and event"]
    Save --> More{"More nodes?"}
    More -->|"yes"| Next
    More -->|"no"| Done["Acknowledge job as done"]
    Next -. "cancel signal" .-> Cancelled["Stop safely and mark cancelled"]
    Next -. "node failure" .-> Failure{"Paper-capable uncertainty?"}
    Failure -->|"yes"| FailClosed["Fail without automatic retry"]
    Failure -->|"no"| Retry["Requeue within attempt limit<br/>and resume from completed checkpoints"]
```

A resumed job skips each node already recorded as completed. `full`,
`deepagent_paper`, and `deepagent_full` fail closed after an uncertain worker
loss, because retrying could duplicate paper activity. Backtest and advisor jobs
may be retried and resume from their persisted step state.

## Daily Advisor Scheduling and Generation

The autonomy worker is the only scheduler owner. It asks Alpaca for the actual
NYSE session close, so weekends, holidays, early closes, and daylight-saving
changes do not rely on a fixed UTC time.

```mermaid
flowchart TD
    Tick["Advisor scheduler poll"] --> Enabled{"ADVISOR_ENABLED?"}
    Enabled -->|"no"| Stop["Do nothing"]
    Enabled -->|"yes"| Date["Resolve current America/New_York date"]
    Date --> Users["Find active users with linked encrypted credentials"]
    Users --> Pending{"User and session already handled in this process?"}
    Pending -->|"yes"| SkipUser["Skip user"]
    Pending -->|"no"| Calendar["Read and cache Alpaca market close for the date"]
    Calendar --> Session{"Trading session exists?"}
    Session -->|"no"| NoSession["No report job for holiday or weekend"]
    Session -->|"yes"| Due{"Actual close plus configured delay has passed?"}
    Due -->|"no"| Wait["Wait for next poll"]
    Due -->|"yes"| Accounts["Verify usable owned Alpaca paper accounts"]
    Accounts --> Batch["Enqueue one deepagent_advisor batch<br/>per user and session"]
    Batch --> Dedupe[("Database dedupe key<br/>user plus session")]
    Dedupe --> Lane["Dedicated advisor worker lane"]
    Lane --> PerAccount["Generate one report per account"]
```

For every account in the batch, the report engine follows this flow:

```mermaid
flowchart TD
    Start["Reserve unique user, account, session report"] --> Existing{"Completed or partial report already stored?"}
    Existing -->|"yes"| Reuse["Reuse the persisted report"]
    Existing -->|"no"| BrokerEvidence["Collect broker equity history,<br/>positions, exposure, and concentration"]
    Existing -->|"no"| DatabaseEvidence["Collect paper trades scoped to the exact slug when available,<br/>plus current config, matched backtest, validation,<br/>and reconciliation"]
    BrokerEvidence --> Merge["Keep broker account profit and loss separate<br/>from AlpaTrade-attributed realized profit and loss"]
    DatabaseEvidence --> Merge
    Merge --> Normalize["Normalize comparison units<br/>without changing raw backtest values"]
    Normalize --> Regime["Add market regime, policy limits,<br/>quality warnings, and attribution residual"]
    Regime --> Classify["Apply deterministic severity gates"]
    Classify --> Candidates["Create risk actions and eligible tests;<br/>test values come only from current config, refit grid,<br/>regime preset, or stored backtest candidates"]
    Candidates --> ScheduledGraph["create_deep_agent<br/>no tools, no checkpointer,<br/>only read-only trading-advisor subagent"]
    ScheduledGraph --> Draft["Structured AdvisorDraft<br/>candidate IDs, order, exact rationale, evidence refs"]
    Draft --> Validate{"Application validation passes?"}
    Validate -->|"yes"| Assemble["Assemble recommendations from<br/>the original server-side candidates"]
    Validate -->|"no"| Fallback["Deterministic fallback<br/>status partial"]
    ScheduledGraph -. "model unavailable" .-> Fallback
    Assemble --> SaveReport[("Save evidence plus one advisory payload")]
    Fallback --> SaveReport
    SaveReport --> NoExecution["No order, parameter change,<br/>restart, cancellation, or test is queued"]
```

The scheduled graph uses `AdvisorDraft` as its structured response type. The
application rejects unknown or duplicated candidate IDs, missing or unsupported
evidence references, altered numbers, invented explanations, and omitted eligible
candidates on `review` or `urgent` reports. Parameter values are copied from the
server-side candidate after validation; they are never accepted from model text.

### Severity Decision Order

The implementation applies urgent risk gates first, so an urgent account cannot
be hidden by a small paper-trade sample.

```mermaid
flowchart TD
    Evidence["Deterministic evidence"] --> Urgent{"Daily equity loss at least 2 percent<br/>or configured risk-policy breach?"}
    Urgent -->|"yes"| U["urgent"]
    Urgent -->|"no"| Sample{"Fewer than 5 closed paper trades?"}
    Sample -->|"yes"| I["insufficient_data"]
    Sample -->|"no"| Review{"Paper Sharpe below 50 percent of matched backtest,<br/>or at least 3 losing sessions,<br/>or 20-session drawdown at least 5 percent?"}
    Review -->|"yes"| R["review"]
    Review -->|"no"| M["monitor"]

    I --> Explain["Persist why_no_change"]
    M --> Explain
    R --> Approval["Recommend eligible tests or risk review only"]
    U --> Approval
```

Thresholds are configurable through `ADVISOR_*` environment variables; the
diagram shows the shipped defaults. No-trade and profitable sessions still get a
report, with an explicit explanation when no change is justified.

## Consolidated Delivery and Shared Surfaces

The report is written once. Dashboard, API, email, and chat use the same stored
`evidence` and `advisory` payload instead of independently generating another
advisor report.

```mermaid
flowchart TD
    Reports["All account reports in the user batch"] --> Failed{"Any account report failed?"}
    Failed -->|"yes"| Partial["Mark batch partial and send no incomplete email"]
    Failed -->|"no"| Delivery["Reserve unique user, session,<br/>email, and recipient delivery"]
    Delivery --> Sent{"Already sent?"}
    Sent -->|"yes"| Reuse["Reuse delivery record"]
    Sent -->|"no"| Unknown{"Sending or outcome unknown?"}
    Unknown -->|"yes"| NoDuplicate["Do not risk a duplicate email"]
    Unknown -->|"no"| EmailEnabled{"ADVISOR_EMAIL_ENABLED?"}
    EmailEnabled -->|"no"| Disabled["Persist delivery as disabled"]
    EmailEnabled -->|"yes"| Claim["Atomically claim delivery before provider call"]
    Claim --> Compose["Render one email from all stored account reports"]
    Compose --> Postmark["Send to active user's login email"]
    Postmark --> Result["Persist sent or failed status and attempt count"]

    Stored[("advisor_reports")]
    Stored --> APIList["GET /v2/advisor/reports"]
    Stored --> APIDetail["GET /v2/advisor/reports/{report_id}"]
    Stored --> Dashboard["Persisted advisor card and history"]
    Stored --> ChatTools["get_latest_advisor_report<br/>get_advisor_history"]
    Stored --> Compose
```

Email is disabled by default. A delivery left in `sending` after an uncertain
provider outcome is moved to `unknown` and is not automatically resent.

## Turning Advice Into a Paper Test

A report is never an instruction to execute. The user must issue separate,
explicit messages for each transition.

```mermaid
flowchart TD
    Report[("Persisted report recommendation")] --> AskTest["User explicitly asks to run this recommendation"]
    AskTest --> StrategyLab["strategy-lab calls queue_advisor_backtest"]
    StrategyLab --> Load["Server loads owned report and exact stored test_config<br/>by report ID and recommendation ID"]
    Load --> BacktestJob["Queue deduplicated deepagent_backtest job"]
    BacktestJob --> Complete{"Owned backtest completed with trades?"}
    Complete -->|"no"| Stop["No paper session"]
    Complete -->|"yes"| AskValidate["User explicitly asks to validate the run"]
    AskValidate --> Validation["Validation passes or is corrected"]
    Validation --> AskPaper["User separately asks to start paper from the run"]
    AskPaper --> PaperGate["Verify owned, completed, non-empty,<br/>validated buy-the-dip backtest"]
    PaperGate -->|"fail"| Reject["Reject without queuing"]
    PaperGate -->|"pass"| PaperJob["Queue bounded deepagent_paper session<br/>with the stored best parameters"]
    PaperJob --> Alpaca["Owned Alpaca paper account only"]
```

`queue_advisor_backtest` never accepts a replacement parameter grid from the
model. `queue_paper_from_backtest` currently supports `buy_the_dip` only and
requires an owned completed backtest, at least one trade, a stored best
configuration, and a passed or corrected backtest validation.

## Persistence Map

```mermaid
erDiagram
    USERS ||--o{ USER_ACCOUNTS : owns
    USERS ||--o{ CHAT_CONVERSATIONS : owns
    USERS ||--o{ AUTONOMY_RUNS : owns
    CHAT_CONVERSATIONS ||--o{ CHAT_MESSAGES : contains
    USERS ||--o{ DEEPAGENT_RESPONSES : invokes
    USER_ACCOUNTS o|--o{ DEEPAGENT_RESPONSES : scopes
    CHAT_CONVERSATIONS ||--o{ DEEPAGENT_RESPONSES : records
    DEEPAGENT_RESPONSES ||--o{ DEEPAGENT_EVENTS : emits
    DEEPAGENT_RESPONSES ||--o{ DEEPAGENT_ACTIONS : authorizes
    AUTONOMY_RUNS o|--o{ DEEPAGENT_ACTIONS : linked_job
    AUTONOMY_RUNS ||--o{ AUTONOMY_RUN_STEPS : checkpoints
    AUTONOMY_RUNS ||--o{ AUTONOMY_EVENTS : logs
    USER_ACCOUNTS ||--o{ ADVISOR_REPORTS : receives
    USERS ||--o{ ADVISOR_DELIVERIES : receives
    ADVISOR_DELIVERIES }o--o{ ADVISOR_REPORTS : includes_ids
    CHAT_CONVERSATIONS ||--o{ LANGGRAPH_CHECKPOINTS : logical_thread

    DEEPAGENT_RESPONSES {
        uuid response_id PK
        uuid user_id FK
        uuid thread_id FK
        uuid request_message_id
        string request_fingerprint
        string status
        jsonb response_payload
    }

    DEEPAGENT_ACTIONS {
        uuid action_id PK
        uuid response_id FK
        uuid job_id FK
        string tool_call_id
        string tool_name
        string order_client_id
        string status
    }

    AUTONOMY_RUNS {
        uuid run_id PK
        uuid user_id FK
        uuid account_id
        string kind
        string status
        string dedupe_key
        jsonb config
    }

    ADVISOR_REPORTS {
        uuid report_id PK
        uuid user_id FK
        uuid account_id FK
        date session_date
        string status
        string severity
        jsonb evidence
        jsonb advisory
    }

    ADVISOR_DELIVERIES {
        uuid delivery_id PK
        uuid user_id FK
        date session_date
        string channel
        string recipient
        jsonb report_ids
        string status
    }
```

`LANGGRAPH_CHECKPOINTS` represents the official checkpointer tables as a logical
entity; they are created by `AsyncPostgresSaver` and use the tenant-qualified
thread key rather than an application foreign key. `advisor_deliveries.report_ids`
is a JSON list used to compose one user email, not a physical join table.

## Failure and Replay Behavior

```mermaid
stateDiagram-v2
    [*] --> Running: response reserved
    Running --> Running: heartbeat and SSE ping
    Running --> Completed: assistant and payload committed
    Running --> Failed: graph error or stream disconnect
    Running --> Failed: stale process detected at initialization
    Completed --> Completed: same message replays cached payload
    Failed --> Failed: same message replays recorded failure
    Running --> Conflict: duplicate or concurrent request
    Completed --> Conflict: same message ID with different fingerprint
    Failed --> Conflict: same message ID with different fingerprint
```

Operationally important fallbacks are:

- Canonical DeepAgent, model, or checkpointer unavailable: return HTTP 503.
- Blocked or unauthorized tool: return a tool error without exposing data.
- Scheduled advisor model unavailable or invalid: persist a deterministic
  `partial` report with metrics, severity, and a generation note.
- Broker evidence unavailable: persist quality warnings and keep broker results
  distinct from locally attributed strategy results.
- Paper-capable worker heartbeat lost: fail closed and do not automatically retry.
- Email outcome uncertain: record `unknown` and do not automatically resend.

## Implementation References

- Canonical service and event lifecycle: [`engine/ai/deepagents.py`](../engine/ai/deepagents.py)
- Trusted context, tools, and specialist definitions: [`engine/ai/deepagent_tools.py`](../engine/ai/deepagent_tools.py)
- Durable response and action store: [`engine/ai/deepagent_store.py`](../engine/ai/deepagent_store.py)
- API contracts and endpoints: [`api_app.py`](../api_app.py) and [`api_models.py`](../api_models.py)
- Compatibility chat adapter: [`engine/ai/chat_stream.py`](../engine/ai/chat_stream.py)
- Queue, worker, and checkpointed pipelines: [`engine/autonomy/queue.py`](../engine/autonomy/queue.py), [`engine/autonomy/worker.py`](../engine/autonomy/worker.py), and [`engine/autonomy/graph.py`](../engine/autonomy/graph.py)
- NYSE-aware scheduling: [`engine/autonomy/schedule.py`](../engine/autonomy/schedule.py)
- Advisor evidence and delivery engine: [`engine/reporting/advisor.py`](../engine/reporting/advisor.py)
- Database definitions: [`sql/22_deepagent_responses.sql`](../sql/22_deepagent_responses.sql) and [`sql/23_daily_advisor.sql`](../sql/23_daily_advisor.sql)
