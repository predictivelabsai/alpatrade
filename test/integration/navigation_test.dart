import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'package:carhero/config/theme.dart';
import 'package:carhero/models/auth.dart';
import 'package:carhero/models/agent.dart';
import 'package:carhero/models/session.dart';
import 'package:carhero/models/favorite.dart';
import 'package:carhero/models/garage.dart';
import 'package:carhero/models/market_map.dart';
import 'package:carhero/models/profile.dart';
import 'package:carhero/providers/auth_provider.dart';
import 'package:carhero/providers/agent_provider.dart';
import 'package:carhero/providers/session_provider.dart';
import 'package:carhero/providers/favorite_provider.dart';
import 'package:carhero/providers/garage_provider.dart';
import 'package:carhero/providers/market_map_provider.dart';
import 'package:carhero/providers/profile_provider.dart';
import 'package:carhero/screens/chat_screen.dart';
import 'package:carhero/screens/market_map_screen.dart';
import 'package:carhero/screens/favorites_screen.dart';
import 'package:carhero/screens/garage_screen.dart';
import 'package:carhero/screens/profile_screen.dart';
import 'package:carhero/screens/app_scaffold.dart';

// ---------------------------------------------------------------------------
// Fake notifiers to isolate from network
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

late GoRouter _router;

Widget _buildNavTestApp({String initialLocation = '/chat'}) {
  _router = GoRouter(
    initialLocation: initialLocation,
    routes: [
      ShellRoute(
        builder: (context, state, child) => AppScaffold(child: child),
        routes: [
          GoRoute(
            path: '/chat',
            pageBuilder: (context, state) =>
                const NoTransitionPage(child: ChatScreen()),
          ),
          GoRoute(
            path: '/market-map',
            pageBuilder: (context, state) =>
                const NoTransitionPage(child: MarketMapScreen()),
          ),
          GoRoute(
            path: '/favorites',
            pageBuilder: (context, state) =>
                const NoTransitionPage(child: FavoritesScreen()),
          ),
          GoRoute(
            path: '/garage',
            pageBuilder: (context, state) =>
                const NoTransitionPage(child: GarageScreen()),
          ),
          GoRoute(
            path: '/profile',
            pageBuilder: (context, state) =>
                const NoTransitionPage(child: ProfileScreen()),
          ),
        ],
      ),
    ],
  );

  return ProviderScope(
    overrides: [
      authProvider.overrideWith(() => _FakeAuthNotifier()),
      agentsProvider.overrideWith((ref) => <AgentOut>[]),
      sessionsProvider.overrideWith((ref) => <SessionSummary>[]),
      favoritesProvider.overrideWith(() => _FakeFavoritesNotifier()),
      garageProvider.overrideWith(() => _FakeGarageNotifier()),
      profileProvider.overrideWith(() => _FakeProfileNotifier()),
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

void main() {
  group('Sidebar navigation integration', () {
    testWidgets('starts on Chat tab', (tester) async {
      await tester.pumpWidget(_buildNavTestApp());
      await tester.pumpAndSettle();

      expect(find.text('Kenri.ai · Personal Advisor'), findsOneWidget);
      expect(find.text('Kenri.ai'), findsOneWidget);
    });

    testWidgets('navigating to Market Map shows tabs and title', (
      tester,
    ) async {
      await tester.pumpWidget(_buildNavTestApp(initialLocation: '/market-map'));
      await tester.pumpAndSettle();

      expect(find.text('Market Map'), findsOneWidget);
      expect(find.text('Overview'), findsOneWidget);
      expect(find.text('Value Map'), findsOneWidget);
      expect(find.text('Price Index'), findsOneWidget);
    });

    testWidgets('Favorites screen shows empty state', (tester) async {
      await tester.pumpWidget(_buildNavTestApp(initialLocation: '/favorites'));
      await tester.pumpAndSettle();

      expect(find.text('No favorites yet'), findsOneWidget);
      expect(
        find.text('Save listings you like and they will appear here.'),
        findsOneWidget,
      );
    });

    testWidgets('Garage screen shows empty state with Add Car button', (
      tester,
    ) async {
      await tester.pumpWidget(_buildNavTestApp(initialLocation: '/garage'));
      await tester.pumpAndSettle();

      expect(find.text('My Garage'), findsOneWidget);
      expect(find.text('No cars in your garage'), findsOneWidget);
      expect(
        find.text('Add your car to track its value and costs.'),
        findsOneWidget,
      );
      expect(find.text('Add Car'), findsWidgets);
    });

    testWidgets('Profile screen shows account section', (tester) async {
      await tester.pumpWidget(_buildNavTestApp(initialLocation: '/profile'));
      await tester.pumpAndSettle();

      expect(find.text('Profile & Preferences'), findsOneWidget);
      expect(find.text('Account'), findsOneWidget);
    });

    testWidgets('can navigate between screens via router', (tester) async {
      await tester.pumpWidget(_buildNavTestApp());
      await tester.pumpAndSettle();

      // Start on chat
      expect(find.text('Kenri.ai'), findsOneWidget);

      // Navigate to favorites via router
      _router.go('/favorites');
      await tester.pumpAndSettle();
      expect(find.text('No favorites yet'), findsOneWidget);

      // Navigate back to chat
      _router.go('/chat');
      await tester.pumpAndSettle();
      expect(find.text('Kenri.ai'), findsOneWidget);
    });

    testWidgets('AppScaffold wraps all routes', (tester) async {
      await tester.pumpWidget(_buildNavTestApp());
      await tester.pumpAndSettle();

      expect(find.byType(AppScaffold), findsOneWidget);

      _router.go('/market-map');
      await tester.pumpAndSettle();
      expect(find.byType(AppScaffold), findsOneWidget);

      _router.go('/garage');
      await tester.pumpAndSettle();
      expect(find.byType(AppScaffold), findsOneWidget);
    });
  });
}
