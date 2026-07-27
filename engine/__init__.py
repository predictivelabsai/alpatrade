"""AlpaTrade shared engine.

This package is the seed of the asset-agnostic backtesting + paper-trading engine
that all verticals (equities, crypto, FX, prediction markets) will plug into.

Phase 0 ships the `engine.backtest` methodology layer — a faithful implementation of
the Alpaca `alpaca-trading-backtest` skill contract (deterministic dated artifact
folders, data fingerprints, named fill models, the Teaching Five, mandatory
disclosures) running on Alpaca market data via the official `alpaca-py` SDK.
"""
