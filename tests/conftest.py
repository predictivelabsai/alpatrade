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


# --- No prod users from tests ------------------------------------------------
# Tests that really create accounts must use ``test_email()`` (dedicated
# ``@alpatrade-test.invalid`` domain, auto-deleted after a day by
# engine.web.antibot.purge_stale_accounts) and, ideally, a separate database via
# ALPATRADE_TEST_DATABASE_URL. Any other address is refused here.
import os as _os
import uuid as _uuid

TEST_EMAIL_DOMAIN = "alpatrade-test.invalid"

if _os.getenv("ALPATRADE_TEST_DATABASE_URL"):
    _os.environ["DATABASE_URL"] = _os.environ["ALPATRADE_TEST_DATABASE_URL"]


def test_email(prefix: str = "t") -> str:
    return f"{prefix}-{_uuid.uuid4().hex[:10]}@{TEST_EMAIL_DOMAIN}"


test_email.__test__ = False  # not a test function

