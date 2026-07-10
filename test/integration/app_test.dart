import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'package:carhero/config/theme.dart';
import 'package:carhero/models/auth.dart';
import 'package:carhero/models/agent.dart';
import 'package:carhero/models/session.dart';
import 'package:carhero/providers/auth_provider.dart';
import 'package:carhero/providers/agent_provider.dart';
import 'package:carhero/providers/session_provider.dart';
import 'package:carhero/screens/auth/login_screen.dart';
import 'package:carhero/screens/chat_screen.dart';
import 'package:carhero/screens/app_scaffold.dart';

/// Builds a test app with full routing and auth state controlled by [isLoggedIn].
///
/// When [isLoggedIn] is false the router redirects protected routes to login.
/// When true, auth routes redirect to /chat.
Widget _buildTestApp({required bool isLoggedIn}) {
  final router = GoRouter(
    initialLocation: isLoggedIn ? '/chat' : '/auth/login',
    redirect: (context, state) {
      final path = state.uri.path;
      const publicPaths = {'/', '/about', '/contact'};
      const authPaths = {'/auth/login', '/auth/register', '/auth/forgot'};

      if (publicPaths.contains(path) || path.startsWith('/shared/')) {
        return null;
      }
      if (!isLoggedIn && !authPaths.contains(path)) {
        return '/auth/login';
      }
      if (isLoggedIn && authPaths.contains(path)) {
        return '/chat';
      }
      return null;
    },
    routes: [
      GoRoute(path: '/auth/login', builder: (_, __) => const LoginScreen()),
      ShellRoute(
        builder: (context, state, child) => AppScaffold(child: child),
        routes: [
          GoRoute(
            path: '/chat',
            pageBuilder: (context, state) =>
                const NoTransitionPage(child: ChatScreen()),
          ),
        ],
      ),
    ],
  );

  final authValue = isLoggedIn
      ? const AuthResponse(
          token: 'test-token',
          email: 'test@example.com',
          name: 'Test User',
          userId: 1,
        )
      : null;

  return ProviderScope(
    overrides: [
      authProvider.overrideWith(() => _FakeAuthNotifier(authValue)),
      agentsProvider.overrideWith((ref) => <AgentOut>[]),
      sessionsProvider.overrideWith((ref) => <SessionSummary>[]),
    ],
    child: MaterialApp.router(theme: AppTheme.light, routerConfig: router),
  );
}

class _FakeAuthNotifier extends AuthNotifier {
  final AuthResponse? _initial;
  _FakeAuthNotifier(this._initial);

  @override
  Future<AuthResponse?> build() async => _initial;
}

void main() {
  group('App launch integration', () {
    testWidgets('shows login screen when not authenticated', (tester) async {
      await tester.pumpWidget(_buildTestApp(isLoggedIn: false));
      await tester.pumpAndSettle();

      // Login screen should be visible
      expect(find.text('Kenri.ai'), findsOneWidget);
      expect(find.text('Sign In'), findsOneWidget);
      expect(find.text('Personal Advisor'), findsOneWidget);
    });

    testWidgets('shows chat screen when authenticated', (tester) async {
      await tester.pumpWidget(_buildTestApp(isLoggedIn: true));
      await tester.pumpAndSettle();

      // Chat screen should be visible (with the app bar title and input bar)
      expect(find.text('Kenri.ai · Personal Advisor'), findsOneWidget);
      // The welcome message should be visible since there are no messages
      expect(find.text('Kenri.ai'), findsOneWidget);
    });

    testWidgets('authenticated app shows chat screen with sidebar access', (
      tester,
    ) async {
      await tester.pumpWidget(_buildTestApp(isLoggedIn: true));
      await tester.pumpAndSettle();

      // Chat screen should be visible with drawer access via menu button
      expect(find.text('Kenri.ai · Personal Advisor'), findsOneWidget);
      expect(find.byIcon(Icons.menu), findsOneWidget);
    });

    testWidgets('unauthenticated user cannot access /chat', (tester) async {
      // Even if initial location is /chat, redirect should send to login
      final router = GoRouter(
        initialLocation: '/chat',
        redirect: (context, state) {
          final path = state.uri.path;
          const authPaths = {'/auth/login', '/auth/register', '/auth/forgot'};
          if (!authPaths.contains(path) && path != '/' && path != '/about') {
            return '/auth/login';
          }
          return null;
        },
        routes: [
          GoRoute(path: '/auth/login', builder: (_, __) => const LoginScreen()),
          GoRoute(
            path: '/chat',
            builder: (_, __) =>
                const Scaffold(body: Center(child: Text('Chat Screen'))),
          ),
        ],
      );

      await tester.pumpWidget(
        ProviderScope(
          child: MaterialApp.router(
            theme: AppTheme.light,
            routerConfig: router,
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Should be on login, not chat
      expect(find.text('Sign In'), findsOneWidget);
      expect(find.text('Chat Screen'), findsNothing);
    });

    testWidgets('chat screen shows input bar with placeholder text', (
      tester,
    ) async {
      await tester.pumpWidget(_buildTestApp(isLoggedIn: true));
      await tester.pumpAndSettle();

      expect(find.text('Search for a car, compare models...'), findsOneWidget);
    });

    testWidgets('chat screen shows welcome prompts when no messages', (
      tester,
    ) async {
      await tester.pumpWidget(_buildTestApp(isLoggedIn: true));
      await tester.pumpAndSettle();

      // The WelcomeMessage shows "Try asking" and example prompts
      expect(find.text('Try asking'), findsOneWidget);
    });
  });
}
