import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("rps", Path(__file__).resolve().parents[1] / "scripts/run_paper_strategy.py")
rps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rps)


def test_disabled_by_default_idles_without_run(monkeypatch):
    monkeypatch.delenv("PAPER_STRATEGY_ENABLED", raising=False)
    assert not rps.enabled()
    monkeypatch.setattr(rps, "idle_forever", lambda: 0)
    import utils.agent_storage as st
    monkeypatch.setattr(st, "store_run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no run")))
    assert rps.main() == 0


def test_enabled_flag(monkeypatch):
    monkeypatch.setenv("PAPER_STRATEGY_ENABLED", "1")
    assert rps.enabled()
