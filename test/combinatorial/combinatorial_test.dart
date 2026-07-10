import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'package:carhero/config/theme.dart';
import 'package:carhero/models/auth.dart';
import 'package:carhero/models/agent.dart';
import 'package:carhero/models/session.dart';
import 'package:carhero/models/chat.dart';
import 'package:carhero/models/favorite.dart';
import 'package:carhero/models/garage.dart';
import 'package:carhero/models/market_map.dart';
import 'package:carhero/models/profile.dart';
import 'package:carhero/models/daily_scan.dart';
import 'package:carhero/models/analytics.dart';
import 'package:carhero/models/saved_search.dart';
import 'package:carhero/providers/auth_provider.dart';
import 'package:carhero/providers/agent_provider.dart';
import 'package:carhero/providers/session_provider.dart';
import 'package:carhero/providers/favorite_provider.dart';
import 'package:carhero/providers/garage_provider.dart';
import 'package:carhero/providers/market_map_provider.dart';
import 'package:carhero/providers/profile_provider.dart';
import 'package:carhero/providers/daily_scan_provider.dart';
import 'package:carhero/screens/chat_screen.dart';
import 'package:carhero/screens/market_map_screen.dart';
import 'package:carhero/screens/favorites_screen.dart';
import 'package:carhero/screens/saved_searches_screen.dart';
import 'package:carhero/screens/garage_screen.dart';
import 'package:carhero/screens/analytics_screen.dart';
import 'package:carhero/screens/profile_screen.dart';
import 'package:carhero/screens/daily_scan_screen.dart';
import 'package:carhero/screens/app_scaffold.dart';

// ---------------------------------------------------------------------------
// Test result tracking
// ---------------------------------------------------------------------------
class TestResult {
  final String id;
  final String category;
  final String description;
  final String result;
  final String? error;

  TestResult({
    required this.id,
    required this.category,
    required this.description,
    required this.result,
    this.error,
  });

  Map<String, dynamic> toJson() => {
    'id': id,
    'category': category,
    'description': description,
    'result': result,
    if (error != null) 'error': error,
  };
}

final List<TestResult> _allResults = [];

void _record(String id, String cat, String desc, bool pass, [String? err]) {
  _allResults.add(
    TestResult(
      id: id,
      category: cat,
      description: desc,
      result: pass ? 'pass' : 'fail',
      error: err,
    ),
  );
}

// ---------------------------------------------------------------------------
// Fake notifiers
// ---------------------------------------------------------------------------
class _FakeAuthNotifier extends AuthNotifier {
  @override
  Future<AuthResponse?> build() async => const AuthResponse(
    token: 'test-token',
    email: 'test@example.com',
    name: 'Test User',
    userId: 1,
  );
}

class _FakeGuestAuthNotifier extends AuthNotifier {
  @override
  Future<AuthResponse?> build() async => null;
}

class _FakeFavoritesNotifier extends FavoritesNotifier {
  @override
  Future<List<Favorite>> build() async => <Favorite>[];
}

class _FakeGarageNotifier extends GarageNotifier {
  @override
  Future<List<GarageCar>> build() async => <GarageCar>[];
}

class _FakeProfileNotifier extends ProfileNotifier {
  @override
  Future<UserProfile?> build() async => const UserProfile(
    name: 'Test User',
    email: 'test@example.com',
    currency: 'EUR',
    language: 'en',
  );
}

// ---------------------------------------------------------------------------
// Test app builders
// ---------------------------------------------------------------------------
final _testAgents = [
  const AgentOut(
    slug: 'search',
    name: 'Car Search',
    category: 'search',
    icon: '🔍',
    oneLiner: 'Find your dream car',
    prefix: '/search',
    examplePrompts: ['Find me a BMW M3'],
  ),
  const AgentOut(
    slug: 'analyst',
    name: 'Market Analyst',
    category: 'analysis',
    icon: '📊',
    oneLiner: 'Analyze market trends',
    prefix: '/analyst',
    examplePrompts: ['Show market trends'],
  ),
];

final _testSessions = [
  SessionSummary(
    id: 1,
    title: 'Find BMW M3',
    agentSlug: 'search',
    updatedAt: '2026-06-01',
  ),
  SessionSummary(
    id: 2,
    title: 'Market analysis',
    agentSlug: 'analyst',
    updatedAt: '2026-06-02',
  ),
];

late GoRouter _router;

