# LLM judge provider: TypeSafe jev (with Grok fallback)

`LLM_JUDGE_PROVIDER=typesafe` sends **judging, decisioning and classification** calls to TypeSafe's **jev** System One model. Default `grok` = behaviour unchanged. Code: `engine/ai/judge.py`.

## TypeSafe / jev in brief
- `POST https://api.typesafe.ai/v1/systemone`, `Authorization: Bearer $TYPESAFE_API_KEY` (set in the HP `.env`).
- Body: `{model, state, questions}`. Each question is `choice` (pick one of ≤255 options), `score` (2–10 ordered levels) or `noul` (yes/no probability). The response is typed `answers` with calibrated probabilities/confidence, plus `usage`.
- Model `jev-latest` → `jev-1.13.0` (override with `TYPESAFE_MODEL`, and pin it once you've tuned thresholds). Text input only, 64k tokens per request.
- Price: **$0.042 per 1M input tokens, output free**. Limits: 100K tok/s, 80 req/s.
- jev doesn't generate text, so it can't hallucinate outside the options. It's no use for prose, extraction, translation or tool use.

## Behaviour
`judge.decide(state, questions, fallback=…)` calls jev when the flag is on and the key is present. Any error (missing key, HTTP 4xx/5xx/529, timeout, malformed answer, missing answer key) logs a warning and runs the Grok `fallback()`, so a TypeSafe outage only costs latency.

## Inventory of Grok / xAI call sites

| Call site | What it does | Kind | Decision |
|---|---|---|---|
| `engine/research/news_intel.py::analyze_with_ai` (`/research/news` "Analyze with AI") | Per-headline sector direction (up/down/neutral), expected move, confidence | **Classification** | **→ jev** (one typed call per headline, in parallel; per-sector `choice` + move `score`). The one-line thesis is dropped (blank) on the jev path. |
| `engine/autonomy/graph.py` promote note | "Which 1–3 paper strategies are most robust?" | **Judging / ranking** | **→ jev** (`score` weak/fair/robust per strategy, top 3 in the note). The deterministic PromotionBar stays the gate. |
| `engine/autonomy/graph.py` scout / backtest / refit notes (`reason()`) | Free-text rationale, binary-event risk (needs world knowledge) | Generative | Grok |
| `news_scheduler/xai.py::metadata` | Issuer/ticker extraction, translation, `company_type`, `event` | Mostly extraction/translation | Grok. Candidate: `event` (choice from `allowed_events`) and `company_type` (public/private) could move to jev in a second pass, but the Grok call is still needed for the translation, so there's no saving yet. |
| `news_scheduler/xai.py::reason` | 40-word explanation | Generative | Grok |
| `engine/premarket_analysis.py::generate` | Web-search premarket narrative (responses API + tools) | Generative + search | Grok |
| `engine/reporting/advisor.py` (LLM explanation) | Advisor narrative. Severity is already deterministic (`classify_evidence`) | Generative | Grok |
| `engine/ai/*`, `engine/web/ph_chat.py`, `agui_app.py`, `engine/research/alpha_agents.py` | Chat agents, tools, research agents | Generative / agentic | Grok |
| `utils/market_research_util.py::_news_xai`, `utils/research_agent.py`, `utils/alpaca_agent.py`, `scripts/cwt_pipeline.py` | Headline generation, legacy agents, offline pipeline | Generative | Grok |
| `engine/config.py` key check, `engine/voice.py` realtime | Key ping / voice | n/a | Grok |

## Benchmark (2026-10-12, 10 live headlines, `scripts/bench_jev.py`)

| | jev-1.13.0 | grok-4.5 |
|---|---|---|
| Wall time for 10 headlines | **0.73 s** (parallel; ~0.26 s per call) | 29.1 s (one batched call) |
| Top jev sector/direction also in Grok's set | 8/10 | — |
| Mean Jaccard of (sector, direction) sets | 0.54 | — |

Where they disagreed: Grok often adds extra low-signal sectors, some marked "neutral" (which counts against Jaccard), and on "Bloom Energy vs Vertiv" Grok tagged Industrials/Tech/Utilities while jev tagged Energy. On the clear-cut headlines (energy ceasefire, NAND/AI memory, Prime Day, energy profitability) they agreed exactly. That's good enough for a sector heat board, and the probabilities are calibrated.

## Cost estimate
- **News analysis:** Grok ≈ 1.5k input + 2.5k output tokens per 10-headline click ≈ **$0.008** at the platform's configured $1.25/$2.50 per M (more on grok-4.5). jev ≈ 10 × ~550 input tokens ≈ **$0.00023**, a saving of **~97%** per analysis and ~40× faster.
- **Autonomy promote note:** Grok ≈ 400 in + 150 out ≈ $0.0009 per run; jev ≈ $0.00003, ~97% cheaper.
- In absolute terms the saving is small (these are low-volume paths: an on-click analysis and one autonomy run per cycle), roughly a few dollars a month at current traffic. The bigger wins are latency (30 s → <1 s on `/research/news`) and the typed, bounded answers. The large Grok spend (chat agents, premarket narrative, news enrichment) is generative and stays on Grok.

## Enabling
Set `LLM_JUDGE_PROVIDER=typesafe` and `TYPESAFE_API_KEY` in the environment (Coolify for prod). Not enabled in prod by this PR.
