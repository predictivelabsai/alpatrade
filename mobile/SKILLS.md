# SKILLS.md

Deployment, testing, and app store registration playbook for CarHero Mobile.

---

## Table of Contents

1. [Regression Testing](#1-regression-testing)
2. [Playwright E2E Testing](#2-playwright-e2e-testing)
3. [Flutter Platform Setup](#3-flutter-platform-setup)
4. [Google Play — Full Registration & Deployment](#4-google-play--full-registration--deployment)
5. [Apple App Store — Full Registration & Deployment](#5-apple-app-store--full-registration--deployment)
6. [TestFlight (iOS Beta)](#6-testflight-ios-beta)
7. [Google Play Internal & Closed Testing](#7-google-play-internal--closed-testing)
8. [Firebase App Distribution (Android)](#8-firebase-app-distribution-android)
9. [CI/CD Pipeline](#9-cicd-pipeline)
10. [Environment Configuration](#10-environment-configuration)
11. [Google Sign-In Credentials Setup](#11-google-sign-in-credentials-setup)
12. [Combinatorial Testing](#12-combinatorial-testing)

---

## 1. Regression Testing

### Unit Tests

All unit tests live under `test/unit/` and run without a device or emulator.

```bash
# Generate mocks first (required after model/service changes)
dart run build_runner build --delete-conflicting-outputs

# Run all unit tests
flutter test test/unit/

# Run a single test file
flutter test test/unit/models/chat_test.dart

# Run tests matching a name pattern
flutter test --name "SSE event parsing"

# Run with coverage
flutter test --coverage
lcov --remove coverage/lcov.info 'lib/l10n/*' -o coverage/filtered.info
genhtml coverage/filtered.info -o coverage/html
```

**Test categories:**

| Directory | What it covers |
|-----------|---------------|
| `test/unit/models/` | JSON round-trip, computed properties, null safety for all 11 model classes |
| `test/unit/services/` | Mocked Dio responses for auth and favorites, SSE parser for all 8 event types |
| `test/unit/utils/` | Price/mileage formatting, email/password/required validators |

### Widget Tests

Widget tests render individual components in isolation. No network calls — providers that trigger API calls must be overridden.

```bash
flutter test test/widget/

# Single widget test
flutter test test/widget/login_screen_test.dart
```

**Key pattern:** Widgets that watch network-backed providers (e.g., `agentsProvider`) need overrides in the test wrapper to prevent pending timer failures:

```dart
ProviderScope(
  overrides: [
    agentsProvider.overrideWith((ref) async => <AgentOut>[]),
  ],
  child: MaterialApp(home: Scaffold(body: widgetUnderTest)),
)
```

### Integration Tests (in-process)

Tests under `test/integration/` exercise multi-widget flows (auth, chat state machine, favorites CRUD, garage + TCO, market map filters) using real providers with mocked data. These still run via `flutter test` (no device needed).

```bash
flutter test test/integration/
```

### On-Device Integration Tests

For full device integration tests, create files under `integration_test/` (top-level directory, not `test/`). These run on a real device or emulator.

```bash
# Create the directory and a test file
mkdir -p integration_test

# Run on a connected device
flutter test integration_test/app_test.dart

# Run on a specific device
flutter test integration_test/ -d <device-id>
```

**Template for on-device tests:**

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:carhero/main.dart' as app;

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('full login and chat flow', (tester) async {
    app.main();
    await tester.pumpAndSettle();

    // Navigate to login
    await tester.tap(find.text('Sign In'));
    await tester.pumpAndSettle();

    // Fill credentials and submit
    await tester.enterText(find.byType(TextFormField).first, 'test@test.com');
    await tester.enterText(find.byType(TextFormField).last, 'password123');
    await tester.tap(find.text('Sign In'));
    await tester.pumpAndSettle();

    // Verify chat screen loaded
    expect(find.text('CarHero AI Advisor'), findsOneWidget);
  });
}
```

### Adding New Tests: Checklist

1. **New model** → add `test/unit/models/<name>_test.dart` with `fromJson` round-trip, computed properties, null/optional field handling
2. **New service** → add `test/unit/services/<name>_test.dart`, annotate with `@GenerateMocks([ApiClient])`, run `dart run build_runner build`
3. **New screen/widget** → add `test/widget/<name>_test.dart`, override any async providers
4. **New user flow** → add `test/integration/<name>_flow_test.dart` for the state machine logic

---

## 2. Playwright E2E Testing

Playwright tests run against the **companion web app** (`../carhero/`) but can also validate the API contract the mobile app depends on.

### Setup

```bash
npm init -y
npm install -D @playwright/test
npx playwright install
```

### API Contract Tests

Create `e2e/api-contract.spec.ts` to verify every endpoint the mobile app calls:

```typescript
import { test, expect } from '@playwright/test';

const BASE = process.env.API_BASE_URL || 'https://carhero.chat/api/v1';

test.describe('API contract for mobile app', () => {
  let token: string;

  test.beforeAll(async ({ request }) => {
    const res = await request.post(`${BASE}/auth/login`, {
      data: { email: process.env.TEST_EMAIL, password: process.env.TEST_PASSWORD },
    });
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    token = body.token;
  });

  test('GET /agents returns array with expected shape', async ({ request }) => {
    const res = await request.get(`${BASE}/agents`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(res.ok()).toBeTruthy();
    const agents = await res.json();
    expect(agents.length).toBeGreaterThan(0);
    expect(agents[0]).toHaveProperty('slug');
    expect(agents[0]).toHaveProperty('name');
    expect(agents[0]).toHaveProperty('example_prompts');
  });

  test('GET /sessions returns array', async ({ request }) => {
    const res = await request.get(`${BASE}/sessions`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(res.ok()).toBeTruthy();
  });

  test('GET /favorites returns array', async ({ request }) => {
    const res = await request.get(`${BASE}/favorites`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(res.ok()).toBeTruthy();
  });

  test('GET /garage returns array', async ({ request }) => {
    const res = await request.get(`${BASE}/garage`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(res.ok()).toBeTruthy();
  });

  test('GET /market-map/filters returns filter options', async ({ request }) => {
    const res = await request.get(`${BASE}/market-map/filters`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(res.ok()).toBeTruthy();
    const filters = await res.json();
    expect(filters).toHaveProperty('countries');
    expect(filters).toHaveProperty('makes');
  });

  test('POST /chat returns SSE stream', async ({ request }) => {
    const res = await request.post(`${BASE}/chat`, {
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'text/event-stream',
      },
      data: { message: 'Hello', lang: 'en' },
    });
    expect(res.status()).toBe(200);
  });
});
```

### Running Playwright Tests

```bash
# Run all Playwright tests
npx playwright test

# Run against staging
API_BASE_URL=https://staging.carhero.chat/api/v1 npx playwright test

# Run a specific test file
npx playwright test e2e/api-contract.spec.ts

# Run with headed browser (for web app UI tests)
npx playwright test --headed

# Generate HTML report
npx playwright test --reporter=html
npx playwright show-report
```

### Playwright Config

Create `playwright.config.ts`:

```typescript
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: 1,
  use: {
    baseURL: process.env.API_BASE_URL || 'https://carhero.chat/api/v1',
  },
  reporter: [['html', { open: 'never' }]],
});
```

---

## 3. Flutter Platform Setup

Before building for iOS or Android, generate the platform directories:

```bash
# Generate both platforms
flutter create --org chat.carhero --project-name carhero .

# Or generate one at a time
flutter create --platforms=android --org chat.carhero --project-name carhero .
flutter create --platforms=ios --org chat.carhero --project-name carhero .
```

This creates `android/` and `ios/` directories with the bundle ID `chat.carhero.carhero`.

### Verify Platform Builds

```bash
# List available devices
flutter devices

# Build Android APK (debug)
flutter build apk --debug

# Build Android App Bundle (release)
flutter build appbundle --release

# Build iOS (requires macOS + Xcode)
flutter build ios --release --no-codesign

# Build iOS IPA for distribution
flutter build ipa --release
```

---

## 4. Google Play — Full Registration & Deployment

### Step 1: Create a Google Play Developer Account

1. Go to [play.google.com/console/signup](https://play.google.com/console/signup)
2. Sign in with the Google account that will own the app (ideally a company account, not personal)
3. Accept the Developer Distribution Agreement
4. Pay the one-time $25 registration fee
5. Complete identity verification:
   - **Organization**: Provide business name, address, website, DUNS number (if applicable), business email
   - **Individual**: Government-issued ID, address
6. Verification takes 2-7 business days

### Step 2: Create the App Listing

1. Google Play Console → **Create app**
2. Fill in:
   - **App name**: CarHero
   - **Default language**: English (United States)
   - **App or game**: App
   - **Free or paid**: Free
3. Accept declarations (policies, export laws, US content ratings)

### Step 3: Complete Store Listing

Required before any release:

- **Short description** (80 chars): "AI-powered European premium car search & valuation"
- **Full description** (4000 chars): Feature overview, supported languages, agent capabilities
- **Screenshots**: At least 2 phone screenshots (16:9 or 9:16, 320–3840px per side)
  ```bash
  # Take screenshots from emulator
  flutter screenshot --out=screenshots/home.png
  ```
- **Feature graphic**: 1024×500 PNG
- **App icon**: 512×512 PNG (32-bit, no alpha)
- **Category**: Auto & Vehicles
- **Contact email**: Required
- **Privacy policy URL**: Required (host at carhero.chat/privacy)

### Step 4: Content Rating

1. Go to **Policy and programs → App content → Content rating**
2. Complete the IARC questionnaire (takes ~5 minutes)
3. CarHero likely rates "Everyone" — no violence, gambling, user-generated content

### Step 5: Target Audience & Data Safety

1. **Target audience**: 18+ (financial/automotive decisions)
2. **Data safety form**: Declare what data is collected:
   - Email address (account creation)
   - Name (profile)
   - Search history (chat sessions)
   - Location (country preference, not GPS)
   - Device identifiers (crash reporting, if added)

### Step 6: Configure Signing

```bash
# Generate upload key
keytool -genkey -v -keystore ~/upload-keystore.jks \
  -storetype JKS -keyalg RSA -keysize 2048 -validity 10000 \
  -alias upload

# Create android/key.properties (DO NOT COMMIT)
cat > android/key.properties << 'EOF'
storePassword=<password>
keyPassword=<password>
keyAlias=upload
storeFile=/home/julian/upload-keystore.jks
EOF

# Add to android/.gitignore
echo "key.properties" >> android/.gitignore
```

Update `android/app/build.gradle` to reference the keystore:

```groovy
def keystoreProperties = new Properties()
def keystorePropertiesFile = rootProject.file('key.properties')
if (keystorePropertiesFile.exists()) {
    keystoreProperties.load(new FileInputStream(keystorePropertiesFile))
}

android {
    signingConfigs {
        release {
            keyAlias keystoreProperties['keyAlias']
            keyPassword keystoreProperties['keyPassword']
            storeFile keystoreProperties['storeFile'] ? file(keystoreProperties['storeFile']) : null
            storePassword keystoreProperties['storePassword']
        }
    }
    buildTypes {
        release {
            signingConfig signingConfigs.release
        }
    }
}
```

### Step 7: Build & Upload

```bash
# Build release App Bundle
flutter build appbundle --release \
  --dart-define=API_BASE_URL=https://carhero.chat/api/v1

# Output: build/app/outputs/bundle/release/app-release.aab
```

Upload `app-release.aab` via Google Play Console → **Release → Production** (or Internal/Closed testing first).

### Step 8: Review & Launch

- Google review takes 1-3 days for new apps (can be up to 7 days)
- Address any policy violations flagged during review
- Once approved, click **Start rollout to Production**

---

## 5. Apple App Store — Full Registration & Deployment

### Step 1: Enroll in the Apple Developer Program

1. Go to [developer.apple.com/programs/enroll](https://developer.apple.com/programs/enroll)
2. Sign in with an Apple ID (create one if needed)
3. Choose enrollment type:
   - **Individual** ($99/year): Personal name on App Store
   - **Organization** ($99/year): Company name, requires D-U-N-S Number
4. For Organization enrollment:
   - Apply for a [D-U-N-S Number](https://developer.apple.com/support/D-U-N-S/) (free, takes 5-14 business days)
   - The enrollee must have legal authority to bind the organization
5. Complete enrollment and pay the annual fee
6. Apple review takes 24-48 hours

### Step 2: Create App ID & Certificates

In [developer.apple.com/account](https://developer.apple.com/account):

1. **Certificates, Identifiers & Profiles → Identifiers → +**
   - Type: App IDs
   - Platform: iOS
   - Description: CarHero
   - Bundle ID (Explicit): `chat.carhero.carhero`
   - Enable capabilities: Sign In with Apple (if using), Push Notifications (if needed)

2. **Certificates → +**
   - Create an **Apple Distribution** certificate
   - Download and install in Keychain Access

3. **Profiles → +**
   - Type: App Store Distribution
   - Select the App ID and Distribution certificate
   - Download and install

### Step 3: Create the App in App Store Connect

1. Go to [appstoreconnect.apple.com](https://appstoreconnect.apple.com)
2. **My Apps → +** → New App
3. Fill in:
   - **Platforms**: iOS
   - **Name**: CarHero
   - **Primary language**: English (U.S.)
   - **Bundle ID**: Select `chat.carhero.carhero`
   - **SKU**: `carhero-ios-001`
   - **User access**: Full Access

### Step 4: Complete App Store Listing

- **Subtitle** (30 chars): "AI Car Advisor for Europe"
- **Promotional text** (170 chars): Can be updated without a new build
- **Description**: Feature overview
- **Keywords** (100 chars): "cars,marketplace,valuation,premium,european,AI,compare,BMW,Mercedes,Audi,Porsche"
- **Screenshots**: Required per device size
  - 6.7" (iPhone 15 Pro Max): 1290×2796
  - 6.1" (iPhone 15 Pro): 1179×2556
  - iPad Pro 12.9": 2048×2732 (if supporting iPad)
- **App icon**: Provided by Flutter's asset pipeline (1024×1024, no alpha, no transparency)
- **Category**: Auto & Vehicles (primary), Lifestyle (secondary)
- **Privacy policy URL**: Required
- **Support URL**: Required
- **Age rating**: Complete the questionnaire (likely 4+ or 12+)

### Step 5: Configure Xcode Signing

```bash
# Open Xcode workspace
open ios/Runner.xcworkspace
```

In Xcode:
1. Select the **Runner** target
2. **Signing & Capabilities** tab
3. Set **Team** to your Apple Developer team
4. Set **Bundle Identifier** to `chat.carhero.carhero`
5. Ensure **Automatically manage signing** is checked (simplest for initial setup)

### Step 6: Build & Upload

```bash
# Build the IPA
flutter build ipa --release \
  --dart-define=API_BASE_URL=https://carhero.chat/api/v1

# Output: build/ios/ipa/carhero.ipa
```

Upload via one of:
- **Xcode → Product → Archive → Distribute App** (most common)
- **Transporter app** (drag and drop the .ipa)
- **xcrun altool** (CLI):
  ```bash
  xcrun altool --upload-app --type ios \
    --file build/ios/ipa/carhero.ipa \
    --apiKey <key_id> --apiIssuer <issuer_id>
  ```

### Step 7: App Review

- Apple review takes 24-48 hours (can be up to a week for first submission)
- Common rejection reasons for new apps:
  - Missing login credentials for reviewers (provide a demo account in App Review Information)
  - Privacy policy doesn't match data collection
  - App requires a server that's not reachable (ensure API is up during review)
  - Screenshots don't match actual app behavior
- If rejected, read the resolution center notes, fix, and resubmit

---

## 6. TestFlight (iOS Beta)

TestFlight allows up to 10,000 external testers without App Store review (internal testing) or with a lightweight review (external testing).

### Internal Testing (up to 100 testers)

1. Upload a build via Xcode or Transporter (see Step 6 above)
2. App Store Connect → **TestFlight** tab
3. Wait for build processing (5-30 minutes)
4. **Internal Testing → +** → Create a group
5. Add testers by Apple ID email
6. Testers receive an email → install TestFlight app → accept invite → install build

### External Testing (up to 10,000 testers)

1. Upload a build
2. TestFlight → **External Testing → +** → Create a group
3. Fill in **What to Test** and **Test Information**
4. Add testers by email or share a public link
5. First external build requires **Beta App Review** (24-48 hours)
6. Subsequent builds to the same group auto-approve unless major changes

### Beta Build Workflow

```bash
# Bump build number (required for each TestFlight upload)
# In pubspec.yaml: version: 1.0.0+2 (increment the +N part)

# Build
flutter build ipa --release \
  --dart-define=API_BASE_URL=https://carhero.chat/api/v1

# Upload
xcrun altool --upload-app --type ios \
  --file build/ios/ipa/carhero.ipa \
  --apiKey <key_id> --apiIssuer <issuer_id>
```

**Tip:** Each upload must have a unique build number (`+N` in pubspec.yaml version). Increment it for every TestFlight push.

---

## 7. Google Play Internal & Closed Testing

### Internal Testing (up to 100 testers)

Fastest path — no Google review required.

1. Google Play Console → **Testing → Internal testing**
2. **Create new release**
3. Upload the `.aab` file
4. Add a release name and notes
5. **Save → Review release → Start rollout**
6. **Testers tab** → Create an email list (Google accounts only)
7. Share the opt-in link with testers
8. Testers click the link → accept → install from Play Store

### Closed Testing (alpha/beta, unlimited testers)

Requires Google review (1-3 days for first review).

1. Google Play Console → **Testing → Closed testing**
2. Create a track (e.g., "Beta")
3. Upload `.aab`, add release notes
4. Add tester email lists or Google Groups
5. Submit for review

### Build & Upload

```bash
# Build release bundle
flutter build appbundle --release \
  --dart-define=API_BASE_URL=https://carhero.chat/api/v1

# Upload via Google Play Console UI
# Or use the Google Play Developer API / Fastlane
```

---

## 8. Firebase App Distribution (Android)

Alternative to Play Console testing — works with APKs, no Google Play listing needed. Good for ad-hoc testing before Play Store setup is complete.

### Setup

```bash
# Install Firebase CLI
curl -sL https://firebase.tools | bash
firebase login

# Install the Flutter plugin (or use CLI directly)
firebase apps:create ANDROID chat.carhero.carhero --project=<firebase-project-id>
```

### Distribute a Build

```bash
# Build APK (not AAB — Firebase App Distribution uses APKs)
flutter build apk --release \
  --dart-define=API_BASE_URL=https://carhero.chat/api/v1

# Distribute
firebase appdistribution:distribute build/app/outputs/flutter-apk/app-release.apk \
  --app <firebase-app-id> \
  --groups "internal-testers" \
  --release-notes "Build $(date +%Y%m%d): <description>"
```

### Add Testers

```bash
# Add testers by email
firebase appdistribution:testers:add user@example.com --project=<project-id>

# Create a group
firebase appdistribution:group:create internal-testers --project=<project-id>
```

Testers receive an email → install the Firebase App Tester app → install the build.

---

## 9. CI/CD Pipeline

### GitHub Actions: `.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  analyze-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: subosito/flutter-action@v2
        with:
          flutter-version: '3.44.1'
          channel: 'stable'

      - run: flutter pub get
      - run: dart run build_runner build --delete-conflicting-outputs
      - run: flutter analyze
      - run: dart format --set-exit-if-changed lib/ test/
      - run: flutter test --coverage

      - uses: codecov/codecov-action@v4
        with:
          files: coverage/lcov.info

  build-android:
    needs: analyze-and-test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: subosito/flutter-action@v2
        with:
          flutter-version: '3.44.1'

      - run: flutter pub get
      - run: flutter build apk --release --dart-define=API_BASE_URL=https://carhero.chat/api/v1

      - uses: actions/upload-artifact@v4
        with:
          name: android-apk
          path: build/app/outputs/flutter-apk/app-release.apk

  build-ios:
    needs: analyze-and-test
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4
      - uses: subosito/flutter-action@v2
        with:
          flutter-version: '3.44.1'

      - run: flutter pub get
      - run: flutter build ios --release --no-codesign

  playwright-api:
    needs: analyze-and-test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20

      - run: npm ci
      - run: npx playwright install --with-deps
      - run: npx playwright test
        env:
          API_BASE_URL: ${{ vars.API_BASE_URL }}
          TEST_EMAIL: ${{ secrets.TEST_EMAIL }}
          TEST_PASSWORD: ${{ secrets.TEST_PASSWORD }}
```

### Required GitHub Secrets

| Secret | Description |
|--------|-------------|
| `TEST_EMAIL` | Test account email for Playwright API tests |
| `TEST_PASSWORD` | Test account password |

### Required GitHub Variables

| Variable | Description |
|----------|-------------|
| `API_BASE_URL` | API URL for Playwright (default: production) |

---

## 10. Environment Configuration

The app uses `--dart-define` for compile-time configuration:

```bash
# Development (local backend)
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000/api/v1   # Android emulator
flutter run --dart-define=API_BASE_URL=http://localhost:8000/api/v1   # iOS simulator

# Staging
flutter run --dart-define=API_BASE_URL=https://staging.carhero.chat/api/v1

# Production (default — no flag needed)
flutter run
```

**Android emulator note:** Use `10.0.2.2` instead of `localhost` to reach the host machine.

---

## 11. Google Sign-In Credentials Setup

Google Sign-In is declared in `pubspec.yaml` (`google_sign_in: ^7.2.0`) but currently stubbed out with a TODO. To activate it:

### Google Cloud Console Setup

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a project (or use existing) → Enable the **Google Sign-In API**
3. **APIs & Services → Credentials → Create Credentials → OAuth client ID**

### Android OAuth Client

1. Application type: **Android**
2. Package name: `chat.carhero.carhero`
3. SHA-1 fingerprint:
   ```bash
   # Debug key
   keytool -list -v -keystore ~/.android/debug.keystore -alias androiddebugkey -storepass android

   # Release key
   keytool -list -v -keystore ~/upload-keystore.jks -alias upload
   ```
4. Download the client ID
5. No extra config file needed for `google_sign_in` v7 on Android — it reads from the Google Play signing config

### iOS OAuth Client

1. Application type: **iOS**
2. Bundle ID: `chat.carhero.carhero`
3. Download `GoogleService-Info.plist`
4. Place it in `ios/Runner/GoogleService-Info.plist`
5. Add the reversed client ID as a URL scheme in `ios/Runner/Info.plist`:
   ```xml
   <key>CFBundleURLTypes</key>
   <array>
     <dict>
       <key>CFBundleURLSchemes</key>
       <array>
         <string>com.googleusercontent.apps.YOUR_CLIENT_ID</string>
       </array>
     </dict>
   </array>
   ```

### Web OAuth Client (for backend token exchange)

1. Application type: **Web application**
2. Authorized redirect URIs: `https://carhero.chat/api/v1/auth/google/callback`
3. Use this client ID/secret in the FastAPI backend's `/auth/google` endpoint

### Consent Screen

1. **APIs & Services → OAuth consent screen**
2. User type: **External**
3. Fill in app name ("CarHero"), support email, developer contact
4. Scopes: `email`, `profile`, `openid`
5. Test users: Add team emails while in "Testing" status
6. Submit for **verification** before production launch (required if >100 users)
   - Verification requires: privacy policy, homepage, a short video demonstrating the OAuth flow
   - Takes 2-6 weeks

---

## Quick Reference: Release Checklist

### Pre-release

- [ ] All `flutter test` pass (202+ tests)
- [ ] `flutter analyze` shows no errors
- [ ] `dart format --set-exit-if-changed lib/ test/` passes
- [ ] Playwright API contract tests pass against production
- [ ] Version bumped in `pubspec.yaml` (both version and build number)
- [ ] Release notes written

### Android Release

- [ ] `flutter build appbundle --release` succeeds
- [ ] Upload to Google Play Console (internal → closed → production)
- [ ] Verify install on physical device from Play Store

### iOS Release

- [ ] `flutter build ipa --release` succeeds
- [ ] Upload via Xcode/Transporter
- [ ] TestFlight internal test on physical device
- [ ] Submit for App Store review with demo account credentials

---

## 12. Combinatorial Testing

Data-driven test suite that covers models, screens, navigation, and live API endpoints. Test data lives in CSV files; results are written as JSON for CI/audit.

### Test Data (test-data/)

| File | Rows | Coverage |
|------|------|----------|
| `api_endpoints.csv` | 40 | All GET/POST/DELETE endpoints with expected status codes |
| `models_test_data.csv` | 40 | JSON field parsing for 8 model classes |
| `navigation_paths.csv` | 20 | Route-to-route transitions via sidebar |

### Running Flutter Combinatorial Tests (80 tests)

```bash
# Runs 30 model + 30 screen + 20 navigation tests
# Writes results to test-results/flutter-combinatorial.json
flutter test test/combinatorial/combinatorial_test.dart
```

Test breakdown:
- **M01-M30 (Models):** fromJson parsing, null handling, type coercion, round-trip for DailyScanStats, PriceComparison, PriceDrop, DailyScanData, AgentOut, SessionSummary, ChatMessage, Favorite, GarageCar, MarketFilters, UserProfile, SavedSearch, AnalyticsResult
- **S01-S30 (Screens):** Widget rendering for all 8 screens (Chat, Market Map, Favorites, Saved Searches, Garage, Analytics, Profile, Daily Scan), verifying key UI elements, sections, and data display
- **N01-N20 (Navigation):** GoRouter transitions between all screen pairs, sidebar link visibility, round-trip navigation, full circuit through all screens

### Running API Tests (40 tests)

```bash
# Calls live API at https://carhero.chat/api/v1
# Writes results to test-results/api-results.json
bash test-data/run_api_tests.sh

# Override API base URL
API_BASE_URL=http://localhost:8000/api/v1 bash test-data/run_api_tests.sh
```

Covers: health, agents, sessions, auth (401/422), daily-scan, market-map (6 chart types + filters), listings search (6 filter combos), favorites/garage/profile (auth-gated), analytics, contact form validation.

### Test Results (test-results/)

| File | Source | Format |
|------|--------|--------|
| `flutter-combinatorial.json` | Flutter test harness | `{test_run, results: [{id, category, description, result, error?}]}` |
| `api-results.json` | bash curl script | `{test_run, api_base, results: [{id, method, path, expected, actual, result, description}]}` |

### Adding New Test Cases

1. Add rows to the relevant CSV in `test-data/`
2. For model/screen tests, add corresponding `test()` or `testWidgets()` in `test/combinatorial/combinatorial_test.dart`
3. For API tests, just add rows to `api_endpoints.csv` — the bash script picks them up automatically
4. Run and verify: `flutter test test/combinatorial/ && bash test-data/run_api_tests.sh`
