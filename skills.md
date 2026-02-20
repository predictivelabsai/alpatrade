# AlpaTrade Agent Skills Index

Master index of all agent skills in the multi-agent trading system.

## Agents

### 1. Portfolio Manager (Orchestrator)

- **Skill**: `agents/portfolio_manager/SKILL.md`
- **Role**: Orchestrator — dispatches work, tracks overall portfolio state
- **Triggers**: Session start, agent completion, error escalation
- **Capabilities**:
  - Coordinate BT -> PT -> Validation cycle
  - Track run IDs, agent status, iteration counts
  - Route messages between agents
  - Generate final consolidated reports

### 2. Backtester

- **Skill**: `agents/backtester/SKILL.md`
- **Role**: Run parameterized backtests with systematic variation
- **Triggers**: Portfolio Manager dispatches backtest request
- **Capabilities**:
  - Vary portfolio composition (Mag7 subsets, individual stocks)
  - Vary time intervals (1m, 3m, 6m, 1y lookbacks)
  - Vary strategy parameters (dip_threshold, take_profit, hold_days)
  - Store results to DB, report best configuration

### 3. Paper Trader

- **Skill**: `agents/paper_trader/SKILL.md`
- **Role**: Continuous paper trading via Alpaca paper API
- **Triggers**: Portfolio Manager starts session after backtest validates
- **Capabilities**:
  - Real Alpaca paper API orders (market orders, position tracking)
  - Configurable polling interval (default 5min)
  - Daily P&L tracking, trade logging to DB
  - Designed for multi-day continuous operation

### 4. Validator

- **Skill**: `agents/validator/SKILL.md`
- **Role**: Independent validation of backtest and paper trading results
- **Triggers**: Portfolio Manager requests validation after BT or PT completes
- **Capabilities**:
  - Fetch actual market prices from Massive API for each trade
  - Price tolerance checking (configurable, default 1%)
  - P&L math validation, market hours checks, weekend trade detection
  - Self-correction loop (max n=10 iterations)
  - Human-readable error reports when self-correction fails

### 5. Reconciler

- **Skill**: `agents/reconciler/SKILL.md`
- **Role**: Compare DB state against actual Alpaca holdings
- **Triggers**: Portfolio Manager dispatches reconciliation request
- **Capabilities**:
  - Position match: DB open trades vs Alpaca positions
  - Trade match: DB paper trades vs Alpaca filled orders (by order_id)
  - P&L comparison: DB total P&L vs Alpaca portfolio equity
  - Configurable time window (default 7 days)

### 6. Reporter

- **Skill**: `agents/reporter/SKILL.md`
- **Role**: Read-only performance reporting from DB
- **Triggers**: Report requests from Portfolio Manager or CLI
- **Capabilities**:
  - Summary mode: list recent runs with key metrics
  - Detail mode: full performance report for a single run
  - Top strategies: rank strategy slugs by average annualized return
  - Supports prefix matching on run_id

## Interaction Flow

```
Portfolio Manager
    |
    +--> Backtester (run N parameterized backtests)
    |        |
    |        v
    +--> Validator (validate backtest results)
    |        |
    |        v  (if valid)
    +--> Paper Trader (trade with validated parameters)
    |        |
    |        v
    +--> Validator (validate paper trading results)
    |        |
    |        v
    +--> Reconciler (compare DB vs Alpaca holdings)
    |        |
    |        v
    +--> Reporter (generate final performance report)
```

## Message Types

| Type | From | To | Description |
|------|------|----|-------------|
| `backtest_request` | PM | Backtester | Start parameterized backtest |
| `backtest_result` | Backtester | PM | Backtest completion + metrics |
| `validation_request` | PM | Validator | Validate a run's trades |
| `validation_result` | Validator | PM | Validation outcome + anomalies |
| `paper_trade_start` | PM | Paper Trader | Begin paper trading session |
| `trade_update` | Paper Trader | PM | Trade executed / position change |
| `paper_trade_result` | Paper Trader | PM | Session complete + summary |
| `reconciliation_request` | PM | Reconciler | Compare DB vs Alpaca for time window |
| `reconciliation_result` | Reconciler | PM | Reconciliation outcome + discrepancies |
| `report_request` | PM | Reporter | Generate performance report |
| `error` | Any | PM | Error requiring escalation |
| `correction` | Validator | Validator | Self-correction attempt |
