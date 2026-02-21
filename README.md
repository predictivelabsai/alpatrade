# AlpaTrade

[![PyPI](https://img.shields.io/pypi/v/alpatrade)](https://pypi.org/project/alpatrade/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Trading strategy backtester, paper trader, and research CLI powered by [Alpaca Markets](https://alpaca.markets/).

![AlpaTrade CLI](https://raw.githubusercontent.com/predictivelabsai/alpatrade/main/screenshots/cli-welcome.png)

## Screenshots

### Web UI — Backtest Streaming
![Backtest Streaming](https://raw.githubusercontent.com/predictivelabsai/alpatrade/main/static/backtest-streaming.png)

### Web UI — News Research
![News Research](https://raw.githubusercontent.com/predictivelabsai/alpatrade/main/static/news.png)

### Web UI — Trade History
![Trade History](https://raw.githubusercontent.com/predictivelabsai/alpatrade/main/static/trades.png)

### Web UI — Command Reference
![Command Reference](https://raw.githubusercontent.com/predictivelabsai/alpatrade/main/static/help.png)

## Install

```bash
uv tool install alpatrade
```

## Quick Start

```bash
# Create .env with your API keys
cat > .env << 'EOF'
ALPACA_PAPER_API_KEY=your_key
ALPACA_PAPER_SECRET_KEY=your_secret
MASSIVE_API_KEY=your_massive_key
DATABASE_URL=postgresql://user:pass@host/dbname
EOF

# Launch the CLI
alpatrade
```

## Features

- **Parameterized backtesting** — grid search over dip threshold, take profit, hold days, and stop loss to find optimal strategy parameters ranked by Sharpe ratio
- **Paper trading** — continuous background trading on Alpaca's paper API with daily P&L email reports
- **Market research** — news, company profiles, financials, technicals, analyst ratings, and valuation comparisons
- **Multi-agent system** — backtest, validate, paper trade, reconcile, and report via an orchestrated agent pipeline
- **Extended hours & intraday exits** — pre/after-market trading (4AM-8PM ET) and 5-minute bar TP/SL timing
- **Interactive CLI** — prompt_toolkit-powered terminal with dropdown auto-completion, streaming log output, and Plotly equity curve charts

## Commands

```
agent:backtest lookback:1m          Run parameterized backtest
agent:paper duration:7d             Paper trade in background
agent:full lookback:1m duration:1m  Full cycle (BT > Validate > PT > Validate)
agent:validate run-id:<uuid>        Validate a backtest or paper trade run
agent:reconcile window:7d           Reconcile DB vs Alpaca positions

news:TSLA                           Company news headlines
price:TSLA                          Quote and technicals
financials:AAPL                     Income and balance sheet
analysts:AAPL                       Ratings and price targets
valuation:AAPL,MSFT                 Side-by-side valuation comparison
movers                              Top market gainers and losers

trades                              Recent trades from DB
runs                                Recent backtest/paper runs
agent:top                           Rank strategies by Avg Annual Return
agent:top strategy:btd              Filter by slug prefix
```

## Strategy Slugs

Each backtest variation gets a human-readable **slug** that encodes the strategy type, parameters, and lookback period into a compact identifier. Slugs let you compare configurations at a glance and filter results with `agent:top` or `agent:report`.

### Format

```
{strategy}-{param1}-{param2}-...-{lookback}
```

### Buy the Dip (`btd`)

| Token | Meaning |
|-------|---------|
| `btd` | Strategy: buy_the_dip |
| `{n}dp` | Dip threshold % |
| `{n}sl` | Stop loss % |
| `{n}tp` | Take profit % |
| `{n}d` | Hold (days) |
| `{period}` | Lookback (e.g. `1m`, `3m`) |

Example: `btd-7dp-05sl-1tp-1d-3m` = 7% dip, 0.5% stop loss, 1% take profit, 1 day hold, 3-month lookback

### Momentum (`mom`)

| Token | Meaning |
|-------|---------|
| `mom` | Strategy: momentum |
| `{n}lb` | Lookback period (days) |
| `{n}mt` | Momentum threshold % |
| `{n}d` | Hold (days) |
| `{n}tp` | Take profit % |
| `{n}sl` | Stop loss % |
| `{period}` | Lookback |

Example: `mom-20lb-5mt-5d-10tp-5sl-1m`

### VIX Fear Index (`vix`)

| Token | Meaning |
|-------|---------|
| `vix` | Strategy: vix |
| `{n}t` | VIX threshold |
| `{type}` | Hold type (e.g. `on` = overnight) |

Example: `vix-20t-on`

### Box-Wedge (`bwg`)

| Token | Meaning |
|-------|---------|
| `bwg` | Strategy: box_wedge |
| `{n}r` | Risk % |
| `{n}ct` | Contraction threshold % |

Example: `bwg-2r-5ct`

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ALPACA_PAPER_API_KEY` | Yes | Alpaca paper trading API key |
| `ALPACA_PAPER_SECRET_KEY` | Yes | Alpaca paper trading secret |
| `MASSIVE_API_KEY` | Yes | Polygon-compatible market data key |
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `XAI_API_KEY` | No | XAI Grok for AI research commands |
| `EODHD_API_KEY` | No | EOD Historical Data (intraday prices) |
| `POSTMARK_API_KEY` | No | Email notifications for paper trading |

## License

MIT
