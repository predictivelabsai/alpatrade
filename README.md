# AlpaTrade

[![PyPI](https://img.shields.io/pypi/v/alpatrade)](https://pypi.org/project/alpatrade/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Trading strategy backtester, paper trader, and research CLI powered by [Alpaca Markets](https://alpaca.markets/).

![AlpaTrade CLI](https://raw.githubusercontent.com/predictivelabsai/alpatrade/main/screenshots/cli-welcome.png)

## Screenshots

### AG-UI Chat — AI Research
![AI Chat](https://raw.githubusercontent.com/predictivelabsai/alpatrade/main/static/agui-chat.png)

### AG-UI Chat — News
![News](https://raw.githubusercontent.com/predictivelabsai/alpatrade/main/static/agui-landing.png)

### AG-UI Chat — Command Reference
![Help](https://raw.githubusercontent.com/predictivelabsai/alpatrade/main/static/agui-help.png)

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

## Architecture

```mermaid
graph TB
    subgraph Clients
        CLI["Rich CLI<br/><code>alpatrade.py</code><br/>prompt_toolkit"]
        AGUI["AG-UI Chat<br/><code>agui_app.py</code><br/>port 5003"]
        WEB["Web UI<br/><code>web_app.py</code><br/>port 5002"]
        API["REST API<br/><code>api_app.py</code><br/>port 5001"]
    end

    subgraph AI
        AGENT["pydantic-ai Agent<br/>XAI Grok-3-mini"]
        TOOLS["Agent Tools<br/>positions, charts,<br/>news, prices"]
    end

    subgraph Agents["Multi-Agent System"]
        ORCH["Orchestrator"]
        BT["Backtester"]
        PT["Paper Trader"]
        VAL["Validator"]
        REC["Reconciler"]
    end

    subgraph External
        ALPACA["Alpaca Paper API"]
        MARKET["Market Data<br/>Polygon / yfinance"]
        DB[("PostgreSQL<br/><code>alpatrade</code> schema")]
    end

    CLI -->|commands| ORCH
    AGUI -->|WebSocket| AGENT
    AGUI -->|CLI commands| ORCH
    AGENT --> TOOLS
    WEB --> ORCH
    API --> ORCH

    ORCH --> BT
    ORCH --> PT
    ORCH --> VAL
    ORCH --> REC

    BT --> MARKET
    BT --> DB
    PT --> ALPACA
    PT --> DB
    VAL --> MARKET
    VAL --> DB
    REC --> ALPACA
    REC --> DB
    TOOLS --> ALPACA
    TOOLS --> MARKET
    TOOLS --> DB
```

```mermaid
sequenceDiagram
    participant U as User
    participant C as AG-UI Chat
    participant I as Command Interceptor
    participant A as AI Agent
    participant O as Orchestrator
    participant DB as PostgreSQL

    U->>C: "agent:backtest lookback:1m"
    C->>I: detect CLI command
    I->>O: process_command()
    O-->>DB: store results
    O-->>C: streaming logs + result
    C-->>U: backtest card + equity pill

    U->>C: "equity:592beaec"
    C->>I: detect equity: command
    I-->>DB: query trades
    I-->>C: __CHART_DATA__ marker
    C-->>U: Plotly equity curve

    U->>C: "show me AAPL analysis"
    C->>A: free-form → AI agent
    A->>A: call tools (price, news)
    A-->>C: streamed markdown
    C-->>U: formatted response
```

## Features

- **Parameterized backtesting** — grid search over dip threshold, take profit, hold days, and stop loss to find optimal strategy parameters ranked by Sharpe ratio
- **Paper trading** — continuous background trading on Alpaca's paper API with daily P&L email reports, startup order sync, and PDT protection
- **Market research** — news, company profiles, financials, technicals, analyst ratings, and valuation comparisons
- **Charts** — stock price charts and backtest equity curves rendered with Plotly in the artifacts pane
- **Alpaca integration** — live positions, account summary, and order management via Alpaca paper API
- **Multi-agent system** — backtest, validate, paper trade, reconcile, and report via an orchestrated agent pipeline
- **Extended hours & intraday exits** — pre/after-market trading (4AM-8PM ET) and 5-minute bar TP/SL timing
- **AI chat** — AG-UI protocol chat with pydantic-ai agent (XAI Grok-3-mini) for free-form stock research
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

chart:AAPL                          Stock price chart (3mo default)
chart:TSLA period:1y                Custom period chart
equity:<run_id>                     Equity curve for a backtest run

positions                           Open positions from Alpaca
account                             Account summary (value, cash, buying power)

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

## Running Locally

### Prerequisites

- Python 3.13+
- PostgreSQL with an `alpatrade` schema
- API keys (see [Environment Variables](#environment-variables))

### Setup

```bash
git clone https://github.com/predictivelabsai/alpatrade.git
cd alpatrade
uv sync
cp .env.example .env   # then fill in your API keys
```

### Run the CLI

```bash
uv run python alpatrade.py
```

### Run the AG-UI Chat (port 5003)

The AG-UI app is a chat interface built on the [AG-UI protocol](https://docs.ag-ui.com) with FastHTML. It supports CLI commands, AI research queries, and real-time streaming via WebSocket.

```bash
uv run uvicorn agui_app:app --host 0.0.0.0 --port 5003 --reload
```

Open [http://localhost:5003](http://localhost:5003) in your browser.

### Run the Web UI (port 5002)

```bash
uv run python web_app.py
```

### Run the API Server (port 5001)

```bash
uv run uvicorn api_app:app --host 0.0.0.0 --port 5001 --reload
```

## License

MIT
