"""Central, per-user-aware provider configuration.

Resolves the effective **model / market-data / search / agent-framework** provider
settings for a request by layering, in order of precedence:

    1. per-user overrides stored in ``alpatrade.user_settings`` (BYOK / Settings page)
    2. environment variables (deployment defaults, from ``.env``)
    3. hard-coded ``_DEFAULTS`` below

Because the web app and the REST API run in separate processes, per-user settings
live in the DB rather than in process state — both processes call
:func:`get_settings(user_id)` and resolve the same thing.

``build_chat_model(settings)`` turns the resolved model provider/name into a
LangChain chat model (XAI/OpenAI/DeepSeek/Groq are OpenAI-compatible; Anthropic
uses ``langchain-anthropic`` when installed).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, asdict
from functools import lru_cache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Choices surfaced in the Settings dropdowns and the effective fallbacks.
# grok-4.5 is listed but is region-locked on some XAI accounts (403); grok-4.3 is
# the newest model verified to answer, so it is the default.
# ---------------------------------------------------------------------------

MODEL_PROVIDERS = ["xai", "openai", "anthropic"]
MODEL_NAMES = {
    "xai": ["grok-4.3", "grok-4.5", "grok-3-mini"],
    "openai": ["gpt-4o", "gpt-4o-mini"],
    "anthropic": ["claude-sonnet-5", "claude-opus-4-8", "claude-haiku-4-5"],
}
MARKET_DATA_PROVIDERS = ["massive", "eodhd"]
SEARCH_PROVIDERS = ["tavily", "exa"]
AGENT_FRAMEWORKS = ["langgraph", "hermes", "deepagents"]

_DEFAULTS = {
    "model_provider": "xai",
    "model_name": "grok-4.3",
    "market_data_provider": "massive",
    "search_provider": "tavily",
    "agent_framework": "langgraph",
}

# Per-provider OpenAI-compatible endpoints + API-key env var.
_OPENAI_COMPAT = {
    "xai": ("https://api.x.ai/v1", "XAI_API_KEY"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
}


@dataclass
class Settings:
    model_provider: str
    model_name: str
    market_data_provider: str
    search_provider: str
    agent_framework: str

    def as_dict(self) -> dict:
        return asdict(self)


def _norm(val: str | None) -> str | None:
    """Normalise a provider token: lowercase, drop a trailing ``.com``/``.io`` and
    any inline comment (``massive.com  # eodhd.com`` → ``massive``)."""
    if not val:
        return val
    val = val.split("#", 1)[0].strip().lower()
    for suffix in (".com", ".io", ".ai", ".org"):
        if val.endswith(suffix):
            val = val[: -len(suffix)]
    return val or None


def _env_defaults() -> dict:
    """Deployment defaults from env, falling back to _DEFAULTS. Accepts the
    historical ``MARKED_DATA_PROVIDER`` misspelling as well as the correct one."""
    return {
        "model_provider": _norm(os.getenv("MODEL_PROVIDER")) or _DEFAULTS["model_provider"],
        "model_name": os.getenv("MODEL_NAME") or _DEFAULTS["model_name"],
        "market_data_provider": (
            _norm(os.getenv("MARKET_DATA_PROVIDER"))
            or _norm(os.getenv("MARKED_DATA_PROVIDER"))
            or _DEFAULTS["market_data_provider"]
        ),
        "search_provider": _norm(os.getenv("SEARCH_PROVIDER")) or _DEFAULTS["search_provider"],
        "agent_framework": _norm(os.getenv("AGENT_FRAMEWORK")) or _DEFAULTS["agent_framework"],
    }


@lru_cache(maxsize=32)
def _xai_model_available(model: str) -> bool:
    """Best-effort check that the XAI key may call ``model`` in this region.

    Cached per model. Only a *definitive* permission / not-found error marks a
    model unavailable; transient/network errors leave it assumed-available so we
    never wrongly downgrade a good model. Used to self-heal a stale MODEL_NAME
    (e.g. the region-locked grok-4.5) without any deploy change."""
    key = os.getenv("XAI_API_KEY")
    if not key:
        return True
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url="https://api.x.ai/v1", timeout=15, max_retries=0)
        client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": "hi"}],
            max_tokens=1, temperature=0,
        )
        return True
    except Exception as e:  # noqa: BLE001
        msg = str(e).lower()
        definitive = any(s in msg for s in (
            "not available", "permission", "does not exist", "not found", "403", "404",
        ))
        if definitive:
            logger.warning("XAI model %r unavailable (%s) — will fall back.", model, str(e)[:80])
            return False
        return True


def _resolve_xai_model(model: str) -> str:
    """Return ``model`` if callable, else the first working known-good XAI model."""
    if _xai_model_available(model):
        return model
    for candidate in MODEL_NAMES["xai"]:
        if candidate != model and _xai_model_available(candidate):
            logger.warning("Falling back from XAI model %r to %r.", model, candidate)
            return candidate
    return model  # nothing worked; let the real call surface the error


def get_settings(user_id: str | None = None) -> Settings:
    """Resolve effective settings for a user (or the deployment default)."""
    data = _env_defaults()
    if user_id:
        try:
            from engine.auth import get_user_settings
            for key, val in (get_user_settings(user_id) or {}).items():
                if val:
                    data[key] = val
        except Exception:  # noqa: BLE001 — never let settings lookup break a request
            pass
    return Settings(**data)


def build_chat_model(settings: Settings | None = None, *, streaming: bool = True,
                     temperature: float = 0.5, max_tokens: int = 3000):
    """Instantiate a LangChain chat model for the resolved model provider/name."""
    settings = settings or get_settings()
    provider = (settings.model_provider or "xai").lower()
    model = settings.model_name or _DEFAULTS["model_name"]

    if provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(model=model, temperature=temperature,
                                 max_tokens=max_tokens, streaming=streaming)
        except ImportError:
            # No anthropic backend installed → fall back to the XAI default.
            provider = "xai"
            model = _DEFAULTS["model_name"]

    base_url, key_env = _OPENAI_COMPAT.get(provider, _OPENAI_COMPAT["xai"])
    if provider == "xai":
        model = _resolve_xai_model(model)
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        api_key=os.getenv(key_env),
        base_url=base_url,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        streaming=streaming,
    )
