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
