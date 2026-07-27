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

from fastapi import FastAPI  # noqa: E402

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
