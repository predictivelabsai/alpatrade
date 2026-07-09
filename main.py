"""Entrypoint. Thin shim so standard runners (``python main.py``) work without
changes — all routing lives in :mod:`app`."""
import os

from app import app, serve  # noqa: F401

if __name__ == "__main__":
    serve(port=int(os.getenv("ASSETHERO_WEB_PORT", "5001")))
