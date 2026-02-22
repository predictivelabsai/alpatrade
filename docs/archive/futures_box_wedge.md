# Futures Trading with Box & Wedge Strategy

## Overview

The Futures Trading page provides a dedicated interface for trading ES and NQ index futures using Christian Carion's Box & Wedge methodology. This strategy focuses on identifying price contractions (boxes) and entering on breakouts of tighter contractions within those boxes (wedges), allowing for extremely tight stop losses and high reward-to-risk ratios.

## Accessing the Futures Page

Navigate to **Futures** in the Streamlit sidebar to access the dedicated futures trading interface.

## Supported Instruments

### Futures Contracts
- **ES=F**: S&P 500 E-mini futures
- **NQ=F**: Nasdaq 100 E-mini futures
- **YM=F**: Dow Jones E-mini futures
- **RTY=F**: Russell 2000 E-mini futures

### ETF Proxies
For easier backtesting with more historical data:
- **SPY**: S&P 500 ETF
- **QQQ**: Nasdaq 100 ETF
- **DIA**: Dow Jones ETF
- **IWM**: Russell 2000 ETF

## Box & Wedge Strategy

### Christian Carion's Methodology

Christian Carion's trading philosophy revolves around using index futures to generate cash flow with a rules-based approach that emphasizes risk management and fractal market structure.

#### The Box & Wedge Framework

**1. Box Identification (Contraction Period)**
- A period where price is "ping-ponging" in a range, showing low volatility
- Detected when recent price range is less than 70% of the average historical range
- Typically identified on hourly charts
- Represents consolidation before the next move

**2. Wedge Identification (Tighter Contraction)**
- A tighter contraction within the box, showing lower highs and higher lows
- Detected when price range within the wedge is less than 60% of the box range
- Typically 20 periods within the box
- Provides the precise entry trigger

**3. Entry Trigger**
- Breakout of the wedge high (NOT the full box breakout)
- Advantage: Tighter stop loss (at wedge low) vs. waiting for box breakout
- Entry should align with the hourly trend (EMA 9 > EMA 20)

### Risk Management

#### The "All-In" Concept
- **Definition**: 100% invested in a single position while keeping total account risk at ~1%
- **Calculation**: Position size = (Account Capital × 1%) / (Entry Price - Stop Price)
- **Result**: Larger position sizes with extremely tight stops

#### Stop Loss Placement
- **Initial Stop**: At the wedge low (below the tighter contraction)
- **Move to Breakeven**: After 1.5R target is hit
- **Trailing Stop**: Optional for runners

### Scale-Out Approach

The strategy takes profits in three stages:

1. **50% at 1.5R** (1.5 times the risk)
   - First profit target
   - Locks in gains quickly
   - Moves stop to breakeven for remaining position

2. **25% at 3R** (3 times the risk)
   - Second profit target
   - Captures extended moves
   - Reduces position further

3. **25% Runner**
   - Kept with stop at breakeven
   - Captures large trend moves
   - No fixed target; exit on trend reversal

### Trend Filters

**Bull/Bear Filter (Daily)**
- Bullish: Price > 200-day SMA
- Bearish: Price < 200-day SMA
- Action: Only trade in direction of the daily trend

**Short-Term Momentum (Hourly)**
- EMA 9 and EMA 20 for trend direction
- Bullish: EMA 9 > EMA 20
- Bearish: EMA 9 < EMA 20
- Exit Signal: Two consecutive closes below EMA 20 often signals trend end

### Zone Rotations

Christian identifies horizontal "zones" where price typically reacts:
- **ES (S&P 500)**: Rotations occur roughly every 12-15 points
- **NQ (Nasdaq)**: Rotations occur roughly every 25-35 points
- Purpose: Helps identify potential support/resistance levels

## Configurable Parameters

### Box Detection
- **Contraction Threshold**: Box contraction threshold (default: 0.7 = 70% of average range)
- **Box Lookback Periods**: Periods to look back for box identification (default: 100)

### Wedge Detection
- **Wedge Lookback Periods**: Periods to look back for wedge within box (default: 20)

### Risk Management
- **Risk Per Trade (%)**: Percentage of capital to risk per trade (default: 1%)

### Scale Out Targets
- **1.5R Target (%)**: Percentage of position to exit at 1.5R (default: 50%)
- **3R Target (%)**: Percentage of position to exit at 3R (default: 25%)
- **Runner (%)**: Percentage of position to keep as runner (default: 25%)

### Data Configuration
- **Data Frequency**: Recommended 5m or 15m for entries, 1h for trend alignment
- **Initial Capital**: Starting capital for backtest
- **Date Range**: Backtest period

## Usage Example

1. **Select Futures/Proxies**: Choose ES=F and NQ=F (or SPY/QQQ proxies)
2. **Choose Strategy**: Select "box-wedge" from strategy dropdown
3. **Configure Parameters**:
   - Contraction Threshold: 0.7
   - Box Lookback: 100
   - Wedge Lookback: 20
   - Risk Per Trade: 1%
   - Scale Out: 50% at 1.5R, 25% at 3R, 25% runner
4. **Set Timeframe**: Use 5m or 15m for entries
5. **Run Backtest**: Click "Run Backtest" button

## Implementation Details

### Strategy Module
The Box & Wedge strategy is implemented in [`utils/box_wedge.py`](file:///home/julian/dev/hobby/strategy-simulator/utils/box_wedge.py) with the following key functions:

- `calculate_indicators()`: Calculates EMA 9, EMA 20, SMA 200, and ATR
- `is_bullish_regime()`: Checks if price is above 200 SMA
- `find_box_contraction()`: Identifies box (contraction period)
- `find_wedge_within_box()`: Identifies wedge within box
- `calculate_position_size()`: Calculates position size based on 1% risk
- `backtest_box_wedge_strategy()`: Main backtest function

### Futures Page
The Futures trading page is located at [`pages/5_Futures.py`](file:///home/julian/dev/hobby/strategy-simulator/pages/5_Futures.py) and provides:

- Dedicated UI for futures trading
- ES/NQ futures symbol selection
- All Box & Wedge configurable parameters
- Full backtesting capabilities with fee support
- Performance metrics and equity curves

## Key Considerations

- **Patience Required**: Wait for proper box and wedge formation
- **Frequent Stops**: Tight stops mean you may get stopped out frequently
- **Scale-Out Discipline**: Follow the scale-out plan to capture profits while staying in winners
- **Trend Alignment**: Works best when aligned with higher timeframe trends
- **Timeframe Selection**: Use 2m/5m for entries, 1h for trend confirmation

## References

- Christian Carion's trading methodology emphasizes risk management and fractal market structure
- The "All-In" concept: 100% invested with 1% total account risk
- Scale-out approach: 1.5R, 3R, and runners for optimal risk/reward

## Related Documentation

- [Methodology Page](file:///home/julian/dev/hobby/strategy-simulator/pages/10_Methodology.py): Comprehensive strategy documentation
- [Box & Wedge Module](file:///home/julian/dev/hobby/strategy-simulator/utils/box_wedge.py): Strategy implementation
- [Futures Page](file:///home/julian/dev/hobby/strategy-simulator/pages/5_Futures.py): Trading interface
