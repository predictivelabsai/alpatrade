"""Compatibility shim for the canonical :mod:`engine.feeds.market_data` module."""
import sys

import engine.feeds.market_data as _relocated

sys.modules[__name__] = _relocated
