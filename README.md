# AlpaTrade Mobile

Flutter mobile client for [AlpaTrade](https://alpatrade.chat) — an AI trading research and **paper-trading** assistant powered by Alpaca Markets and x.ai. Chat (text or voice) with a trading agent that can read your paper positions and P&L, pull market news and movers, run backtests, and place paper orders.

> Paper trading is simulated. This is not investment advice.

## Features

- **AI Chat** — Plain-English trading assistant over real-time SSE streaming (`POST /v2/chat`). Ask about positions, account, P&L, news, quotes, backtests; place paper orders with a 2-step confirm.
- **Voice** — Hands-free realtime voice via the x.ai realtime agent (`wss://alpatrade.chat/ws/voice`, PCM16 @ 24 kHz, server-side VAD). Mic streams up, the agent speaks back, transcript shows inline.
- **Portfolio** — Open paper positions with live P&L and an account market-value summary.
- **Activity** — Executed trades (paper/backtest) and backtest/paper runs.
- **Strategies** — Top strategy ranking plus per-run reports with a cumulative P&L chart and per-symbol breakdown (fl_chart).
- **More** — Market news & movers, background agent status/logs, language, and settings.
- **Private account access** — Sign in or create an account to view positions,
  activity, strategies, agent status, and place paper orders. Public chat and
  market news remain available before sign-in.
- **Offline detection** — Banner when connectivity drops.

## Tech Stack

| Layer | Choice |
|-------|--------|
| Framework | Flutter 3.44+ / Dart 3.12+ |
| State management | Riverpod 3 |
| Routing | GoRouter 17 (bottom-nav shell) |
| HTTP | Dio (REST) + http (SSE streaming) |
| Voice | record (mic PCM16) + flutter_pcm_sound (playback) + web_socket_channel |
| Charts | fl_chart |
| i18n | Flutter Localizations (ARB) |
| CI/CD | GitHub Actions + Firebase App Distribution (finespresso) |

## API

Base URLs (override with `--dart-define`):

- `API_BASE_URL` — `https://api.alpatrade.chat` (REST + SSE chat)
- `VOICE_WS_URL` — `wss://alpatrade.chat/ws/voice` (realtime voice)

Contract lives in [`docs/mobile-api.md`](docs/mobile-api.md); machine-readable spec in [`docs/swagger.json`](docs/swagger.json).

## Develop

```bash
flutter pub get
flutter run                                   # default: api.alpatrade.chat
flutter run --dart-define=API_BASE_URL=http://localhost:8000
flutter analyze --no-fatal-infos --no-fatal-warnings
flutter test
dart format lib/ test/
```

## CI/CD

`.github/workflows/ci.yml` runs analyze → test → build APK/AAB → distribute the APK to the **testers** group on Firebase App Distribution (project `finespresso`). Manual runs: `deploy-android.yml` (workflow_dispatch). Required repo secrets: `FIREBASE_APP_ID`, `FIREBASE_SERVICE_ACCOUNT`, and (for signed release) `KEYSTORE_BASE64`, `KEY_ALIAS`, `KEY_PASSWORD`, `STORE_PASSWORD`.
