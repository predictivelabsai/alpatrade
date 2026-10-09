# Chat With Traders → backtested Leaderboard strategies

Pipeline: `scripts/cwt_pipeline.py catalogue | transcribe | extract | backtest | publish`
(`--episode N` or `--all`; `all --episode N` runs every step). Engine:
`engine/backtest/breakout.py`. Data: `data/cwt/episodes.csv`, `alpatrade.cwt_episodes`
(`sql/43_cwt_episodes.sql`), per-episode folders `data/cwt/<slug>/`.

## Catalogue (2026-10-10)
- Source: chatwithtraders.com (sitemap → each episode page's embedded API state; the
  `/episode-by-topic-stocks` page only server-renders 9 of its 135 episodes, the rest load via
  "Load More").
- **135 episodes tagged `stocks`** (of 337 total), 152.3 h of audio; mp3 for all (megaphone).
- YouTube: **124 matched** on the Chat With Traders channel via `yt-dlp ytsearch` (141.4 h),
  scored by guest surname + episode number + subtitle words, one video per episode (repeat
  guests de-duplicated). Matches on old episodes are heuristic: check the caption header. yt-dlp must be ≥ 2026.x (installed
  in `.venv`; the system 2024.04 build can't download captions any more).

## Transcription options (135 episodes, 152.3 h; 124 on YouTube = 141.4 h; 11 audio-only = 10.9 h)

| Option | Cost / audio hour | Whole catalogue | Speed (measured on the HP where noted) | Quality |
|---|---|---|---|---|
| (a) YouTube auto-captions (yt-dlp) | $0 | **$0** for 124 eps; 11 need a fallback | ~5–20 s / episode (measured) → < 30 min total | Lower-case, no punctuation/speakers, ~10–15% WER on names/tickers; timestamps exact. Good enough for rule extraction |
| (b) faster-whisper on the HP (i5-8500 6c, CPU int8) | $0 (electricity) | **$0** | small: **5.7× realtime** (measured) → ~27 h for 152 h; medium: **2.2×** → ~69 h. GPU (Quadro P1000 4 GB, sm_61) unusable as-is: no CUDA 12 cuBLAS installed; even working it would be ~small-model only | Punctuated, better than captions (medium ≈ captions + punctuation; small slightly worse on names) |
| (c) ElevenLabs Scribe v2 | ~$0.22–0.40 (plan-dependent list price) | ~$35–60 | ~1–2 min / episode (API) | Best-in-class WER, diarisation, word timestamps. Keys found (2 `.env` files) are on the **free tier with 9,922/10,000 credits used** → needs a paid plan |
| (d1) OpenAI whisper-1 / gpt-4o-transcribe | $0.36 | ~$55 | ~1–3 min / episode; 25 MB upload cap → chunk mp3s | Very good; gpt-4o-mini-transcribe $0.18/h → ~$27. `OPENAI_API_KEY` present in many `.env`s (not validated) |
| (d2) Deepgram Nova-3 | ~$0.26 | ~$40 | < 1 min / episode | Very good, diarisation. **No key found** |
| (d3) AssemblyAI Universal | ~$0.15–0.27 | ~$23–41 | ~1 min / episode | Very good, diarisation. **No key found** |
| (e) Gemini 2.5 Flash on the YouTube URL + strategy prompt | **$0.14** (measured: 395k tokens for an 80-min episode = 322k video + 73k audio @ $0.30/$1.00 per M + ~6.5k out @ $2.50/M ≈ $0.19) | ~$20 for the 124 YouTube eps (+ ~$1.3 to upload the 11 audio-only mp3s) | **57 s / episode** (measured) | Gives a strategy summary with quotes, not a transcript. Timestamps were **~10 min off** vs the captions in the pilot → don't trust its timestamps. Needs `mediaResolution=LOW` to stay under 1M tokens |

Extraction (Grok `grok-4.3`, JSON mode, ~17k input tokens / episode): ~12 s and a few cents per
episode. Backtest: ~7.5 min / episode with the 24-config grid (~25 s without, `--no-grid`) on
cached bars.

**Recommendation for the bulk run:** (a) YouTube captions for the 124 YouTube episodes + (b)
faster-whisper *small* on the HP CPU for the other 11 (~2 h), all free; extract with
Grok; optionally (e) Gemini (~$20) as a second, independent strategy read to cross-check the
Grok spec. Pay for Scribe/Deepgram only if verbatim quotes must be publication-grade.

## Pilot: ep. 212 Kristjan Kullamägi – Breakouts, Home Runs & Exponential Returns (2021-02-26)
Artefacts in `data/cwt/212-kristjan-kullamagi-breakouts-home-runs-exponential-returns/`:
`transcript.txt` (captions), `gemini_strategy.md`, `spec.json` (Grok), `backtest.json`,
`skill.md`, `equity_full.csv`, `trades_full.csv`. Results are in the skill.md and on
`/strategies/{id}` (kind = backtest).

## Bulk run results (2026-10-10, v0.33.3)
135 `stocks` episodes → **16 testable** (one strategy per trader + template; all 16 published),
**119 not testable** (intraday, options/futures, discretionary, no concrete rules, macro), 0
skipped (< 10 trades). Stan Gluzman (ep. 171, 211) is overridden to `intraday_only` and his row
is unpublished. Universe: today's S&P 500 (survivorship-biased), Alpaca SIP daily bars, cash
only, 10 bps per side. Test = 2022-01-03 → 2026-10-09 slice of the full 2016-01-04 run.

| Trader | Template | Test ann. % | SPY ann. % | Alpha ann. % | Sharpe / SPY | Max DD % | Trades (test) | Full ann. % |
|---|---|---|---|---|---|---|---|---|
| Vincent Bruzzese | relative_strength | 37.5 | 12.3 | +25.2 | 1.17 / 0.76 | -32.3 | 731 | 19.1 |
| Ross Haber | relative_strength | 29.8 | 12.3 | +17.5 | 1.33 / 0.76 | -17.4 | 1534 | 19.2 |
| Rob Hanna | dip | 19.5 | 12.3 | +7.1 | 0.70 / 0.76 | -32.1 | 1930 | 16.3 |
| Tom Basso | trend_ma | 9.4 | 12.3 | -3.0 | 0.68 / 0.76 | -16.6 | 957 | 8.5 |
| Ivaylo Ivanhoff | breakout | 7.0 | 12.3 | -5.3 | 0.39 / 0.76 | -37.9 | 1051 | -7.1 |
| Kristjan Kullamägi | breakout | -0.8 | 12.3 | -13.2 | -0.43 / 0.76 | -4.3 | 52 | -1.1 |
| Dan Shapiro | breakout | -3.4 | 12.3 | -15.8 | -0.02 / 0.76 | -45.6 | 940 | -6.7 |
| Julian Komar | breakout | -3.6 | 12.3 | -15.9 | -0.35 / 0.76 | -20.1 | 241 | -1.2 |
| Jon Boorman | breakout | -4.3 | 12.3 | -16.6 | -0.23 / 0.76 | -35.7 | 656 | -5.5 |
| Christian Carreon | breakout | -4.9 | 12.3 | -17.2 | -0.46 / 0.76 | -29.8 | 205 | -5.4 |
| Kenny Glick | breakout | -6.0 | 12.3 | -18.3 | -1.38 / 0.76 | -25.6 | 574 | -6.3 |
| Mark Ritchie II | breakout | -8.1 | 12.3 | -20.4 | -0.36 / 0.76 | -52.2 | 711 | -13.6 |
| George, @RollyTrader | breakout | -9.3 | 12.3 | -21.7 | -1.00 / 0.76 | -38.9 | 942 | -5.7 |
| Nick Radge | breakout | -10.6 | 12.3 | -23.0 | -0.93 / 0.76 | -44.4 | 2386 | -8.5 |
| Marsten Parker | breakout | -14.0 | 12.3 | -26.4 | -1.17 / 0.76 | -52.3 | 960 | -15.8 |
| John Walsh | breakout | -16.8 | 12.3 | -29.1 | -0.82 / 0.76 | -66.2 | 1061 | -15.6 |

Sanity fixes in this run (see `docs/change_log.md` v0.33.3): LLM `0` = not stated → template
default (was clamped to the lower bound), feasible breakout windows (`mom_days ≥ cons_days + 20`),
rotation at most weekly with a 2× rank buffer, manual classification overrides, unpublish of
stale rows, publish without burning sequence ids. Every breakout group is negative vs SPY on
large caps; the low-of-day stop + SMA trail is a coarse daily stand-in for intraday entries.
Marsten Parker's method (volume thrust, 5% target / 7% stop, 3–4 day hold) is only loosely
approximated by the breakout template.
