# CarHero Mobile

Flutter mobile app for [CarHero](https://carhero.chat) — an AI-powered European premium car marketplace. Search, compare, and value 50,000+ premium car listings across 8+ European marketplaces using 5 specialist AI agents.

## Features

- **AI Chat** — Conversational interface with 5 specialist agents (search, market analyst, valuator, comparator, advisor) via real-time SSE streaming
- **Market Map** — Interactive treemap, price trends, geographic heatmaps, value scatter plots, and price index charts (fl_chart)
- **Favorites** — Save listings with notes, track price changes
- **My Garage** — Track owned vehicles with live market valuations and TCO breakdowns
- **Saved Searches** — Persist search filters, get notifications on new matches
- **Analytics** — Natural language to SQL queries with auto-generated charts
- **12 Languages** — English, Estonian, German, French, Swedish, Latvian, Norwegian, Danish, Polish, Dutch, Finnish, Lithuanian
- **Auth** — Email/password + Google Sign-In with JWT
- **Offline Detection** — Banner shown when network connectivity drops

## Tech Stack

| Layer | Choice |
|-------|--------|
| Framework | Flutter 3.44+ / Dart 3.12+ |
| State management | Riverpod 3 |
| Routing | GoRouter 17 |
| HTTP | Dio (REST) + http (SSE streaming) |
| Charts | fl_chart |
| Auth | JWT Bearer + Google Sign-In v7 |
| i18n | Flutter Localizations (ARB) |
| Storage | flutter_secure_storage + shared_preferences |
| Testing | flutter_test + mockito |
| CI/CD | GitHub Actions + Firebase App Distribution |

## Project Structure

```
lib/
  main.dart                  # Entry point
  app.dart                   # MaterialApp.router + ProviderScope

  config/
    api_config.dart          # Base URL, timeouts (configurable via --dart-define)
    theme.dart               # Material 3 theme (colors, typography)
    constants.dart           # Brand list, country codes, fuel types

  models/                    # Data classes (11 files)
    auth.dart, chat.dart, listing.dart, favorite.dart, garage.dart,
    session.dart, profile.dart, market_map.dart, analytics.dart,
    agent.dart, saved_search.dart

  services/                  # API layer (13 files)
    api_client.dart          # Dio client + JWT interceptor
    chat_service.dart        # SSE streaming via POST
    auth_service.dart, listing_service.dart, favorite_service.dart,
    garage_service.dart, market_map_service.dart, analytics_service.dart,
    profile_service.dart, session_service.dart, saved_search_service.dart,
    agent_service.dart, contact_service.dart

  providers/                 # Riverpod state (12 files)
    auth_provider.dart       # AsyncNotifier for auth state
    chat_provider.dart       # Manages SSE stream, messages, artifacts
    connectivity_provider.dart # Network status monitoring
    locale_provider.dart, market_map_provider.dart, analytics_provider.dart,
    favorite_provider.dart, garage_provider.dart, session_provider.dart,
    profile_provider.dart, saved_search_provider.dart, agent_provider.dart

  router/
    app_router.dart          # GoRouter with auth redirect

  screens/                   # 11 screen modules
  widgets/                   # Reusable components (ErrorView, EmptyState)
  utils/                     # Formatters, validators, secure storage
  l10n/                      # 12 ARB files + generated localizations
```

## Setup

### Prerequisites

- Flutter SDK >= 3.44.0
- Dart SDK >= 3.12.0
- Android Studio / Xcode for emulators

### Install & Run

```bash
flutter pub get
dart run build_runner build --delete-conflicting-outputs
flutter run
```

### Configure API URL

Default API: `https://carhero.chat/api/v1`

Override at build time:

```bash
flutter run --dart-define=API_BASE_URL=http://localhost:8000/api/v1
```

### Google Sign-In

Google OAuth is configured via `--dart-define`:

```bash
flutter run --dart-define=GOOGLE_SERVER_CLIENT_ID=your-web-client-id.apps.googleusercontent.com
```

Default Web Client ID (from GCP project `finespresso`): `76656799510-2996ug4uc4743ht74g4hsopn61g71ien.apps.googleusercontent.com`

Android OAuth Client ID: `76656799510-99q9f28jc0494atvgmjirppeuk2mfe8l.apps.googleusercontent.com` (validated via SHA-1 + package name)

### Run Tests

```bash
# Generate mocks first
dart run build_runner build --delete-conflicting-outputs

# Run all tests (294 tests)
flutter test

# Run by category
flutter test test/unit/
flutter test test/widget/
flutter test test/integration/
```

## Test Suite

35 test files, 294 tests across three layers:

| Category | Files | Coverage |
|----------|-------|----------|
| Unit — Models | 11 | JSON round-trip, computed properties, null handling |
| Unit — Services | 3 | Auth, favorites (mocked Dio), SSE parser (all 8 event types) |
| Unit — Utils | 2 | Price/mileage formatting, email/password validation |
| Widget | 10 | Login, listing card, chat bubbles, input bar, tool cards, welcome, profile, about, contact, home |
| Integration | 7 | Auth flow, chat streaming, favorites CRUD, garage + TCO, market map, navigation, app launch |

## CI/CD

### GitHub Actions (`ci.yml`)

On every push to `main`:
1. **Analyze** — `dart format --set-exit-if-changed` + `flutter analyze`
2. **Test** — `flutter test --coverage` (294 tests)
3. **Build** — `flutter build apk --release` + `flutter build appbundle --release`
4. **Distribute** — APK uploaded to Firebase App Distribution (testers group)

### Firebase App Distribution

- **Firebase Project**: `carhero-mobile` (GCP project ID)
- **App ID**: `1:698790728504:android:9dfa8be9906dacc8b9a7cd`
- **Package**: `chat.carhero.carhero`
- **Testers group**: `testers`

To install on device:
1. Install **Firebase App Tester** from Google Play Store
2. Sign in with your Google account (must be in testers group)
3. Download the latest build

### GitHub Secrets Required

| Secret | Purpose |
|--------|---------|
| `FIREBASE_SERVICE_ACCOUNT` | Service account JSON for Firebase App Distribution uploads |
| `FIREBASE_APP_ID` | Firebase Android app ID |
| `KEYSTORE_BASE64` | Base64-encoded release keystore (optional, uses debug signing if absent) |
| `KEY_ALIAS` | Keystore key alias |
| `KEY_PASSWORD` | Keystore key password |
| `STORE_PASSWORD` | Keystore store password |

## GCP / Firebase Configuration

### GCP Projects

| Project | ID | Purpose |
|---------|-----|---------|
| CarHero Mobile | `carhero-mobile` | Firebase, App Distribution, Crashlytics |
| Finespresso | `finespresso` | Google OAuth client IDs (shared with web app) |

### Google OAuth Setup

- **Web Client ID** (used as `serverClientId` in Flutter): `76656799510-2996ug4uc4743ht74g4hsopn61g71ien.apps.googleusercontent.com`
- **Android Client ID**: `76656799510-99q9f28jc0494atvgmjirppeuk2mfe8l.apps.googleusercontent.com`
  - Package: `chat.carhero.carhero`
  - SHA-1 (debug): from `~/.android/debug.keystore`

### Firebase Service Account

Service account `firebase-app-dist@carhero-mobile.iam.gserviceaccount.com` with `roles/firebaseappdistro.admin` role. Key stored as `FIREBASE_SERVICE_ACCOUNT` GitHub secret.

## Supported Languages

`en` `et` `de` `fr` `sv` `lv` `no` `da` `pl` `nl` `fi` `lt`

~90 translation keys per language, sourced from the CarHero web app's i18n catalog.

## Backend API

The app connects to the CarHero FastAPI backend at `/api/v1`. Key endpoint groups:

- **Auth** — `/auth/login`, `/auth/register`, `/auth/google`, `/auth/me`
- **Chat** — `/sessions`, `/chat` (SSE), `/agents`
- **Favorites** — `/favorites` CRUD
- **Garage** — `/garage` CRUD + `/valuation` + `/tco`
- **Market Map** — `/market-map/treemap|trends|geo|value-map|price-index`
- **Analytics** — `/analytics/query`
- **Profile** — `/user/profile`
- **Shared** — `/shared/{token}` (public, no auth)

## License

Proprietary. All rights reserved.
