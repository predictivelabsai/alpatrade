# Trading Regulations & PDT

This document outlines the regulatory constraints observed by the trading system, specifically focusing on the **Pattern Day Trading (PDT)** rule.

## Pattern Day Trading (PDT) Rule

The PDT rule is a FINRA regulation that applies to margin accounts for investors who trade frequently.

### Definition of a Day Trade
A **day trade** is defined as the purchase and sale (or sale and purchase) of the same security on the same day in a margin account.

### Definition of a Pattern Day Trader
You are classified as a Pattern Day Trader if you execute **four or more day trades within five business days**, provided the number of day trades is more than 6% of the total trades in your account during that same five-day period.

### The $25,000 Requirement
Once classified as a Pattern Day Trader, you must maintain a minimum equity of **$25,000** in your margin account on any day that you trade. If your account equity falls below this threshold, you will be blocked from executing any new day trades until the balance is restored.

## System Implementation

To protect users from unintentional PDT violations and account locks, this system implements several safeguards:

### 1. Mandatory Overnight Hold
By default, the **Buy-The-Dip** strategy is configured to prevent same-day exits if the account value is under $25,000.
- **Backtesting**: The simulation ignores Take Profit and Stop Loss triggers on the day of entry. These triggers only become active on the following trading day.
- **Execution**: The `cli_trader.py` and associated logic will not close a position on the same day it was opened unless manually overridden.

### 2. Default Holding Period
The default `hold_days` parameter is set to **2 days**. This ensures that even if no price targets are hit, the position is held long enough to clear the day-trading window.

### 3. PDT Protection Toggle
For users with accounts over $25,000 (who are permitted to day trade), the `pdt_protection` flag can be set to `False` in the strategy configurations. This allows the system to capture same-day gains if a Take Profit target is reached.

---
> [!WARNING]
> While these safeguards are designed to help you stay compliant, you are ultimately responsible for monitoring your own account status and following FINRA regulations.
