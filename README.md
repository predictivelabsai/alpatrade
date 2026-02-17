# AlpaTrade

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Trading strategy backtester, paper trader, and research CLI powered by [Alpaca Markets](https://alpaca.markets/).

## Install

```bash
pip install alpatrade
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
- **Interactive CLI** — Rich-powered terminal with streaming log output and Plotly equity curve charts

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
agent:top                           Rank strategies by Sharpe ratio
```

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
