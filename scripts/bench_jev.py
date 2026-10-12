"""Benchmark TypeSafe jev vs Grok on the news sector-impact judging task.

Usage: python scripts/bench_jev.py [N]   (reads XAI_API_KEY / TYPESAFE_API_KEY from .env)
Prints latency, token usage, estimated cost and sector-direction agreement. No secrets printed.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402

import os  # noqa: E402
load_dotenv(os.getenv("ALPATRADE_ENV") or Path(__file__).resolve().parents[1] / ".env", override=True)
from engine.research import news_intel as ni  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 8
rows = ni.collect(limit=60)["rows"][:N]
print(f"{len(rows)} live headlines")

t = time.perf_counter()
jev = ni.analyze_with_jev(rows)
jev_s = time.perf_counter() - t

ni._analysis_cache["key"] = None
model = ni._build_model()
t = time.perf_counter()
grok = ni.analyze_with_ai(rows, model=model)
grok_s = time.perf_counter() - t


def dirs(item):
    return {(x["sector"], x["direction"]) for x in item["ai"]["sectors"]}


agree = top_agree = 0
for a, b in zip(jev["items"], grok["items"]):
    ja, gb = dirs(a), dirs(b)
    agree += len(ja & gb) / max(1, len(ja | gb))
    js = a["ai"]["sectors"][:1]
    if js and (js[0]["sector"], js[0]["direction"]) in gb:
        top_agree += 1
    print("-", a["title"][:70], "| jev:", sorted(ja)[:3], "| grok:", sorted(gb)[:3])
print(json.dumps({"n": len(rows), "jev_total_s": round(jev_s, 2), "grok_total_s": round(grok_s, 2),
                  "jaccard_mean": round(agree / max(1, len(rows)), 2),
                  "jev_top_in_grok": f"{top_agree}/{len(rows)}",
                  "jev_model": jev["model"], "grok_model": grok["model"]}, indent=1))
