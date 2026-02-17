# ETF Integration Walkthrough

This document outlines the integration of European and APAC ETFs into the Strategy Simulator home page. Users can now select these ETFs to compare their performance against their trading strategy and the S&P 500 (SPY).

## Changes Made

### 1. Global ETF Benchmarks Selection
A new multiselect has been added to the sidebar under the **Benchmarks** section. This allows users to select any of the 19 ETFs extracted from the provided market analysis.

### 2. Equity Curve Integration
When running a backtest, the selected Global ETFs are now calculated as buy-and-hold benchmarks and plotted on the **Equity Curve** chart. They are shown with `dash-dot` lines to distinguish them from the main strategy and SPY benchmarks.

### 3. ETF List
The following ETFs were added:
- **Europe:** Spain (EWP), Austria (EWO), Italy (EWI), Finland (EFNL), Germany (EWG), Belgium (EWK), Sweden (EWD), Switzerland (EWL), Great Britain (EWU), Netherlands (EWN), Norway (ENOR), Ireland (EIRL), France (EWQ).
- **Middle East:** Israel (EIS).
- **APAC:** Hong Kong (EWH), Singapore (EWS), Japan (EWJ), Australia (EWA).
- **Other:** Canada (EWC).

## Implementation Details

### Home.py
- Added `GLOBAL_ETFS` dictionary containing the symbol mappings.
- Included `GLOBAL_ETFS` in the `all_options` for sidebar holdings selection.
- Added a dedicated "Global Benchmarks" multiselect in the sidebar.
- Updated the backtest results processing to fetch data for selected benchmarks using `calculate_single_buy_and_hold`.
- Added traces to the Plotly equity curve for each selected benchmark.

## Verification Results

### Automated Verification
A verification script was run to confirm that all 19 ETF symbols are valid and return data from Yahoo Finance.

```bash
SUCCESS: Spain (EWP) (EWP)
SUCCESS: Austria (EWO) (EWO)
...
All symbols verified successfully!
```

### Manual Verification
The UI was updated to include the new selection:
1.  **Sidebar:** Added "Benchmarks" subheader with "Global Benchmarks (Europe/APAC)" multiselect.
2.  **Logic:** Updated backtest execution to fetch and calculate returns for each selected global ETF.
3.  **Graph:** Added traces for each selected ETF to the Plotly chart.
