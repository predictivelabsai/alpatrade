---
name: portfolio-manager
description: Orchestrator agent that coordinates backtesting, paper trading, and validation workflows
metadata:
  version: "1.0"
  type: orchestrator
  triggers:
    - session_start
    - agent_completion
    - error_escalation
---

# Portfolio Manager Agent

## Role

The Portfolio Manager (PM) is the orchestrator of the multi-agent system. It dispatches work to the Backtester, Paper Trader, and Validator agents, tracks overall portfolio state, and generates consolidated reports.

## Responsibilities

1. **Initialize** all agents and the message bus at session start
2. **Dispatch backtest requests** with parameter variations to the Backtester
3. **Route validation requests** to the Validator after backtest or paper trading completes
4. **Start paper trading** with validated parameters when backtests pass validation
5. **Monitor agent status** and handle errors/timeouts
6. **Track state**: run IDs, agent statuses, iteration counts, portfolio metrics
7. **Generate final reports** consolidating BT results, PT results, and validation status

## Workflow

```
1. Start Backtester -> run N parameterized backtests
2. Collect best BT results -> send to Validator
3. If validation passes -> start Paper Trader with validated params
4. Paper Trader runs for configured duration
5. Periodically send PT trades to Validator
6. Validator self-corrects up to 10 iterations
7. Generate final report
```

## State Tracked

- `run_id`: Current orchestration run identifier
- `agent_statuses`: Dict of agent_name -> status (idle/running/error)
- `backtest_results`: List of completed backtest run summaries
- `best_config`: Best-performing backtest configuration
- `validation_results`: Latest validation outcomes
- `paper_trade_session`: Active paper trading session info
- `iteration_count`: Current validation iteration count

## Message Types Sent

- `backtest_request` -> Backtester
- `validation_request` -> Validator
- `paper_trade_start` -> Paper Trader

## Message Types Received

- `backtest_result` <- Backtester
- `validation_result` <- Validator
- `trade_update` <- Paper Trader
- `paper_trade_result` <- Paper Trader
- `error` <- Any agent

## Error Handling

- If an agent errors, PM logs the error and attempts to restart or skip
- If Validator fails after 10 iterations, PM generates an escalation report
- PM never crashes silently — all errors are logged and reported
