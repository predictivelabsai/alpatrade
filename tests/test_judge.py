"""TypeSafe jev judge: provider flag, fallback to Grok, news sector mapping."""
from engine.ai import judge
from engine.research import news_intel as ni


class _R:
    def __init__(self, code, body):
        self.status_code, self._b = code, body

    def json(self):
        return self._b


class _H:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def post(self, url, **kw):
        self.calls.append(kw)
        return self.resp


def test_provider_flag(monkeypatch):
    monkeypatch.delenv("LLM_JUDGE_PROVIDER", raising=False)
    assert judge.judge_provider() == "grok" and not judge.use_typesafe()
    monkeypatch.setenv("LLM_JUDGE_PROVIDER", "typesafe")
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    assert judge.use_typesafe()


def test_decide_uses_jev(monkeypatch):
    monkeypatch.setenv("LLM_JUDGE_PROVIDER", "typesafe")
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    h = _H(_R(200, {"model": "jev-1.13.0", "answers": {"q": {"type": "noul", "noul": 0.9}},
                    "usage": {"input_tokens": 10}}))
    prov, res = judge.decide("s", {"q": {"type": "noul", "instructions": "?"}},
                             fallback=lambda: "grok", http=h)
    assert prov == "typesafe" and res["answers"]["q"]["noul"] == 0.9
    assert h.calls[0]["headers"]["Authorization"] == "Bearer k"


def test_decide_falls_back_on_error(monkeypatch):
    monkeypatch.setenv("LLM_JUDGE_PROVIDER", "typesafe")
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    for resp in (_R(529, {}), _R(200, {"answers": {}}), _R(200, "not json")):
        assert judge.decide("s", {"q": {}}, fallback=lambda: "G", http=_H(resp)) == ("grok", "G")


def test_decide_grok_when_flag_off(monkeypatch):
    monkeypatch.setenv("LLM_JUDGE_PROVIDER", "grok")
    h = _H(_R(200, {}))
    assert judge.decide("s", {"q": {}}, fallback=lambda: 1, http=h) == ("grok", 1) and not h.calls


def test_jev_item_maps_sectors():
    ans = {f"s{i}": {"choice": "neutral", "probabilities": {"neutral": 1.0}} for i in range(len(ni.SECTORS))}
    ans["s0"] = {"choice": "up", "probabilities": {"up": 0.9}}
    ans["s6"] = {"choice": "down", "probabilities": {"down": 0.6}}
    ans["move"] = {"score": 3.0}
    ai = ni.jev_item(ans)
    assert [x["sector"] for x in ai["sectors"]] == ["Technology", "Energy"]
    assert ai["sectors"][0]["direction"] == "up" and ai["sectors"][0]["move_pct"] == 4.5


def test_analyze_with_jev_shape(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    ans = {f"s{i}": {"choice": "neutral"} for i in range(len(ni.SECTORS))}
    ans["s0"] = {"choice": "up", "probabilities": {"up": 1.0}}
    ans["move"] = {"score": 1}
    h = _H(_R(200, {"model": "jev-1.13.0", "answers": ans, "usage": {}}))
    out = ni.analyze_with_jev([{"title": "Nvidia beats", "tickers": ["NVDA"]}], http=h)
    assert out["model"].startswith("jev") and out["sectors"][0]["sector"] == "Technology"
    assert out["items"][0]["ai"]["tickers"] == ["NVDA"]
