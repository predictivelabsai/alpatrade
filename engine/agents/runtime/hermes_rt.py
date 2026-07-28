"""Hermes adapter — LangGraph reasoning + Hermes channel notifier.

Hermes is a runtime you deploy and talk to (Telegram/WhatsApp/CLI). It is not a
separate pipeline engine — for ``build``/``run``/``stream`` this adapter
inherits LangGraph (so any xAI/OpenAI-served model works through
``engine.config``), and adds a ``notify()`` path for pushing autonomy digests
and alerts to a Hermes channel. Selecting ``AGENT_FRAMEWORK=hermes`` therefore
gives identical reasoning behaviour to ``langgraph`` plus the notifier side-channel.

The autonomy pipeline's ``promote`` node calls ``notify()`` directly
(``engine/autonomy/notify.py``) when ``HERMES_WEBHOOK_URL`` is set. The
``reason()`` helper (``engine/autonomy/reason.py``) uses this runtime for
LLM-backed reasoning when it's the configured framework.

Configure with ``HERMES_WEBHOOK_URL`` (+ optional ``HERMES_TOKEN``) to enable
notify; without it, ``notify`` is a no-op that returns False.
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
