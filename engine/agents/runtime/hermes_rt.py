"""Hermes adapter — Nous Research's deployable agent *runtime* (front-end/notifier).

Hermes is a runtime you deploy and talk to (Telegram/WhatsApp/CLI), not a
build-a-pipeline framework. So for pipeline nodes this adapter delegates reasoning to
LangGraph (a Hermes/xAI-served model still works through ``engine.config``), and adds
a ``notify()`` path for pushing autonomy digests/alerts to a Hermes channel.

Configure with ``HERMES_WEBHOOK_URL`` (+ optional ``HERMES_TOKEN``) to enable notify;
without it, ``notify`` is a no-op that returns False.
"""
from __future__ import annotations

import os

from engine.agents.runtime.langgraph_rt import LangGraphRuntime


class HermesRuntime(LangGraphRuntime):
    name = "hermes"

    @staticmethod
    def available() -> bool:
        # Always usable: pipeline reasoning falls through to LangGraph. Its distinct
        # value (a talk-to front-end / notifier) is opt-in via HERMES_WEBHOOK_URL.
        return True

    def notify(self, text: str) -> bool:
        """Push a message to the configured Hermes channel; False if not configured."""
        url = os.getenv("HERMES_WEBHOOK_URL")
        if not url:
            return False
        try:
            import requests
            headers = {}
            if os.getenv("HERMES_TOKEN"):
                headers["Authorization"] = f"Bearer {os.getenv('HERMES_TOKEN')}"
            r = requests.post(url, json={"text": text}, headers=headers, timeout=15)
            return r.status_code < 400
        except Exception:  # noqa: BLE001
            return False
