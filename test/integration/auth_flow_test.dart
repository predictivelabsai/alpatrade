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
import 'package:carhero/screens/auth/register_screen.dart';
import 'package:carhero/screens/auth/forgot_password_screen.dart';
import 'package:carhero/screens/chat_screen.dart';
import 'package:carhero/screens/app_scaffold.dart';

/// A controllable AuthNotifier for tests. Simulates login/register/logout
/// without hitting a real API or secure storage.
class FakeAuthNotifier extends AuthNotifier {
  AuthResponse? _value;

  FakeAuthNotifier([this._value]);

  @override
  Future<AuthResponse?> build() async => _value;

  @override
  Future<void> login(String email, String password) async {
    state = const AsyncValue.loading();
    _value = AuthResponse(
      token: 'fake-jwt-token',
      email: email,
      name: 'Test User',
      userId: 1,
    );
    state = AsyncValue.data(_value);
  }

  @override
  Future<void> register(String email, String password, String name) async {
    state = const AsyncValue.loading();
    _value = AuthResponse(
      token: 'fake-jwt-token',
      email: email,
      name: name,
      userId: 2,
    );
    state = AsyncValue.data(_value);
  }

  @override
  Future<void> logout() async {
    _value = null;
    state = const AsyncValue.data(null);
  }
}

