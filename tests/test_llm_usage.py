from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest


class Result:
    def __init__(self, scalar=0, rows=None): self.value, self.rows = scalar, rows or []
    def scalar(self): return self.value
    def mappings(self): return self
    def all(self): return self.rows


class Session:
    def __init__(self, scalar=0): self.value, self.calls = scalar, []
    def execute(self, sql, params):
        self.calls.append((str(sql), params))
        return Result(self.value)


class Pool:
    def __init__(self, session): self.session = session
    @contextmanager
    def get_session(self): yield self.session


def test_usage_migration_is_tenant_scoped_and_contains_no_credentials():
    sql = Path("sql/30_llm_usage_logging.sql").read_text(encoding="utf-8")
    assert "alpatrade.llm_usage_logging" in sql
    assert "user_id UUID" in sql
    assert "funding_source" in sql
    assert "api_key_enc" not in sql


def test_extract_measured_usage_and_estimate_fallback():
    from engine.ai.llm_usage import estimate_usage, extract_usage
    measured = extract_usage({"usage": {"prompt_tokens": 10, "completion_tokens": 4}})
    assert (measured.input_tokens, measured.output_tokens, measured.total_tokens) == (10, 4, 14)
    assert measured.quality == "measured"
    estimated = estimate_usage("abcd" * 4, "wxyz" * 2)
    assert estimated.total_tokens == 6
    assert estimated.quality == "estimated"


def test_record_usage_saves_metadata_not_prompt_or_key(monkeypatch):
    from engine.ai import llm_usage
    session = Session()
    monkeypatch.setattr(llm_usage, "get_pool", lambda: Pool(session))
    llm_usage.record_usage(
        user_id="11111111-1111-1111-1111-111111111111",
        thread_id="22222222-2222-2222-2222-222222222222",
        agent="hermes", provider="xai", model="model", funding_source="platform",
        prompt="private prompt", response="private response",
    )
    _sql, params = session.calls[0]
    assert "private prompt" not in str(params)
    assert "private response" not in str(params)
    assert params["agent"] == "hermes"
    assert params["total"] > 0


def test_platform_daily_budget_blocks_but_byok_does_not(monkeypatch):
    from engine.ai import llm_usage
    monkeypatch.setattr(llm_usage, "daily_platform_cost", lambda *_a: Decimal("5.01"))
    with pytest.raises(llm_usage.DailyBudgetExceeded):
        llm_usage.enforce_daily_budget(funding_source="platform")
    llm_usage.enforce_daily_budget(funding_source="user_byok")


def test_budget_warning_at_80_and_90_percent(monkeypatch):
    from engine.ai import llm_usage
    monkeypatch.setattr(llm_usage, "PLATFORM_DAILY_BUDGET_USD", Decimal("5"))
    monkeypatch.setattr(llm_usage, "daily_platform_cost", lambda *_a: Decimal("4.10"))
    assert "80%" in llm_usage.budget_warning(funding_source="platform")
    monkeypatch.setattr(llm_usage, "daily_platform_cost", lambda *_a: Decimal("4.60"))
    assert "90%" in llm_usage.budget_warning(funding_source="platform")
    assert llm_usage.budget_warning(funding_source="user_byok") is None


def test_non_admin_usage_queries_are_owner_scoped(monkeypatch):
    from engine.ai import llm_usage
    session = Session()
    monkeypatch.setattr(llm_usage, "get_pool", lambda: Pool(session))
    llm_usage.list_usage("11111111-1111-1111-1111-111111111111", is_admin=False)
    assert "l.user_id = CAST(:uid AS UUID)" in session.calls[0][0]