Widget _buildApp({
  String initialLocation = '/chat',
  bool guest = false,
  List<SessionSummary>? sessions,
}) {
  _router = GoRouter(
    initialLocation: initialLocation,
    routes: [
      ShellRoute(
        builder: (context, state, child) => AppScaffold(child: child),
        routes: [
          GoRoute(
            path: '/chat',
            pageBuilder: (c, s) => const NoTransitionPage(child: ChatScreen()),
          ),
          GoRoute(
            path: '/market-map',
            pageBuilder: (c, s) =>
                const NoTransitionPage(child: MarketMapScreen()),
          ),
          GoRoute(
            path: '/favorites',
            pageBuilder: (c, s) =>
                const NoTransitionPage(child: FavoritesScreen()),
          ),
          GoRoute(
            path: '/saved-searches',
            pageBuilder: (c, s) =>
                const NoTransitionPage(child: SavedSearchesScreen()),
          ),
          GoRoute(
            path: '/garage',
            pageBuilder: (c, s) =>
                const NoTransitionPage(child: GarageScreen()),
          ),
          GoRoute(
            path: '/analytics',
            pageBuilder: (c, s) =>
                const NoTransitionPage(child: AnalyticsScreen()),
          ),
          GoRoute(
            path: '/profile',
            pageBuilder: (c, s) =>
                const NoTransitionPage(child: ProfileScreen()),
          ),
          GoRoute(
            path: '/daily-scan',
            pageBuilder: (c, s) =>
                const NoTransitionPage(child: DailyScanScreen()),
          ),
        ],
      ),
    ],
  );

  return ProviderScope(
    overrides: [
      authProvider.overrideWith(
        () => guest ? _FakeGuestAuthNotifier() : _FakeAuthNotifier(),
      ),
      agentsProvider.overrideWith((ref) => _testAgents),
      sessionsProvider.overrideWith((ref) => sessions ?? _testSessions),
      favoritesProvider.overrideWith(() => _FakeFavoritesNotifier()),
      garageProvider.overrideWith(() => _FakeGarageNotifier()),
      profileProvider.overrideWith(() => _FakeProfileNotifier()),
      dailyScanProvider.overrideWith(
        (ref) => DailyScanData(
          stats: const DailyScanStats(
            totalActive: 50000,
            freshCount: 12000,
            newCount: 350,
            providersScraped: 8,
            countriesCovered: 6,
            lastScrape: '2026-06-01T10:00:00',
          ),
          comparisons: [
            const PriceComparison(
              make: 'BMW',
              model: 'M3',
              year: 2020,
              listingCount: 25,
              sourceCount: 4,
              minPrice: 45000,
              maxPrice: 62000,
              avgPrice: 53000,
              savingsEur: 17000,
              savingsPct: 27.4,
              cheapPrice: 45000,
              cheapCountry: 'Germany',
              cheapProvider: 'AutoScout24',
              cheapKm: 35000,
              expensivePrice: 62000,
              expensiveCountry: 'Netherlands',
              expensiveProvider: 'Marktplaats',
            ),
            const PriceComparison(
              make: 'Porsche',
              model: '911',
              year: 2019,
              listingCount: 15,
              sourceCount: 3,
              savingsEur: 12000,
              savingsPct: 15.0,
              cheapPrice: 68000,
              cheapCountry: 'Germany',
              expensivePrice: 80000,
              expensiveCountry: 'Sweden',
            ),
          ],
          priceDrops: [
            const PriceDrop(
              make: 'Audi',
              model: 'RS6',
              year: 2021,
              priceEur: 89000,
              oldPrice: 97000,
              dropEur: 8000,
              dropPct: 8.2,
              country: 'Germany',
              provider: 'Mobile.de',
            ),
          ],
        ),
      ),
      marketFiltersProvider.overrideWith(
        (ref) => const MarketFilters(
          countries: ['Germany', 'France'],
          makes: ['BMW', 'Audi'],
          fuelTypes: ['Petrol', 'Diesel'],
        ),
      ),
      treemapProvider.overrideWith((ref) => <TreemapItem>[]),
      trendsProvider.overrideWith((ref) => <TrendItem>[]),
      geoProvider.overrideWith((ref) => <GeoItem>[]),
      valueMapProvider.overrideWith((ref) => <ValueMapItem>[]),
      priceIndexProvider.overrideWith((ref) => <PriceIndexItem>[]),
    ],
    child: MaterialApp.router(theme: AppTheme.light, routerConfig: _router),
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
void main() {
  // ========================================================================
  // Category 1: Model serialization (40 tests)
  // ========================================================================
  group('M: Model serialization', () {
    test('M01: DailyScanStats.fromJson full', () {
      final s = DailyScanStats.fromJson({
        'total_active': 50000,
        'fresh_count': 12000,
        'new_count': 350,
        'providers_scraped': 8,
        'countries_covered': 6,
        'last_scrape': '2026-06-01T10:00:00',
      });
      final pass =
          s.totalActive == 50000 &&
          s.freshCount == 12000 &&
          s.newCount == 350 &&
          s.providersScraped == 8 &&
          s.countriesCovered == 6 &&
          s.lastScrape == '2026-06-01T10:00:00';
      _record('M01', 'model', 'DailyScanStats full parse', pass);
      expect(pass, isTrue);
    });

    test('M02: DailyScanStats.fromJson empty', () {
      final s = DailyScanStats.fromJson({});
      final pass =
          s.totalActive == 0 && s.freshCount == 0 && s.lastScrape == null;
      _record('M02', 'model', 'DailyScanStats empty parse', pass);
      expect(pass, isTrue);
    });

    test('M03: DailyScanStats.fromJson nulls', () {
      final s = DailyScanStats.fromJson({
        'total_active': null,
        'fresh_count': null,
      });
      final pass = s.totalActive == 0 && s.freshCount == 0;
      _record('M03', 'model', 'DailyScanStats null fields', pass);
      expect(pass, isTrue);
    });

    test('M04: PriceComparison.fromJson full', () {
      final c = PriceComparison.fromJson({
        'make': 'BMW',
        'model': 'M3',
        'year': 2020,
        'listing_count': 25,
        'source_count': 4,
        'min_price': 45000,
        'max_price': 62000,
        'avg_price': 53000,
        'savings_eur': 17000.0,
        'savings_pct': 27.4,
        'cheap_price': 45000.0,
        'cheap_country': 'Germany',
        'cheap_provider': 'AutoScout24',
        'cheap_url': 'https://example.com',
        'cheap_km': 35000,
        'expensive_price': 62000.0,
        'expensive_country': 'Netherlands',
        'expensive_provider': 'Marktplaats',
        'expensive_url': 'https://example2.com',
      });
      final pass =
          c.make == 'BMW' &&
          c.model == 'M3' &&
          c.year == 2020 &&
          c.savingsEur == 17000.0 &&
          c.cheapCountry == 'Germany' &&
          c.cheapKm == 35000 &&
          c.expensiveCountry == 'Netherlands';
      _record('M04', 'model', 'PriceComparison full parse', pass);
      expect(pass, isTrue);
    });

    test('M05: PriceComparison.fromJson empty', () {
      final c = PriceComparison.fromJson({});
      final pass = c.make == '' && c.model == '' && c.year == 0;
      _record('M05', 'model', 'PriceComparison empty parse', pass);
      expect(pass, isTrue);
    });

    test('M06: PriceDrop.fromJson full', () {
      final d = PriceDrop.fromJson({
        'make': 'Porsche',
        'model': '911',
        'variant': 'Carrera',
        'year': 2019,
        'mileage_km': 25000,
        'price_eur': 85000.0,
        'old_price': 95000.0,
        'drop_eur': 10000.0,
        'drop_pct': 10.5,
        'country': 'Netherlands',
        'provider': 'AutoTrack',
        'fuel_type': 'Petrol',
        'source_url': 'https://example.com/911',
      });
      final pass =
          d.make == 'Porsche' &&
          d.variant == 'Carrera' &&
          d.dropPct == 10.5 &&
          d.mileageKm == 25000;
      _record('M06', 'model', 'PriceDrop full parse', pass);
      expect(pass, isTrue);
    });

    test('M07: PriceDrop.fromJson nulls', () {
      final d = PriceDrop.fromJson({
        'make': 'BMW',
        'model': 'X5',
        'year': 2021,
      });
      final pass =
          d.variant == null && d.mileageKm == null && d.sourceUrl == null;
      _record('M07', 'model', 'PriceDrop null optional fields', pass);
      expect(pass, isTrue);
    });

    test('M08: DailyScanData.fromJson full structure', () {
      final data = DailyScanData.fromJson({
        'stats': {'total_active': 100, 'fresh_count': 50},
        'comparisons': [
          {'make': 'BMW', 'model': 'M3', 'year': 2020},
        ],
        'price_drops': [
          {'make': 'Audi', 'model': 'A4', 'year': 2019},
        ],
      });
      final pass =
          data.stats.totalActive == 100 &&
          data.comparisons.length == 1 &&
          data.priceDrops.length == 1;
      _record('M08', 'model', 'DailyScanData full parse', pass);
      expect(pass, isTrue);
    });

    test('M09: DailyScanData.fromJson empty lists', () {
      final data = DailyScanData.fromJson({'stats': {}});
      final pass = data.comparisons.isEmpty && data.priceDrops.isEmpty;
      _record('M09', 'model', 'DailyScanData empty lists', pass);
      expect(pass, isTrue);
    });

    test('M10: AgentOut constructor', () {
      const a = AgentOut(
        slug: 'search',
        name: 'Search',
        category: 'search',
        icon: '🔍',
        oneLiner: 'Find cars',
        prefix: '/search',
        examplePrompts: ['Find BMW'],
      );
      final pass = a.slug == 'search' && a.examplePrompts.length == 1;
      _record('M10', 'model', 'AgentOut constructor', pass);
      expect(pass, isTrue);
    });

    test('M11: SessionSummary fields', () {
      final s = SessionSummary(
        id: 42,
        title: 'Test session',
        agentSlug: 'search',
        updatedAt: '2026-06-01',
      );
      final pass = s.id == 42 && s.title == 'Test session';
      _record('M11', 'model', 'SessionSummary fields', pass);
      expect(pass, isTrue);
    });

    test('M12: ChatMessage construction', () {
      final m = ChatMessage(role: 'user', content: 'Hello');
      final pass =
          m.role == 'user' && m.content == 'Hello' && m.artifacts.isEmpty;
      _record('M12', 'model', 'ChatMessage construction', pass);
      expect(pass, isTrue);
    });

    test('M13: ChatMessage with artifacts', () {
      final m = ChatMessage(
        role: 'assistant',
        content: 'Here are results',
        artifacts: [
          Artifact(kind: 'listing', data: {'make': 'BMW'}),
        ],
      );
      final pass = m.artifacts.length == 1 && m.artifacts[0].kind == 'listing';
      _record('M13', 'model', 'ChatMessage with artifacts', pass);
      expect(pass, isTrue);
    });

    test('M14: ChatRequest toJson', () {
      final r = ChatRequest(message: 'Find BMW', sessionId: 5, lang: 'de');
      final j = r.toJson();
      final pass =
          j['message'] == 'Find BMW' &&
          j['session_id'] == 5 &&
          j['lang'] == 'de';
      _record('M14', 'model', 'ChatRequest toJson', pass);
      expect(pass, isTrue);
    });

    test('M15: ChatRequest toJson without session', () {
      final r = ChatRequest(message: 'Hello', lang: 'en');
      final j = r.toJson();
      final pass = j['message'] == 'Hello' && j['session_id'] == null;
      _record('M15', 'model', 'ChatRequest toJson no session', pass);
      expect(pass, isTrue);
    });

    test('M16: Favorite fields', () {
      const f = Favorite(
        id: 1,
        listingId: 100,
        make: 'Audi',
        model: 'A4',
        year: 2020,
        priceEur: 35000,
        priceAtSave: 36000,
        priceChange: -1000,
        country: 'Germany',
      );
      final pass = f.priceChange == -1000 && f.make == 'Audi';
      _record('M16', 'model', 'Favorite fields', pass);
      expect(pass, isTrue);
    });

    test('M17: GarageCar fields', () {
      const g = GarageCar(
        id: 1,
        make: 'Mercedes-Benz',
        model: 'C63',
        year: 2019,
      );
      final pass = g.make == 'Mercedes-Benz' && g.year == 2019;
      _record('M17', 'model', 'GarageCar fields', pass);
      expect(pass, isTrue);
    });

    test('M18: UserProfile defaults', () {
      const p = UserProfile(name: 'Test', email: 'test@test.com');
      final pass = p.currency == 'EUR' && p.language == 'en';
      _record('M18', 'model', 'UserProfile defaults', pass);
      expect(pass, isTrue);
    });

    test('M19: MarketFilters fromJson', () {
      const f = MarketFilters(
        countries: ['DE', 'FR'],
        makes: ['BMW'],
        fuelTypes: ['Petrol'],
      );
      final pass = f.countries.length == 2 && f.makes.length == 1;
      _record('M19', 'model', 'MarketFilters construction', pass);
      expect(pass, isTrue);
    });

    test('M20: PriceComparison numeric edge case - zero', () {
      final c = PriceComparison.fromJson({
        'make': 'Test',
        'model': 'Car',
        'year': 0,
        'savings_eur': 0,
        'savings_pct': 0,
      });
      final pass = c.savingsEur == 0 && c.savingsPct == 0;
      _record('M20', 'model', 'PriceComparison zero values', pass);
      expect(pass, isTrue);
    });

    test('M21: PriceComparison numeric edge case - negative', () {
      final c = PriceComparison.fromJson({
        'make': 'Test',
        'model': 'Car',
        'year': 2020,
        'savings_eur': -500,
      });
      final pass = c.savingsEur == -500;
      _record('M21', 'model', 'PriceComparison negative savings', pass);
      expect(pass, isTrue);
    });

    test('M22: PriceDrop large values', () {
      final d = PriceDrop.fromJson({
        'make': 'Bugatti',
        'model': 'Chiron',
        'year': 2022,
        'price_eur': 2500000.0,
        'old_price': 3000000.0,
        'drop_eur': 500000.0,
        'drop_pct': 16.67,
      });
      final pass = d.priceEur == 2500000.0 && d.dropEur == 500000.0;
      _record('M22', 'model', 'PriceDrop large values', pass);
      expect(pass, isTrue);
    });

    test('M23: DailyScanStats decimal coercion', () {
      final s = DailyScanStats.fromJson({
        'total_active': 1.0,
        'fresh_count': 2.5,
      });
      final pass = s.totalActive == 1 && s.freshCount == 2;
      _record('M23', 'model', 'DailyScanStats decimal to int', pass);
      expect(pass, isTrue);
    });

    test('M24: Multiple comparisons parse', () {
      final data = DailyScanData.fromJson({
        'stats': {},
        'comparisons': List.generate(
          50,
          (i) => {
            'make': 'Brand$i',
            'model': 'Model$i',
            'year': 2020 + (i % 5),
          },
        ),
        'price_drops': [],
      });
      final pass = data.comparisons.length == 50;
      _record('M24', 'model', 'Parse 50 comparisons', pass);
      expect(pass, isTrue);
    });

    test('M25: SavedSearch construction', () {
      const s = SavedSearch(
        id: 1,
        name: 'BMW under 50k',
        filters: {'make': 'BMW', 'max_price': '50000'},
        lastCount: 15,
        notifyEmail: true,
      );
      final pass = s.name == 'BMW under 50k' && s.lastCount == 15;
      _record('M25', 'model', 'SavedSearch fields', pass);
      expect(pass, isTrue);
    });

    test('M26: Artifact kinds', () {
      final a1 = Artifact(kind: 'listing', data: {});
      final a2 = Artifact(kind: 'listings', data: {'listings': []});
      final a3 = Artifact(kind: 'chart', data: {'type': 'bar'});
      final pass =
          a1.kind == 'listing' && a2.kind == 'listings' && a3.kind == 'chart';
      _record('M26', 'model', 'Artifact kind variants', pass);
      expect(pass, isTrue);
    });

    test('M27: ChatMessage tool calls', () {
      final m = ChatMessage(
        role: 'assistant',
        content: 'Searching...',
        toolCalls: [
          ToolCall(name: 'search_listings', args: {'make': 'BMW'}),
        ],
      );
      final pass =
          m.toolCalls.length == 1 && m.toolCalls[0].name == 'search_listings';
      _record('M27', 'model', 'ChatMessage with tool calls', pass);
      expect(pass, isTrue);
    });

    test('M28: AuthResponse fields', () {
      const a = AuthResponse(
        token: 'abc',
        email: 'a@b.com',
        name: 'A',
        userId: 1,
      );
      final pass = a.token == 'abc' && a.userId == 1;
      _record('M28', 'model', 'AuthResponse fields', pass);
      expect(pass, isTrue);
    });

    test('M29: PriceComparison all URL fields', () {
      final c = PriceComparison.fromJson({
        'make': 'Test',
        'model': 'Car',
        'year': 2020,
        'cheap_url': 'https://cheap.com',
        'expensive_url': 'https://expensive.com',
      });
      final pass =
          c.cheapUrl == 'https://cheap.com' &&
          c.expensiveUrl == 'https://expensive.com';
      _record('M29', 'model', 'PriceComparison URLs', pass);
      expect(pass, isTrue);
    });

    test('M30: DailyScanData.fromJson missing stats key', () {
      final data = DailyScanData.fromJson({});
      final pass = data.stats.totalActive == 0 && data.comparisons.isEmpty;
      _record('M30', 'model', 'DailyScanData missing stats', pass);
      expect(pass, isTrue);
    });
  });

  // ========================================================================
  // Category 2: Screen rendering (30 tests)
  // ========================================================================
  group('S: Screen rendering', () {
    testWidgets('S01: Chat screen renders title', (t) async {
      await t.pumpWidget(_buildApp());
      await t.pumpAndSettle();
      final pass = find
          .text('Kenri.ai · Personal Advisor')
          .evaluate()
          .isNotEmpty;
      _record('S01', 'screen', 'Chat screen title', pass);
      expect(pass, isTrue);
    });

    testWidgets('S02: Chat screen shows welcome', (t) async {
      await t.pumpWidget(_buildApp());
      await t.pumpAndSettle();
      final pass = find.text('Kenri.ai').evaluate().isNotEmpty;
      _record('S02', 'screen', 'Chat welcome message', pass);
      expect(pass, isTrue);
    });

    testWidgets('S03: Chat screen shows input bar', (t) async {
      await t.pumpWidget(_buildApp());
      await t.pumpAndSettle();
      final pass = find
          .text('Search for a car, compare models...')
          .evaluate()
          .isNotEmpty;
      _record('S03', 'screen', 'Chat input placeholder', pass);
      expect(pass, isTrue);
    });

    testWidgets('S04: Chat screen has menu button', (t) async {
      await t.pumpWidget(_buildApp());
      await t.pumpAndSettle();
      final pass = find.byIcon(Icons.menu).evaluate().isNotEmpty;
      _record('S04', 'screen', 'Chat menu button', pass);
      expect(pass, isTrue);
    });

    testWidgets('S05: Daily Scan screen renders', (t) async {
      await t.pumpWidget(_buildApp(initialLocation: '/daily-scan'));
      await t.pumpAndSettle();
      final pass = find.text('Daily Scan').evaluate().isNotEmpty;
      _record('S05', 'screen', 'Daily Scan title', pass);
      expect(pass, isTrue);
    });

    testWidgets('S06: Daily Scan shows stats banner', (t) async {
      await t.pumpWidget(_buildApp(initialLocation: '/daily-scan'));
      await t.pumpAndSettle();
      final pass = find.textContaining('listings').evaluate().isNotEmpty;
      _record('S06', 'screen', 'Daily Scan stats banner', pass);
      expect(pass, isTrue);
    });

    testWidgets('S07: Daily Scan shows comparisons', (t) async {
      await t.pumpWidget(_buildApp(initialLocation: '/daily-scan'));
      await t.pumpAndSettle();
      final pass = find.text('Best Price Arbitrage').evaluate().isNotEmpty;
      _record('S07', 'screen', 'Daily Scan arbitrage section', pass);
      expect(pass, isTrue);
    });

    testWidgets('S08: Daily Scan shows price drops', (t) async {
      await t.pumpWidget(_buildApp(initialLocation: '/daily-scan'));
      await t.pumpAndSettle();
      final pass = find
          .text('Price Drops', skipOffstage: false)
          .evaluate()
          .isNotEmpty;
      _record('S08', 'screen', 'Daily Scan price drops section', pass);
      expect(pass, isTrue);
    });

    testWidgets('S09: Daily Scan shows BMW M3 card', (t) async {
      await t.pumpWidget(_buildApp(initialLocation: '/daily-scan'));
      await t.pumpAndSettle();
      final pass = find.text('BMW M3').evaluate().isNotEmpty;
      _record('S09', 'screen', 'Daily Scan BMW M3 card', pass);
      expect(pass, isTrue);
    });

    testWidgets('S10: Daily Scan shows search field', (t) async {
      await t.pumpWidget(_buildApp(initialLocation: '/daily-scan'));
      await t.pumpAndSettle();
      final pass = find.text('Search make or model...').evaluate().isNotEmpty;
      _record('S10', 'screen', 'Daily Scan search field', pass);
      expect(pass, isTrue);
    });

    testWidgets('S11: Market Map renders', (t) async {
      await t.pumpWidget(_buildApp(initialLocation: '/market-map'));
      await t.pumpAndSettle();
      final pass = find.text('Market Map').evaluate().isNotEmpty;
      _record('S11', 'screen', 'Market Map title', pass);
      expect(pass, isTrue);
    });

    testWidgets('S12: Market Map shows tabs', (t) async {
      await t.pumpWidget(_buildApp(initialLocation: '/market-map'));
      await t.pumpAndSettle();
      final pass =
          find.text('Overview').evaluate().isNotEmpty &&
          find.text('Value Map').evaluate().isNotEmpty &&
          find.text('Price Index').evaluate().isNotEmpty;
      _record('S12', 'screen', 'Market Map tabs', pass);
      expect(pass, isTrue);
    });

    testWidgets('S13: Favorites empty state', (t) async {
      await t.pumpWidget(_buildApp(initialLocation: '/favorites'));
      await t.pumpAndSettle();
      final pass = find.text('No favorites yet').evaluate().isNotEmpty;
      _record('S13', 'screen', 'Favorites empty state', pass);
      expect(pass, isTrue);
    });

    testWidgets('S14: Garage empty state', (t) async {
      await t.pumpWidget(_buildApp(initialLocation: '/garage'));
      await t.pumpAndSettle();
      final pass = find.text('No cars in your garage').evaluate().isNotEmpty;
      _record('S14', 'screen', 'Garage empty state', pass);
      expect(pass, isTrue);
    });

    testWidgets('S15: Profile renders', (t) async {
      await t.pumpWidget(_buildApp(initialLocation: '/profile'));
      await t.pumpAndSettle();
      final pass = find.text('Profile & Preferences').evaluate().isNotEmpty;
      _record('S15', 'screen', 'Profile title', pass);
      expect(pass, isTrue);
    });

    testWidgets('S16: All screens have menu icon', (t) async {
      bool allHaveMenu = true;
      for (final route in [
        '/chat',
        '/daily-scan',
        '/market-map',
        '/favorites',
        '/garage',
        '/profile',
      ]) {
        await t.pumpWidget(_buildApp(initialLocation: route));
        await t.pumpAndSettle();
        if (find.byIcon(Icons.menu).evaluate().isEmpty) {
          allHaveMenu = false;
          break;
        }
      }
      _record('S16', 'screen', 'All screens have menu icon', allHaveMenu);
      expect(allHaveMenu, isTrue);
    });

    testWidgets('S17: Daily Scan refresh button', (t) async {
      await t.pumpWidget(_buildApp(initialLocation: '/daily-scan'));
      await t.pumpAndSettle();
      final pass = find.byIcon(Icons.refresh).evaluate().isNotEmpty;
      _record('S17', 'screen', 'Daily Scan refresh button', pass);
      expect(pass, isTrue);
    });

    testWidgets('S18: Daily Scan filter dropdowns', (t) async {
      await t.pumpWidget(_buildApp(initialLocation: '/daily-scan'));
      await t.pumpAndSettle();
      final pass =
          find.text('All makes').evaluate().isNotEmpty &&
          find.text('All years').evaluate().isNotEmpty;
      _record('S18', 'screen', 'Daily Scan filter dropdowns', pass);
      expect(pass, isTrue);
    });

    testWidgets('S19: Daily Scan result count', (t) async {
      await t.pumpWidget(_buildApp(initialLocation: '/daily-scan'));
      await t.pumpAndSettle();
      final pass = find.text('2 of 2 results').evaluate().isNotEmpty;
      _record('S19', 'screen', 'Daily Scan result count', pass);
      expect(pass, isTrue);
    });

    testWidgets('S20: Daily Scan CHEAPEST label', (t) async {
      await t.pumpWidget(_buildApp(initialLocation: '/daily-scan'));
      await t.pumpAndSettle();
      final pass = find.text('CHEAPEST').evaluate().isNotEmpty;
      _record('S20', 'screen', 'Daily Scan CHEAPEST label', pass);
      expect(pass, isTrue);
    });

    testWidgets('S21: Guest mode shows Guest in sidebar', (t) async {
      await t.pumpWidget(_buildApp(guest: true));
      await t.pumpAndSettle();
      await t.tap(find.byIcon(Icons.menu));
      await t.pumpAndSettle();
      final pass = find.text('Guest').evaluate().isNotEmpty;
      _record('S21', 'screen', 'Guest mode sidebar label', pass);
      expect(pass, isTrue);
    });

    testWidgets('S22: Auth mode shows user name in sidebar', (t) async {
      await t.pumpWidget(_buildApp());
      await t.pumpAndSettle();
      await t.tap(find.byIcon(Icons.menu));
      await t.pumpAndSettle();
      final pass = find.text('Test User').evaluate().isNotEmpty;
      _record('S22', 'screen', 'Auth mode sidebar user name', pass);
      expect(pass, isTrue);
    });

    testWidgets('S23: Sidebar shows New Chat button', (t) async {
      await t.pumpWidget(_buildApp());
      await t.pumpAndSettle();
      await t.tap(find.byIcon(Icons.menu));
      await t.pumpAndSettle();
      final pass = find.text('New Chat').evaluate().isNotEmpty;
      _record('S23', 'screen', 'Sidebar New Chat button', pass);
      expect(pass, isTrue);
    });

    testWidgets('S24: Sidebar shows agents', (t) async {
      await t.pumpWidget(_buildApp());
      await t.pumpAndSettle();
      await t.tap(find.byIcon(Icons.menu));
      await t.pumpAndSettle();
      final pass = find.text('Car Search').evaluate().isNotEmpty;
      _record('S24', 'screen', 'Sidebar agent list', pass);
      expect(pass, isTrue);
    });

    testWidgets('S25: Sidebar shows workspace links', (t) async {
      await t.pumpWidget(_buildApp());
      await t.pumpAndSettle();
      await t.tap(find.byIcon(Icons.menu));
      await t.pumpAndSettle();
      final pass =
          find.text('Daily Scan').evaluate().isNotEmpty &&
          find.text('Market Map').evaluate().isNotEmpty;
      _record('S25', 'screen', 'Sidebar workspace links', pass);
      expect(pass, isTrue);
    });

    testWidgets('S26: Sidebar shows sessions', (t) async {
      await t.pumpWidget(_buildApp());
      await t.pumpAndSettle();
      await t.tap(find.byIcon(Icons.menu));
      await t.pumpAndSettle();
      final pass = find.text('Find BMW M3').evaluate().isNotEmpty;
      _record('S26', 'screen', 'Sidebar session list', pass);
      expect(pass, isTrue);
    });

    testWidgets('S27: Sidebar empty sessions', (t) async {
      await t.pumpWidget(_buildApp(sessions: []));
      await t.pumpAndSettle();
      await t.tap(find.byIcon(Icons.menu));
      await t.pumpAndSettle();
      final pass = find.text('No chat history yet').evaluate().isNotEmpty;
      _record('S27', 'screen', 'Sidebar empty sessions', pass);
      expect(pass, isTrue);
    });

    testWidgets('S28: Analytics screen renders', (t) async {
      await t.pumpWidget(_buildApp(initialLocation: '/analytics'));
      await t.pumpAndSettle();
      final pass = find.text('Analytics').evaluate().isNotEmpty;
      _record('S28', 'screen', 'Analytics title', pass);
      expect(pass, isTrue);
    });

    testWidgets('S29: Saved Searches screen renders', (t) async {
      await t.pumpWidget(_buildApp(initialLocation: '/saved-searches'));
      await t.pumpAndSettle();
      final pass = find.text('Saved Searches').evaluate().isNotEmpty;
      _record('S29', 'screen', 'Saved Searches title', pass);
      expect(pass, isTrue);
    });

    testWidgets('S30: Daily Scan Audi RS6 price drop', (t) async {
      await t.pumpWidget(_buildApp(initialLocation: '/daily-scan'));
      await t.pumpAndSettle();
      final pass = find
          .textContaining('Audi', skipOffstage: false)
          .evaluate()
          .isNotEmpty;
      _record('S30', 'screen', 'Daily Scan price drop card', pass);
      expect(pass, isTrue);
    });
  });

  // ========================================================================
  // Category 3: Navigation (20 tests)
  // ========================================================================
  group('N: Navigation', () {
    testWidgets('N01: Drawer opens from chat', (t) async {
      await t.pumpWidget(_buildApp());
      await t.pumpAndSettle();
      await t.tap(find.byIcon(Icons.menu));
      await t.pumpAndSettle();
      final pass = find.byType(Drawer).evaluate().isNotEmpty;
      _record('N01', 'navigation', 'Drawer opens from chat', pass);
      expect(pass, isTrue);
    });

    testWidgets('N02: Drawer opens from daily scan', (t) async {
      await t.pumpWidget(_buildApp(initialLocation: '/daily-scan'));
      await t.pumpAndSettle();
      await t.tap(find.byIcon(Icons.menu));
      await t.pumpAndSettle();
      final pass = find.byType(Drawer).evaluate().isNotEmpty;
      _record('N02', 'navigation', 'Drawer opens from daily scan', pass);
      expect(pass, isTrue);
    });

    testWidgets('N03: Drawer opens from market map', (t) async {
      await t.pumpWidget(_buildApp(initialLocation: '/market-map'));
      await t.pumpAndSettle();
      await t.tap(find.byIcon(Icons.menu));
      await t.pumpAndSettle();
      final pass = find.byType(Drawer).evaluate().isNotEmpty;
      _record('N03', 'navigation', 'Drawer opens from market map', pass);
      expect(pass, isTrue);
    });

    testWidgets('N04: Drawer opens from favorites', (t) async {
      await t.pumpWidget(_buildApp(initialLocation: '/favorites'));
      await t.pumpAndSettle();
      await t.tap(find.byIcon(Icons.menu));
      await t.pumpAndSettle();
      final pass = find.byType(Drawer).evaluate().isNotEmpty;
      _record('N04', 'navigation', 'Drawer opens from favorites', pass);
      expect(pass, isTrue);
    });

    testWidgets('N05: Drawer opens from garage', (t) async {
      await t.pumpWidget(_buildApp(initialLocation: '/garage'));
      await t.pumpAndSettle();
      await t.tap(find.byIcon(Icons.menu));
      await t.pumpAndSettle();
      final pass = find.byType(Drawer).evaluate().isNotEmpty;
      _record('N05', 'navigation', 'Drawer opens from garage', pass);
      expect(pass, isTrue);
    });

    testWidgets('N06: Drawer opens from profile', (t) async {
      await t.pumpWidget(_buildApp(initialLocation: '/profile'));
      await t.pumpAndSettle();
      await t.tap(find.byIcon(Icons.menu));
      await t.pumpAndSettle();
      final pass = find.byType(Drawer).evaluate().isNotEmpty;
      _record('N06', 'navigation', 'Drawer opens from profile', pass);
      expect(pass, isTrue);
    });

    testWidgets('N07: Drawer opens from analytics', (t) async {
      await t.pumpWidget(_buildApp(initialLocation: '/analytics'));
      await t.pumpAndSettle();
      await t.tap(find.byIcon(Icons.menu));
      await t.pumpAndSettle();
      final pass = find.byType(Drawer).evaluate().isNotEmpty;
      _record('N07', 'navigation', 'Drawer opens from analytics', pass);
      expect(pass, isTrue);
    });

    testWidgets('N08: Navigate chat to daily scan', (t) async {
      await t.pumpWidget(_buildApp());
      await t.pumpAndSettle();
      _router.go('/daily-scan');
      await t.pumpAndSettle();
      final pass = find.text('Daily Scan').evaluate().isNotEmpty;
      _record('N08', 'navigation', 'Chat to Daily Scan', pass);
      expect(pass, isTrue);
    });

    testWidgets('N09: Navigate chat to market map', (t) async {
      await t.pumpWidget(_buildApp());
      await t.pumpAndSettle();
      _router.go('/market-map');
      await t.pumpAndSettle();
      final pass = find.text('Market Map').evaluate().isNotEmpty;
      _record('N09', 'navigation', 'Chat to Market Map', pass);
      expect(pass, isTrue);
    });

    testWidgets('N10: Navigate chat to favorites', (t) async {
      await t.pumpWidget(_buildApp());
      await t.pumpAndSettle();
      _router.go('/favorites');
      await t.pumpAndSettle();
      final pass = find.text('No favorites yet').evaluate().isNotEmpty;
      _record('N10', 'navigation', 'Chat to Favorites', pass);
      expect(pass, isTrue);
    });

    testWidgets('N11: Navigate chat to garage', (t) async {
      await t.pumpWidget(_buildApp());
      await t.pumpAndSettle();
      _router.go('/garage');
      await t.pumpAndSettle();
      final pass = find.text('My Garage').evaluate().isNotEmpty;
      _record('N11', 'navigation', 'Chat to Garage', pass);
      expect(pass, isTrue);
    });

    testWidgets('N12: Navigate chat to profile', (t) async {
      await t.pumpWidget(_buildApp());
      await t.pumpAndSettle();
      _router.go('/profile');
      await t.pumpAndSettle();
      final pass = find.text('Profile & Preferences').evaluate().isNotEmpty;
      _record('N12', 'navigation', 'Chat to Profile', pass);
      expect(pass, isTrue);
    });

    testWidgets('N13: Round-trip navigation', (t) async {
      await t.pumpWidget(_buildApp());
      await t.pumpAndSettle();
      _router.go('/daily-scan');
      await t.pumpAndSettle();
      _router.go('/chat');
      await t.pumpAndSettle();
      final pass = find
          .text('Kenri.ai · Personal Advisor')
          .evaluate()
          .isNotEmpty;
      _record('N13', 'navigation', 'Round-trip Chat-DailyScan-Chat', pass);
      expect(pass, isTrue);
    });

    testWidgets('N14: Three-stop navigation', (t) async {
      await t.pumpWidget(_buildApp());
      await t.pumpAndSettle();
      _router.go('/market-map');
      await t.pumpAndSettle();
      _router.go('/favorites');
      await t.pumpAndSettle();
      _router.go('/garage');
      await t.pumpAndSettle();
      final pass = find.text('My Garage').evaluate().isNotEmpty;
      _record('N14', 'navigation', 'Three-stop navigation', pass);
      expect(pass, isTrue);
    });

    testWidgets('N15: Full circuit all screens', (t) async {
      await t.pumpWidget(_buildApp());
      await t.pumpAndSettle();
      bool allOk = true;
      for (final route in [
        '/daily-scan',
        '/market-map',
        '/favorites',
        '/garage',
        '/analytics',
        '/profile',
        '/chat',
      ]) {
        _router.go(route);
        await t.pumpAndSettle();
        if (find.byIcon(Icons.menu).evaluate().isEmpty) {
          allOk = false;
          break;
        }
      }
      _record('N15', 'navigation', 'Full circuit all screens', allOk);
      expect(allOk, isTrue);
    });

    testWidgets('N16: Sidebar Daily Scan link visible', (t) async {
      await t.pumpWidget(_buildApp());
      await t.pumpAndSettle();
      await t.tap(find.byIcon(Icons.menu));
      await t.pumpAndSettle();
      final pass = find.text('Daily Scan').evaluate().isNotEmpty;
      _record('N16', 'navigation', 'Sidebar has Daily Scan link', pass);
      expect(pass, isTrue);
    });

    testWidgets('N17: Sidebar Favorites link visible', (t) async {
      await t.pumpWidget(_buildApp());
      await t.pumpAndSettle();
      await t.tap(find.byIcon(Icons.menu));
      await t.pumpAndSettle();
      final pass = find.text('Favorites').evaluate().isNotEmpty;
      _record('N17', 'navigation', 'Sidebar has Favorites link', pass);
      expect(pass, isTrue);
    });

    testWidgets('N18: Sidebar Profile link visible', (t) async {
      await t.pumpWidget(_buildApp());
      await t.pumpAndSettle();
      await t.tap(find.byIcon(Icons.menu));
      await t.pumpAndSettle();
      final pass = find
          .text('Profile', skipOffstage: false)
          .evaluate()
          .isNotEmpty;
      _record('N18', 'navigation', 'Sidebar has Profile link', pass);
      expect(pass, isTrue);
    });

    testWidgets('N19: Sidebar My Garage link visible', (t) async {
      await t.pumpWidget(_buildApp());
      await t.pumpAndSettle();
      await t.tap(find.byIcon(Icons.menu));
      await t.pumpAndSettle();
      final pass = find
          .text('My Garage', skipOffstage: false)
          .evaluate()
          .isNotEmpty;
      _record('N19', 'navigation', 'Sidebar has My Garage link', pass);
      expect(pass, isTrue);
    });

    testWidgets('N20: Sidebar Analytics link visible', (t) async {
      await t.pumpWidget(_buildApp());
      await t.pumpAndSettle();
      await t.tap(find.byIcon(Icons.menu));
      await t.pumpAndSettle();
      final pass = find
          .text('Analytics', skipOffstage: false)
          .evaluate()
          .isNotEmpty;
      _record('N20', 'navigation', 'Sidebar has Analytics link', pass);
      expect(pass, isTrue);
    });
  });

  // ========================================================================
  // Write results at the end
  // ========================================================================
  tearDownAll(() {
    final output = {
      'test_run': DateTime.now().toIso8601String(),
      'total': _allResults.length,
      'passed': _allResults.where((r) => r.result == 'pass').length,
      'failed': _allResults.where((r) => r.result == 'fail').length,
      'categories': {
        'model': _allResults.where((r) => r.category == 'model').length,
        'screen': _allResults.where((r) => r.category == 'screen').length,
        'navigation': _allResults
            .where((r) => r.category == 'navigation')
            .length,
      },
      'results': _allResults.map((r) => r.toJson()).toList(),
    };

    final dir = Directory('test-results');
    if (!dir.existsSync()) dir.createSync(recursive: true);
    File(
      'test-results/flutter-combinatorial.json',
    ).writeAsStringSync(const JsonEncoder.withIndent('  ').convert(output));
  });
}
