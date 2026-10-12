"""Shared test setup: deterministic security exclusions (no DB / Alpaca asset lookups)."""
import pytest


@pytest.fixture(autouse=True)
def _pinned_exclusions(monkeypatch):
    from engine.reporting import exclusions
    monkeypatch.setenv("EXCLUSION_AUTO_ASSET_STATUS", "0")
    monkeypatch.delenv("EXCLUSION_DUST_USD", raising=False)
    exclusions.set_rules_for_tests([dict(r) for r in exclusions.FALLBACK_RULES])
    yield
    exclusions.set_rules_for_tests(None)
