# CLI Trader - Command Line Trading Script

Execute trading strategies from the command line for automated and scheduled trading.

## Features

- **Multiple Strategies**: Buy-the-dip, VIX-based, and more
- **Paper & Live Trading**: Switch between simulation and real trading
- **Dry Run Mode**: Test without executing actual trades
- **Logging**: Comprehensive logging to file and console
- **Cron Compatible**: Easy integration with cron for scheduled execution

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Make script executable
chmod +x cli_trader.py

# Set up environment variables in .env
cp .env.example .env
# Edit .env and add your Alpaca API keys
```

## Usage

### Basic Commands

```bash
# Get account status
python cli_trader.py --strategy status --mode paper

# Execute buy-the-dip strategy (paper trading)
python cli_trader.py --strategy buy-the-dip --mode paper

# Execute VIX strategy (paper trading)
python cli_trader.py --strategy vix --mode paper

# Close all positions
python cli_trader.py --strategy close-all --mode paper
```

### Advanced Options

```bash
# Custom symbols
python cli_trader.py --strategy buy-the-dip --mode paper --symbols AAPL,MSFT,GOOGL

# Custom capital per trade
python cli_trader.py --strategy buy-the-dip --mode paper --capital 2000

# Custom dip threshold
python cli_trader.py --strategy buy-the-dip --mode paper --dip-threshold 7.5

# Custom VIX threshold
python cli_trader.py --strategy vix --mode paper --vix-threshold 25

# Dry run (no actual trades)
python cli_trader.py --strategy buy-the-dip --mode paper --dry-run

# Continuous loop (uses EODHD intraday prices; requires EODHD_API_KEY)
python cli_trader.py --strategy buy-the-dip --mode paper --loop --interval 300
```

### Live Trading

⚠️ **WARNING**: Live trading uses real money!

```bash
# Live trading with 5-second confirmation delay
python cli_trader.py --strategy buy-the-dip --mode live --symbols AAPL,MSFT

# Press Ctrl+C within 5 seconds to cancel
```

## Command Line Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--strategy` | str | **required** | Strategy to execute: `buy-the-dip`, `vix`, `close-all`, `status` |
| `--mode` | str | `paper` | Trading mode: `paper` or `live` |
| `--symbols` | str | `AAPL,MSFT,GOOGL,AMZN,META,TSLA,NVDA` | Comma-separated stock symbols |
| `--capital` | float | `1000.0` | Capital per trade in dollars |
| `--dip-threshold` | float | `5.0` | Dip threshold percentage for buy-the-dip |
| `--vix-threshold` | float | `20.0` | VIX threshold for VIX strategy |
| `--dry-run` | flag | `False` | Dry run mode (no actual trades) |
| `--loop` | flag | `False` | Continuously run with periodic checks |
| `--interval` | int | `300` | Polling interval in seconds for loop mode |

## Strategies

### Buy-the-Dip Strategy

Buys stocks when they dip below a threshold from recent highs.

**Logic:**
1. Calculate recent 20-day high
2. Compare intraday price (EODHD) to recent high
3. If dip >= threshold, place buy order

**Parameters:**
- `--dip-threshold`: Percentage dip to trigger buy (default: 5%)
- `--capital`: Capital to allocate per trade

**Example:**
```bash
python cli_trader.py \
  --strategy buy-the-dip \
  --mode paper \
  --symbols AAPL,MSFT,NVDA \
  --dip-threshold 7.5 \
  --capital 2000
```

### Continuous Loop Mode

Run periodically during market hours. Uses EODHD intraday prices when available.

```bash
python cli_trader.py --strategy buy-the-dip --mode paper --loop --interval 300
```

### VIX Strategy

Buys stocks when VIX (fear index) exceeds a threshold.

**Logic:**
1. Check current VIX level
2. If VIX >= threshold, buy all specified symbols
3. Hold overnight or close at end of day

**Parameters:**
- `--vix-threshold`: VIX level to trigger trades (default: 20)
- `--capital`: Capital to allocate per trade

**Example:**
```bash
python cli_trader.py \
  --strategy vix \
  --mode paper \
  --symbols AAPL,MSFT,GOOGL,AMZN \
  --vix-threshold 25 \
  --capital 1500
```

## Scheduled Execution with Cron

### Setup Cron Jobs

Edit your crontab:
```bash
crontab -e
```

### Example Cron Schedules

```bash
# Run buy-the-dip every weekday at 9:30 AM
30 9 * * 1-5 cd /path/to/strategy-simulator && /path/to/.venv/bin/python cli_trader.py --strategy buy-the-dip --mode paper

# Run VIX strategy every hour during trading hours
0 9-16 * * 1-5 cd /path/to/strategy-simulator && /path/to/.venv/bin/python cli_trader.py --strategy vix --mode paper

# Check account status every day at 4 PM
0 16 * * 1-5 cd /path/to/strategy-simulator && /path/to/.venv/bin/python cli_trader.py --strategy status --mode paper

# Close all positions at market close (3:55 PM)
55 15 * * 1-5 cd /path/to/strategy-simulator && /path/to/.venv/bin/python cli_trader.py --strategy close-all --mode paper

# Run every 15 minutes during trading hours
*/15 9-16 * * 1-5 cd /path/to/strategy-simulator && /path/to/.venv/bin/python cli_trader.py --strategy buy-the-dip --mode paper
```