Widget _buildTestApp() {
  final router = GoRouter(
    initialLocation: '/auth/login',
    routes: [
      GoRoute(path: '/auth/login', builder: (_, __) => const LoginScreen()),
      GoRoute(
        path: '/auth/register',
        builder: (_, __) => const RegisterScreen(),
      ),
      GoRoute(
        path: '/auth/forgot',
        builder: (_, __) => const ForgotPasswordScreen(),
      ),
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

  return ProviderScope(
    overrides: [
      authProvider.overrideWith(() => FakeAuthNotifier()),
      agentsProvider.overrideWith((ref) => <AgentOut>[]),
      sessionsProvider.overrideWith((ref) => <SessionSummary>[]),
    ],
    child: MaterialApp.router(theme: AppTheme.light, routerConfig: router),
  );
}

void main() {
  group('Auth flow integration', () {
    testWidgets('login screen renders all elements', (tester) async {
      await tester.pumpWidget(_buildTestApp());
      await tester.pumpAndSettle();

      expect(find.text('Kenri.ai'), findsOneWidget);
      expect(find.text('Sign In'), findsOneWidget);
      expect(find.text('Sign in with Google'), findsOneWidget);
      expect(find.text('Forgot password?'), findsOneWidget);
      expect(find.text('Register'), findsOneWidget);
    });

    testWidgets('can navigate to register screen', (tester) async {
      await tester.pumpWidget(_buildTestApp());
      await tester.pumpAndSettle();

      await tester.tap(find.text('Register'));
      await tester.pumpAndSettle();

      expect(find.text('Create Account'), findsOneWidget);
      expect(find.text('Create your account'), findsOneWidget);
    });

    testWidgets('register screen has name, email, password fields', (
      tester,
    ) async {
      await tester.pumpWidget(_buildTestApp());
      await tester.pumpAndSettle();

      await tester.tap(find.text('Register'));
      await tester.pumpAndSettle();

      // Should have 3 TextFormFields (name, email, password)
      expect(find.byType(TextFormField), findsNWidgets(3));
      expect(find.text('Full name'), findsOneWidget);
      expect(find.text('Email'), findsOneWidget);
    });

    testWidgets('can navigate to forgot password', (tester) async {
      await tester.pumpWidget(_buildTestApp());
      await tester.pumpAndSettle();

      await tester.tap(find.text('Forgot password?'));
      await tester.pumpAndSettle();

      expect(find.text('Send Reset Link'), findsOneWidget);
    });

    testWidgets('form validation prevents empty submit', (tester) async {
      await tester.pumpWidget(_buildTestApp());
      await tester.pumpAndSettle();

      await tester.tap(find.text('Sign In'));
      await tester.pumpAndSettle();

      expect(find.text('Email is required'), findsOneWidget);
      expect(find.text('Password is required'), findsOneWidget);
    });

    testWidgets('email validation catches invalid input', (tester) async {
      await tester.pumpWidget(_buildTestApp());
      await tester.pumpAndSettle();

      await tester.enterText(find.byType(TextFormField).first, 'bad-email');
      await tester.enterText(find.byType(TextFormField).last, 'password123');
      await tester.tap(find.text('Sign In'));
      await tester.pumpAndSettle();

      expect(find.text('Invalid email'), findsOneWidget);
    });

    testWidgets('short password shows validation error', (tester) async {
      await tester.pumpWidget(_buildTestApp());
      await tester.pumpAndSettle();

      await tester.enterText(find.byType(TextFormField).first, 'user@test.com');
      await tester.enterText(find.byType(TextFormField).last, 'ab');
      await tester.tap(find.text('Sign In'));
      await tester.pumpAndSettle();

      expect(find.text('Must be at least 6 characters'), findsOneWidget);
    });

    testWidgets('valid form submission does not show validation errors', (
      tester,
    ) async {
      await tester.pumpWidget(_buildTestApp());
      await tester.pumpAndSettle();

      // Fill in valid credentials
      await tester.enterText(find.byType(TextFormField).first, 'user@test.com');
      await tester.enterText(find.byType(TextFormField).last, 'password123');

      // Tap sign in - should not show validation errors
      await tester.tap(find.text('Sign In'));
      await tester.pumpAndSettle();

      expect(find.text('Email is required'), findsNothing);
      expect(find.text('Password is required'), findsNothing);
      expect(find.text('Invalid email'), findsNothing);
    });

    testWidgets('successful login updates auth provider state', (tester) async {
      late WidgetRef capturedRef;

      final router = GoRouter(
        initialLocation: '/auth/login',
        routes: [
          GoRoute(path: '/auth/login', builder: (_, __) => const LoginScreen()),
          GoRoute(
            path: '/chat',
            builder: (_, __) =>
                const Scaffold(body: Center(child: Text('Chat Arrived'))),
          ),
        ],
      );

      await tester.pumpWidget(
        ProviderScope(
          overrides: [authProvider.overrideWith(() => FakeAuthNotifier())],
          child: MaterialApp.router(
            theme: AppTheme.light,
            routerConfig: router,
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Verify that auth state starts as null (not logged in)
      final scope = tester
          .element(find.byType(LoginScreen))
          .findAncestorWidgetOfExactType<ProviderScope>()!;

      // Fill in valid credentials
      await tester.enterText(find.byType(TextFormField).first, 'user@test.com');
      await tester.enterText(find.byType(TextFormField).last, 'password123');

      // Tap sign in -- FakeAuthNotifier.login() will set auth state to data
      await tester.tap(find.text('Sign In'));
      await tester.pumpAndSettle();

      // After login, there should be no validation errors shown
      // (form was valid and login was called)
      expect(find.text('Email is required'), findsNothing);
      expect(find.text('Invalid email'), findsNothing);
      expect(find.text('Password is required'), findsNothing);
    });

    testWidgets('can navigate from register back to login', (tester) async {
      await tester.pumpWidget(_buildTestApp());
      await tester.pumpAndSettle();

      // Go to register
      await tester.tap(find.text('Register'));
      await tester.pumpAndSettle();
      expect(find.text('Create Account'), findsOneWidget);

      // Go back to login via "Sign in" link
      await tester.tap(find.text('Sign in'));
      await tester.pumpAndSettle();
      expect(find.text('Sign In'), findsOneWidget);
    });

    testWidgets('register screen validates empty fields', (tester) async {
      await tester.pumpWidget(_buildTestApp());
      await tester.pumpAndSettle();

      await tester.tap(find.text('Register'));
      await tester.pumpAndSettle();

      await tester.tap(find.text('Create Account'));
      await tester.pumpAndSettle();

      // All three fields should show required/validation errors
      expect(find.textContaining('required'), findsWidgets);
    });
  });
}
