# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
flutter pub get

# Run all tests
flutter test

# Run a single test file
flutter test test/unit/models/chat_test.dart

# Static analysis (errors only — infos/warnings are non-blocking)
flutter analyze --no-fatal-infos --no-fatal-warnings

# Format code
dart format lib/ test/

# Run the app (defaults: API https://api.alpatrade.chat, voice wss://alpatrade.chat/ws/voice)
flutter run
flutter run --dart-define=API_BASE_URL=http://localhost:8000 --dart-define=VOICE_WS_URL=ws://localhost:5003/ws/voice

# Generate app icons (after changing assets/images/app_icon.png)
dart run flutter_launcher_icons
```

## Architecture

Flutter mobile client for **AlpaTrade** (backend at `../alpatrade/`, api_app.py + agui_app.py). It talks to the live API at `https://api.alpatrade.chat` (REST + SSE chat) and `wss://alpatrade.chat/ws/voice` (realtime voice). No local database — all state comes from the API or in-memory Riverpod providers. **No auth**: the API is anonymous and serves a shared demo paper-trading account.

### State & Data Flow (Riverpod 3)

```
apiClientProvider (anonymous Dio)     → *ServiceProviders → *Providers (FutureProvider) → screens
chatProvider (Notifier<ChatState>)    → ChatService (raw http SSE) → /v2/chat
voiceProvider (Notifier<VoiceUiState>)→ VoiceService (WebSocket + mic PCM + PCM playback)
connectivityProvider (StreamNotifier) → AppScaffold (offline banner)
```

- `apiClientProvider` (lib/providers/api_provider.dart) is a single shared anonymous `ApiClient` (Dio). No JWT.
- Each feature has a stateless service (thin API wrapper taking `ApiClient`) and a `FutureProvider` holding its async read.
- `chatProvider` manages the SSE streaming state machine and keeps one `thread_id` per conversation (so the 2-step paper-order confirm works).
- `voiceProvider` drives the realtime voice session and appends transcript lines into the chat message list.

### Chat SSE Streaming — `POST /v2/chat`

`ChatService.streamChat()` uses the raw `http` package (Dio can't stream POST bodies). Body: `{msg, thread_id?}`, `Accept: text/event-stream`. Events parsed into a sealed `ChatEvent`: `session` (echoes thread id, a **String**), `agent_route` (`command`|`ai`), `token` (concatenate `text`), `tool_start`/`tool_end`, `error`, `done`. There are no `artifact` events.

### Voice — `wss://alpatrade.chat/ws/voice`

Server-side proxy to x.ai's realtime agent (PCM16 mono @ 24 kHz, server VAD). `VoiceService` (lib/services/voice_service.dart): captures mic via `record` (`AudioEncoder.pcm16bits`), streams `{type:"audio", audio:<base64>}` up the WebSocket, and plays returned `audio` frames via `flutter_pcm_sound`. Inbound events: `ready`, `speech_started/stopped`, `user_transcript`, `assistant_delta/done`, `tool`, `audio`, `done`, `error`. The x.ai key stays server-side. Requires `RECORD_AUDIO` (declared in the manifest).

### Routing

**GoRouter** with a `ShellRoute` + `AppScaffold` (bottom nav + offline banner). Five tabs: `/chat`, `/portfolio`, `/activity`, `/strategies`, `/more`. `/` redirects to `/chat`. No auth guard (anonymous API). Sub-screens under More/Strategies are opened via `Navigator.push`, not the router.

### Feature modules

| Tab | Endpoints | Files |
|---|---|---|
| Chat | `POST /v2/chat`, `wss .../ws/voice` | chat_*, voice_* |
| Portfolio | `GET /v2/positions` (+ client-side totals) | position.dart, positions_* |
| Activity | `GET /v2/trades?trade_type=`, `GET /v2/runs` | trade.dart, run.dart, activity_* |
| Strategies | `GET /v2/top`, `/v2/report`, `/v2/pnl/{id}` | strategy.dart, pnl.dart, strategies_*, strategy_detail_screen |
| More | `GET /news`, `/movers` (return `{result: markdown}`), `GET /v2/status` | market_*, news/movers/status/settings screens |

`GET /news` and `GET /movers` return `{"result": "<markdown>"}` — render the markdown directly. `/v2/top` is a JSON array. Full contract: `docs/mobile-api.md`; spec: `docs/swagger.json`.

### Theme

`AppTheme.light` (lib/config/theme.dart) mirrors the web app palette: cream `#F7F6F1` surfaces, forest-green accent `#1F5D43`, ink `#14231B`. Inter for text, JetBrains Mono (`AppTheme.monoFont`) for numbers/tickers. P&L coloring via `AppTheme.pnlColor(v)` / `gain` / `loss`. Formatting via `Fmt.*` (lib/utils/formatters.dart): `usd`, `signedUsd`, `pct(v, signed:)`, `shares`, `titleize`, date helpers.

### Key patterns

- Models are plain Dart classes with `fromJson` (no codegen). Null-safe casts: `(j['x'] as num?)?.toDouble()`.
- Riverpod 3 API only: `Notifier`/`NotifierProvider`, `FutureProvider`(`.family`), `Provider`. No `StateNotifier`/`StateProvider`. Don't annotate variables with the `Override` type (not exported from the v3 barrel).
- Prefer `.withValues(alpha:)` over the deprecated `.withOpacity`.

## Testing

Unit tests under `test/unit/` cover models (JSON round-trip: chat/position/trade), SSE parsing, and formatters. Run `flutter test`.

## CI/CD

`.github/workflows/ci.yml` on push to main: analyze (format + static analysis) → test → build APK + AAB (`--dart-define=API_BASE_URL=https://api.alpatrade.chat`) → distribute APK to the **testers** group via Firebase App Distribution. Manual: `deploy-android.yml` (workflow_dispatch). The app bundles **no** Firebase SDK; App Distribution runs entirely in CI via the `wzieba/Firebase-Distribution-Github-Action`.

## Firebase & GCP

- **Firebase project**: `finespresso` (App Distribution only).
- **Android package / app id**: `chat.alpatrade.app`.
- Required repo secrets: `FIREBASE_APP_ID`, `FIREBASE_SERVICE_ACCOUNT` (service-account JSON), plus release-signing secrets `KEYSTORE_BASE64`, `KEY_ALIAS`, `KEY_PASSWORD`, `STORE_PASSWORD`.
