"""AlpaTrade unified REST API (Phase 1) — port 5002.

Single FastAPI entry point. Each asset vertical is mounted under a versioned
namespace `/api/v1/<vertical>`. Phase 1 ships the equities vertical (the existing
api_app FastAPI app); crypto/fx/prediction/research mount in their merge phases.

Run:  ASSETHERO_API_PORT=5002 python api.py
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from fastapi import FastAPI, Depends, HTTPException  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import api_app  # noqa: E402  (existing equities FastAPI app)

app = FastAPI(
    title="AlpaTrade API",
    version="0.2.0",
    description="Multi-asset trading platform API. Verticals mount under /api/v1/<vertical>.",
)


@app.get("/api/v1/health", tags=["meta"])
def health():
    return {
        "status": "ok",
        "service": "alpatrade",
        "version": "0.2.0",
        "verticals": {
            "equities": "/api/v1/equities",
            "crypto": "pending",
            "fx": "pending",
            "prediction": "pending",
            "research": "pending",
        },
    }


# ---------------------------------------------------------------------------
# Settings — cross-vertical, so lives at the top level (Phase 3e)
# ---------------------------------------------------------------------------

class SettingsUpdate(BaseModel):
    model_provider: str | None = None
    model_name: str | None = None
    market_data_provider: str | None = None
    search_provider: str | None = None
    agent_framework: str | None = None


@app.get("/api/v1/settings", tags=["settings"])
async def get_settings_endpoint(user: dict | None = Depends(api_app.get_current_user)):
    """Return the caller's effective settings (per-user overrides merged over env defaults)."""
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    from engine.config import get_settings
    s = get_settings(user["user_id"])
    return {
        "model_provider": s.model_provider,
        "model_name": s.model_name,
        "market_data_provider": s.market_data_provider,
        "search_provider": s.search_provider,
        "agent_framework": s.agent_framework,
    }


@app.patch("/api/v1/settings", tags=["settings"])
async def patch_settings_endpoint(
    req: SettingsUpdate,
    user: dict | None = Depends(api_app.get_current_user),
):
    """Update the caller's per-user settings (model, framework, providers).

    Only non-null fields are written; null fields are ignored (not cleared).
    The change takes effect immediately — no restart needed (the web UI's
    /settings/preferences does the same and evicts the agent cache; for the
    REST path the next agent invocation picks up the new settings lazily).
    """
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    from engine.auth import store_user_settings, USER_SETTING_FIELDS
    updates = {f: getattr(req, f) for f in USER_SETTING_FIELDS if getattr(req, f) is not None}
    if not updates:
        return {"updated": False, "reason": "no fields to update"}
    store_user_settings(user["user_id"], **updates)
    # Evict caches so the change is live for the next request/reasoning call.
    try:
        from agui_app import clear_agent_cache
        clear_agent_cache()
    except Exception:  # noqa: BLE001
        pass
    try:
        from engine.autonomy.reason import clear_reasoning_cache
        clear_reasoning_cache()
    except Exception:  # noqa: BLE001
        pass
    return {"updated": True, "fields": list(updates.keys())}


# Equities vertical: the existing api_app endpoints (/auth/*, /v2/*) under the namespace.
app.mount("/api/v1/equities", api_app.app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=int(os.getenv("ASSETHERO_API_PORT", "5002")),
        reload=False,
    )
