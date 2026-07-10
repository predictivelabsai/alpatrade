# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
flutter pub get

# Generate mocks and serialization code (required before tests run)
dart run build_runner build --delete-conflicting-outputs

# Run all tests (370 tests)
flutter test

# Run a single test file
flutter test test/unit/models/chat_test.dart

# Run tests in a directory
flutter test test/widget/

# Static analysis (errors only — infos/warnings are non-blocking)
flutter analyze --no-fatal-infos --no-fatal-warnings

# Format code
dart format lib/ test/

# Run the app (default API: https://carhero.chat/api/v1)
flutter run

# Run with custom API URL
flutter run --dart-define=API_BASE_URL=http://localhost:8000/api/v1

# Generate app icons (after changing assets/images/app_icon.png)
dart run flutter_launcher_icons
```

## Architecture

Flutter mobile client for the CarHero web app (at `../carhero/`). Connects to a FastAPI backend at `/api/v1` for all data. No local database — all state comes from the API or in-memory Riverpod providers.

### State & Data Flow

**Riverpod 3** is the state management layer. The provider dependency chain is:

```
authProvider (AsyncNotifier) → apiClientProvider (Dio + JWT interceptor) → *ServiceProviders → *ScreenProviders
connectivityProvider (StreamNotifier) → AppScaffold (offline banner)
```

- `authProvider` owns the JWT token lifecycle (login, register, restore from secure storage, logout)
- `apiClientProvider` creates a `Dio` instance that auto-attaches the Bearer token via interceptor and throws `UnauthorizedException` on 401
- Each feature has a service class (thin API wrapper) and a provider that holds UI state
- `chatProvider` is a `Notifier<ChatState>` that manages the SSE streaming state machine
- `connectivityProvider` monitors network via connectivity_plus and drives the offline banner

### Chat SSE Streaming

Chat uses **raw `http` package** (not Dio) because Dio doesn't support streaming POST responses well. The flow:

1. `ChatService.streamChat()` sends a POST to `/chat` with `Accept: text/event-stream`
2. Parses the SSE wire format (`event: <name>\ndata: <json>\n\n`) into a sealed `ChatEvent` hierarchy
3. `ChatNotifier` consumes the stream and transitions through: idle → add user message → streaming (accumulate tokens, track tool calls) → finalize assistant message → idle
4. 8 event types: `session`, `agent_route`, `token`, `tool_start`, `tool_end`, `artifact_show`, `done`, `error`

### Routing

**GoRouter** with auth-guarded routes. Public routes (`/`, `/about`, `/contact`, `/shared/:token`) bypass auth. Protected routes use a `ShellRoute` with `AppScaffold` (bottom nav bar + offline banner). Auth redirect is currently disabled for testing — re-enable in `app_router.dart` when auth token flow is finalized.

### i18n

12 languages via Flutter's built-in localization. ARB files in `lib/l10n/`, generated class is `L10n` (configured in `l10n.yaml`). Template is `app_en.arb`. Locale is stored in `localeProvider` and synced with the chat API's `lang` parameter.

### Theme

Single `AppTheme.light` in `config/theme.dart`. Uses a dark ink (#1A1A1A) + white palette with gray tones. Available grays: `gray50`, `gray100`, `gray200`, `gray400`, `gray500` (no gray300 or gray600). Material 3, Inter font family.

### Key Patterns

- **Models** are plain Dart classes with `fromJson`/`toJson` (no freezed codegen in use despite the dependency)
- **Services** are stateless API wrappers that take `ApiClient` and return typed models
- **Providers** use Riverpod 3 API: `Notifier`/`NotifierProvider` for mutable state, `FutureProvider` for async reads, `Provider` for derived/computed values. No `StateNotifier` or `StateProvider` (Riverpod 2 API removed).
- **Widget tests** that touch providers watching network-backed `FutureProvider`s (like `agentsProvider`) must override them to avoid pending timer failures
- The `Override` type from Riverpod is **not** exported from the main `flutter_riverpod` barrel in v3; avoid using it as a type annotation

## Testing

36 test files, 370 tests. Three layers:
- `test/unit/` — models (JSON round-trip), services (mocked Dio via `@GenerateMocks`), utils
- `test/widget/` — individual widget rendering and interaction (10 files)
- `test/integration/` — multi-widget flows using providers and router (7 files)

Service tests require generated mock files. Run `dart run build_runner build` before `flutter test` if mocks are missing.

## CI/CD

GitHub Actions CI (`.github/workflows/ci.yml`) runs on every push to main:
1. Analyze (format + static analysis)
2. Test (370 tests with coverage)
3. Build Android APK + AAB
4. Distribute APK to Firebase App Distribution (testers group)

Manual deploy: `.github/workflows/deploy-android.yml` (workflow_dispatch)

## Firebase & GCP

- **Firebase Project**: `carhero-mobile` (project number: 698790728504)
- **App ID**: `1:698790728504:android:9dfa8be9906dacc8b9a7cd`
- **Package**: `chat.carhero.carhero`
- **Service Account**: `firebase-app-dist@carhero-mobile.iam.gserviceaccount.com`
- **Google OAuth** (GCP project `finespresso`):
  - Web Client ID: `76656799510-2996ug4uc4743ht74g4hsopn61g71ien.apps.googleusercontent.com`
  - Android Client ID: `76656799510-99q9f28jc0494atvgmjirppeuk2mfe8l.apps.googleusercontent.com`
