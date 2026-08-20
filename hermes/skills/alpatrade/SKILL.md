---
name: alpatrade
description: Run user-scoped AlpaTrade backtests, save optimized candidates, inspect runs, and start paper trading.
---

# AlpaTrade broker

Use this skill only when the user asks to backtest, optimize, inspect a saved
candidate, or start paper trading. The system message supplies a short-lived
delegation token. The container supplies `ALPATRADE_API_URL` and
`ALPATRADE_HERMES_API_KEY`.

Every request must use both headers shown in the system message and the exact
internal base URL `http://api:5001`. Never use the public AlpaTrade domain and
never call a route outside `/v2/hermes/`. Never request database credentials.
Live trading is not supported.

Use the terminal with `curl` exactly as shown. Do not use Python, heredocs,
temporary files, package discovery, or OpenAPI downloads. Do not retry a failed
command with a different execution method; report the broker error to the user.

```bash
curl -sS -X POST "$ALPATRADE_API_URL/v2/hermes/backtests" \
  -H "Content-Type: application/json" \
  -H "X-Hermes-Key: $ALPATRADE_HERMES_API_KEY" \
  -H "X-Hermes-Delegation: <delegation-from-system-message>" \
  -d '{"strategy":"buy_the_dip","symbols":"AAPL,MSFT","lookback":"3m","objective":{"maximize":"sharpe_ratio"}}'
```

The response includes `candidate_id`. Use it to start paper trading:

```bash
curl -sS -X POST "$ALPATRADE_API_URL/v2/hermes/candidates/<candidate_id>/paper" \
  -H "Content-Type: application/json" \
  -H "X-Hermes-Key: $ALPATRADE_HERMES_API_KEY" \
  -H "X-Hermes-Delegation: <delegation-from-system-message>" \
  -d '{"duration":"7d"}'
```

List saved candidates with `GET /v2/hermes/candidates` and inspect an owned run
with `GET /v2/hermes/runs/<run_id>`. Summarize metrics and IDs for the user.
