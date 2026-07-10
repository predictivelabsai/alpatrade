"""LLM provider connectivity test — provider-agnostic, XAI first.

Each provider is OpenAI-compatible (chat/completions via a base_url). A provider is
tested only when its API key is present in the environment; XAI is the primary one.
Add a provider by appending to PROVIDERS.

Env overrides: <PROVIDER>_CHAT_MODEL (e.g. XAI_CHAT_MODEL=grok-3).

Run (pytest):   python -m pytest tests/llm_test.py -v
Run (script):   python tests/llm_test.py
"""
import os
import sys
from pathlib import Path

try:
    import pytest
except ImportError:  # allow running as a plain script without pytest installed
    pytest = None

sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()


def _model(env_prefix: str, default: str) -> str:
    return os.getenv(f"{env_prefix}_CHAT_MODEL", default)


# name, api-key env var, base_url, default chat model. XAI is first / primary.
PROVIDERS = [
    ("xai",      "XAI_API_KEY",      "https://api.x.ai/v1",            _model("XAI", "grok-4.3")),
    ("openai",   "OPENAI_API_KEY",   "https://api.openai.com/v1",      _model("OPENAI", "gpt-4o-mini")),
    ("deepseek", "DEEPSEEK_API_KEY", "https://api.deepseek.com",       _model("DEEPSEEK", "deepseek-chat")),
    ("groq",     "GROQ_API_KEY",     "https://api.groq.com/openai/v1", _model("GROQ", "llama-3.1-8b-instant")),
]


def _chat(base_url: str, api_key: str, model: str) -> str:
    """Run a minimal chat completion and return the reply text."""
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Reply with exactly one word: pong"}],
        max_tokens=8,
        temperature=0,
    )
    return (resp.choices[0].message.content or "").strip()


if pytest is not None:
    @pytest.mark.parametrize("name, env_key, base_url, model", PROVIDERS,
                             ids=[p[0] for p in PROVIDERS])
    def test_provider_chat(name, env_key, base_url, model):
        """Each configured LLM provider answers a trivial chat completion."""
        key = os.getenv(env_key)
        if not key:
            pytest.skip(f"{env_key} not set")
        reply = _chat(base_url, key, model)
        assert reply, f"{name} ({model}) returned an empty completion"

    def test_configured_model_answers():
        """The effective chat model from engine.config answers — even if MODEL_NAME
        points at an unavailable model, build_chat_model must self-heal to a good one."""
        if not os.getenv("XAI_API_KEY"):
            pytest.skip("XAI_API_KEY not set")
        from engine.config import get_settings, build_chat_model
        llm = build_chat_model(get_settings(), streaming=False, max_tokens=8)
        reply = (llm.invoke("Reply with exactly one word: pong").content or "").strip()
        assert reply, "configured chat model returned an empty completion"


def _main() -> int:
    any_run, failed = False, 0
    for name, env_key, base_url, model in PROVIDERS:
        key = os.getenv(env_key)
        if not key:
            print(f"SKIP  {name:9} — {env_key} not set")
            continue
        any_run = True
        try:
            reply = _chat(base_url, key, model)
            if reply:
                print(f"PASS  {name:9} — {model} -> {reply[:40]!r}")
            else:
                print(f"FAIL  {name:9} — {model} returned empty completion")
                failed += 1
        except Exception as e:  # noqa: BLE001
            print(f"FAIL  {name:9} — {model}: {e!r}"[:160])
            failed += 1
    if not any_run:
        print("No LLM provider keys set (expected at least XAI_API_KEY).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
