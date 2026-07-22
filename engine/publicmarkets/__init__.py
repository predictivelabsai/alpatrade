"""Public-markets tools borrowed from liquidround (backend reused, AlpaTrade UI).

Self-contained backends: `edgar` (SEC EDGAR — no DB), `market_intel` (sector ETF
heatmap — no DB). Phase 3 adds DB-backed tools (hedge funds, IPO map/pipeline) that
read the shared Postgres schemas (hedgefolio.*, liquidround.*, public.*).
"""