### Cron Time Format

```
* * * * * command
│ │ │ │ │
│ │ │ │ └─── Day of week (0-6, 0=Sunday)
│ │ │ └───── Month (1-12)
│ │ └─────── Day of month (1-31)
│ └───────── Hour (0-23)
└─────────── Minute (0-59)
```

**Common Patterns:**
- `30 9 * * 1-5` - 9:30 AM on weekdays
- `0 9-16 * * 1-5` - Every hour from 9 AM to 4 PM on weekdays
- `*/15 * * * *` - Every 15 minutes
- `0 */2 * * *` - Every 2 hours

## Logging

Logs are written to:
- **Console**: Real-time output
- **File**: `trading.log` in the project directory

### Log Levels

- **INFO**: Strategy execution, trades, account status
- **WARNING**: Skipped symbols, insufficient quantity
- **ERROR**: API errors, failed orders

### View Logs

```bash
# View recent logs
tail -f trading.log

# View last 100 lines
tail -n 100 trading.log

# Search for errors
grep ERROR trading.log

# Search for successful trades
grep "Order placed" trading.log
```

## Environment Variables

Required in `.env` file:

```bash
# Paper Trading (default)
ALPACA_PAPER_API_KEY=your_paper_api_key
ALPACA_PAPER_SECRET_KEY=your_paper_secret_key

# Live Trading (optional)
ALPACA_LIVE_API_KEY=your_live_api_key
ALPACA_LIVE_SECRET_KEY=your_live_secret_key

# Market Data APIs
EODHD_API_KEY=your_eodhd_api_key   # used for intraday prices in CLI loop
# Optional fallback:
MASSIVE_API_KEY=your_massive_key
```

## Safety Features

1. **5-Second Confirmation**: Live trading has a 5-second delay to cancel
2. **Dry Run Mode**: Test strategies without executing trades
3. **Paper Trading Default**: Always defaults to paper mode
4. **Comprehensive Logging**: All actions logged for audit trail
5. **Error Handling**: Graceful handling of API errors

## Troubleshooting

### Common Issues

**"API keys not found"**
- Ensure `.env` file exists and contains valid API keys
- Check that you're using the correct mode (paper/live)

**"No data for symbol"**
- Symbol may be invalid or delisted
- Check symbol spelling and availability

**"Quantity too small"**
- Increase `--capital` parameter
- Stock price may be too high for allocated capital

**"Order failed: unauthorized"**
- Verify API keys are correct and active
- Check Alpaca account status

### Debug Mode

Run with verbose logging:
```bash
python cli_trader.py --strategy buy-the-dip --mode paper --dry-run
```

## Examples

### Morning Trading Routine

```bash
#!/bin/bash
# morning_trade.sh

cd /path/to/strategy-simulator
source .venv/bin/activate

# Check account status
python cli_trader.py --strategy status --mode paper

# Execute buy-the-dip strategy
python cli_trader.py \
  --strategy buy-the-dip \
  --mode paper \
  --symbols AAPL,MSFT,GOOGL,AMZN,META,TSLA,NVDA \
  --dip-threshold 5.0 \
  --capital 1000

# Execute VIX strategy if needed
python cli_trader.py \
  --strategy vix \
  --mode paper \
  --symbols SPY,QQQ,DIA \
  --vix-threshold 20 \
  --capital 2000
```

### End of Day Routine

```bash
#!/bin/bash
# eod_trade.sh

cd /path/to/strategy-simulator
source .venv/bin/activate

# Close all positions
python cli_trader.py --strategy close-all --mode paper

# Check final account status
python cli_trader.py --strategy status --mode paper
```

## Best Practices

1. **Start with Paper Trading**: Always test strategies in paper mode first
2. **Use Dry Run**: Test command-line arguments with `--dry-run`
3. **Monitor Logs**: Regularly check `trading.log` for issues
4. **Set Reasonable Capital**: Don't over-allocate capital per trade
5. **Diversify Symbols**: Trade multiple symbols to spread risk
6. **Schedule Wisely**: Avoid over-trading with too frequent cron jobs
7. **Test Cron Jobs**: Verify cron jobs work before relying on them
8. **Backup Logs**: Archive logs periodically for analysis

## Support

For issues or questions:
- Check logs in `trading.log`
- Review Alpaca API documentation
- Verify environment variables in `.env`
- Test with `--dry-run` flag first

## License

This script is part of the Strategy Simulator project.
