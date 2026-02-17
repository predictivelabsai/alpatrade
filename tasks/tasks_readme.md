# Tasks Directory - README

This directory contains automated trading scripts for executing strategies via command line.

## Scripts

### `cli_trader.py` - Command-Line Trading Bot

Automated trading script that executes strategies on a schedule or continuously. Supports paper trading and live trading modes.

## Quick Start

### Prerequisites

1. Activate virtual environment:
```bash
source .venv/bin/activate
```

2. Set environment variables in `.env`:
```bash
ALPACA_PAPER_API_KEY=your_paper_key
ALPACA_PAPER_SECRET_KEY=your_paper_secret
EODHD_API_KEY=your_eodhd_key
```

## Paper Trading Examples

### Example 1: Single Run - Buy the Dip

Execute buy-the-dip strategy once and exit:

```bash
cd /home/julian/dev/hobby/strategy-simulator
source .venv/bin/activate
PYTHONPATH=/home/julian/dev/hobby/strategy-simulator python tasks/cli_trader.py \
  --strategy buy-the-dip \
  --mode paper \
  --symbols AAPL,MSFT,GOOGL \
  --capital 1000 \
  --dip-threshold 5.0
```

### Example 2: Continuous Trading (Recommended)

Run indefinitely, checking every 5 minutes:

```bash
cd /home/julian/dev/hobby/strategy-simulator
source .venv/bin/activate
PYTHONPATH=/home/julian/dev/hobby/strategy-simulator python tasks/cli_trader.py \
  --strategy buy-the-dip \
  --mode paper \
  --symbols AAPL,MSFT,GOOGL,AMZN,META,TSLA,NVDA \
  --capital 1000 \
  --dip-threshold 5.0 \
  --loop \
  --interval 300
```

**This is the recommended mode for paper trading that runs indefinitely.**

### Example 3: Aggressive Dip Buying

Lower threshold for more frequent trades:

```bash
cd /home/julian/dev/hobby/strategy-simulator
source .venv/bin/activate
PYTHONPATH=/home/julian/dev/hobby/strategy-simulator python tasks/cli_trader.py \
  --strategy buy-the-dip \
  --mode paper \
  --symbols AAPL,MSFT,GOOGL,AMZN,META,TSLA,NVDA,NFLX,AMD,INTC \
  --capital 500 \
  --dip-threshold 3.0 \
  --loop \
  --interval 180
```

### Example 4: Conservative Dip Buying

Higher threshold for fewer, larger dips:

```bash
cd /home/julian/dev/hobby/strategy-simulator
source .venv/bin/activate
PYTHONPATH=/home/julian/dev/hobby/strategy-simulator python tasks/cli_trader.py \
  --strategy buy-the-dip \
  --mode paper \
  --symbols AAPL,MSFT,GOOGL \
  --capital 2000 \
  --dip-threshold 7.0 \
  --loop \
  --interval 600
```

### Example 5: Dry Run Testing

Test the strategy without placing actual trades:

```bash
cd /home/julian/dev/hobby/strategy-simulator
source .venv/bin/activate
PYTHONPATH=/home/julian/dev/hobby/strategy-simulator python tasks/cli_trader.py \
  --strategy buy-the-dip \
  --mode paper \
  --symbols AAPL,MSFT,GOOGL \
  --capital 1000 \
  --dip-threshold 5.0 \
  --dry-run \
  --loop \
  --interval 60
```

### Example 6: Check Account Status

View current paper trading account status:

```bash
cd /home/julian/dev/hobby/strategy-simulator
source .venv/bin/activate
PYTHONPATH=/home/julian/dev/hobby/strategy-simulator python tasks/cli_trader.py \
  --strategy status \
  --mode paper
```

### Example 7: Close All Positions

Close all open positions in paper account:

```bash
cd /home/julian/dev/hobby/strategy-simulator
source .venv/bin/activate
PYTHONPATH=/home/julian/dev/hobby/strategy-simulator python tasks/cli_trader.py \
  --strategy close-all \
  --mode paper
```

## Command-Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--strategy` | Strategy to execute: `buy-the-dip`, `vix`, `close-all`, `status` | Required |
| `--mode` | Trading mode: `paper` or `live` | `paper` |
| `--symbols` | Comma-separated stock symbols | `AAPL,MSFT,GOOGL,AMZN,META,TSLA,NVDA` |
| `--capital` | Capital per trade in dollars | `1000` |
| `--dip-threshold` | Dip percentage to trigger buy (e.g., 5.0 = 5%) | `5.0` |
| `--take-profit-threshold` | Percentage gain to take profit | `1.0` |
| `--stop-loss-threshold` | Percentage loss to stop out | `0.5` |
| `--hold-days` | Minimum days to hold position (Mandatory for PDT if <$25k) | `2` |
| `--dry-run` | Test mode - no actual trades placed | `false` |
| `--once` | Run once and exit | `false` |
| `--interval` | Seconds between checks in continuous mode | `300` |

## Output Files

### Trading Log
- **File**: `trading.log`
- **Content**: Detailed execution logs with timestamps
- **Use**: Monitor strategy execution and debug issues

### Trade Records
- **File**: `reports/sample-back-testing-report.csv`
- **Content**: CSV log of all paper trades
- **Format**: Same as backtesting reports
- **Columns**: entry_time, exit_time, ticker, shares, entry_price, exit_price, pnl, pnl_pct, hit_target, hit_stop, capital_after, taf_fee, cat_fee, total_fees, dip_pct

## How It Works

### Buy-the-Dip Strategy

1. **Data Collection**: Fetches last 20 days of historical data via EODHD
2. **Dip Detection**: Calculates recent 20-day high and current price
3. **Signal Generation**: Triggers buy when `(high - current) / high >= threshold`
4. **Real-Time Pricing**: Uses EODHD `get_real_time_price()` for current prices
5. **Order Execution**: Places market orders via Alpaca paper trading API
6. **CSV Logging**: Records each trade to CSV file

### Loop Mode Operation

When `--loop` is enabled:
- Checks if market is open (via Alpaca API)
- Executes strategy if market is open
- Waits for `--interval` seconds
- Repeats indefinitely until stopped (Ctrl+C)

## Tips

1. **Start with dry-run**: Test your parameters with `--dry-run` first
2. **Monitor logs**: Keep an eye on `trading.log` for execution details
3. **Adjust threshold**: Lower threshold = more trades, higher threshold = fewer trades
4. **Use screen/tmux**: For long-running sessions, use `screen` or `tmux`
5. **Check positions**: Regularly run `--strategy status` to monitor your account

## Running in Background

Use `screen` or `tmux` for persistent sessions:

```bash
# Start a screen session
screen -S paper_trading

# Run the bot
cd /home/julian/dev/hobby/strategy-simulator
source .venv/bin/activate
PYTHONPATH=/home/julian/dev/hobby/strategy-simulator python tasks/cli_trader.py \
  --strategy buy-the-dip \
  --mode paper \
  --loop \
  --interval 300

# Detach: Ctrl+A, then D
# Reattach: screen -r paper_trading
```

## Troubleshooting

**ModuleNotFoundError**: Make sure to activate virtual environment and set PYTHONPATH
```bash
source .venv/bin/activate
export PYTHONPATH=/home/julian/dev/hobby/strategy-simulator
```

**No trades executing**: Check that dip threshold is appropriate for current market conditions

**API errors**: Verify your `.env` file has correct Alpaca and EODHD API keys
