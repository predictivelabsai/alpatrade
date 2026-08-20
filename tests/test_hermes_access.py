"""Security-contract tests for the restricted Hermes broker."""
from pathlib import Path

import pytest

from engine.agents.hermes_access import (
    create_hermes_delegation,
    decode_hermes_delegation,
    hermes_system_instructions,
)


def test_delegation_is_user_scoped_and_short_lived(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "unit-test-secret")
    token = create_hermes_delegation(
        "11111111-1111-1111-1111-111111111111", "thread-7"
    )
    claims = decode_hermes_delegation(token)

    assert claims["sub"] == "11111111-1111-1111-1111-111111111111"
    assert claims["thread_id"] == "thread-7"
    assert claims["scope"] == "hermes:alpatrade"
    assert claims["exp"] - claims["iat"] == 600


def test_delegation_rejects_wrong_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "first-secret")
    token = create_hermes_delegation(
        "11111111-1111-1111-1111-111111111111", "thread-7"
    )
    monkeypatch.setenv("JWT_SECRET", "second-secret")
    with pytest.raises(ValueError):
        decode_hermes_delegation(token)


def test_system_instructions_forbid_direct_db_and_live(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "unit-test-secret")
    text = hermes_system_instructions(
        "11111111-1111-1111-1111-111111111111", "thread-7"
    )
    assert "no direct database access" in text
    assert "Live trading is forbidden" in text
    assert "/v2/hermes/" in text


@pytest.mark.asyncio
async def test_api_dependency_requires_dedicated_key(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi import HTTPException
    from api_app import require_hermes_user

    monkeypatch.setenv("JWT_SECRET", "unit-test-secret")
    monkeypatch.setenv("ALPATRADE_HERMES_API_KEY", "broker-only-secret")
    token = create_hermes_delegation(
        "11111111-1111-1111-1111-111111111111", "thread-7"
    )
    user = await require_hermes_user("broker-only-secret", token)
    assert user["user_id"] == "11111111-1111-1111-1111-111111111111"
    assert user["auth_type"] == "hermes"

    with pytest.raises(HTTPException) as error:
        await require_hermes_user("wrong", token)
    assert error.value.status_code == 401


def test_broker_exposes_paper_but_no_live_route():
    pytest.importorskip("fastapi")
    from api_app import app

    paths = app.openapi()["paths"]
    assert "/v2/hermes/backtests" in paths
    assert "/v2/hermes/candidates/{candidate_id}/paper" in paths
    assert all("live" not in path for path in paths if path.startswith("/v2/hermes/"))


def test_hermes_compose_service_has_no_database_or_trading_credentials():
    compose = Path("docker-compose.yaml").read_text(encoding="utf-8")
    hermes_service = compose.split("\n  api:", 1)[0]
    environment_lines = [
        line.strip() for line in hermes_service.splitlines()
        if line.strip().startswith("-")
    ]
    names = {line[1:].strip().split("=", 1)[0] for line in environment_lines}
    assert "DATABASE_URL" not in names
    assert "API_SERVICE_KEY" not in names
    assert "ALPACA_PAPER_API_KEY" not in names
    assert "ALPACA_PAPER_SECRET_KEY" not in names


def test_migration_never_creates_or_mutates_another_schema():
    migration = Path("sql/18_hermes_agent_attribution.sql").read_text(encoding="utf-8")
    assert "CREATE SCHEMA" not in migration.upper()
    assert "public." not in migration.lower()
    assert "alpatrade.strategy_candidates" in migration
