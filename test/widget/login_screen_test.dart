import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:carhero/config/theme.dart';
import 'package:carhero/screens/auth/login_screen.dart';

Widget _wrapWidget(Widget child) {
  return ProviderScope(
    child: MaterialApp(theme: AppTheme.light, home: child),
  );
}

void main() {
  group('LoginScreen', () {
    testWidgets('renders email and password fields', (tester) async {
      await tester.pumpWidget(_wrapWidget(const LoginScreen()));

      expect(find.byType(TextFormField), findsNWidgets(2));
      expect(find.text('Email'), findsOneWidget);
      expect(find.text('Password'), findsOneWidget);
    });

    testWidgets('renders sign in button', (tester) async {
      await tester.pumpWidget(_wrapWidget(const LoginScreen()));

      expect(find.text('Sign In'), findsOneWidget);
      expect(find.byType(ElevatedButton), findsOneWidget);
    });

    testWidgets('renders Google sign in button', (tester) async {
      await tester.pumpWidget(_wrapWidget(const LoginScreen()));

      expect(find.text('Sign in with Google'), findsOneWidget);
      expect(find.byType(OutlinedButton), findsOneWidget);
    });

    testWidgets('renders forgot password link', (tester) async {
      await tester.pumpWidget(_wrapWidget(const LoginScreen()));

      expect(find.text('Forgot password?'), findsOneWidget);
    });

    testWidgets('renders register link', (tester) async {
      await tester.pumpWidget(_wrapWidget(const LoginScreen()));

      expect(find.text("Don't have an account? "), findsOneWidget);
      expect(find.text('Register'), findsOneWidget);
    });

    testWidgets('renders Kenri.ai branding', (tester) async {
      await tester.pumpWidget(_wrapWidget(const LoginScreen()));

      expect(find.text('Kenri.ai'), findsOneWidget);
      expect(find.text('Personal Advisor'), findsOneWidget);
    });

    testWidgets('shows validation error on empty email', (tester) async {
      await tester.pumpWidget(_wrapWidget(const LoginScreen()));

      await tester.tap(find.text('Sign In'));
      await tester.pumpAndSettle();

      expect(find.text('Email is required'), findsOneWidget);
    });

    testWidgets('shows validation error on empty password', (tester) async {
      await tester.pumpWidget(_wrapWidget(const LoginScreen()));

      // Enter email but leave password empty
      await tester.enterText(find.byType(TextFormField).first, 'test@test.com');
      await tester.tap(find.text('Sign In'));
      await tester.pumpAndSettle();

      expect(find.text('Password is required'), findsOneWidget);
    });

    testWidgets('shows validation error on invalid email', (tester) async {
      await tester.pumpWidget(_wrapWidget(const LoginScreen()));

      await tester.enterText(find.byType(TextFormField).first, 'notanemail');
      await tester.enterText(find.byType(TextFormField).last, 'password123');
      await tester.tap(find.text('Sign In'));
      await tester.pumpAndSettle();

      expect(find.text('Invalid email'), findsOneWidget);
    });

    testWidgets('shows validation error on short password', (tester) async {
      await tester.pumpWidget(_wrapWidget(const LoginScreen()));

      await tester.enterText(find.byType(TextFormField).first, 'user@test.com');
      await tester.enterText(find.byType(TextFormField).last, '123');
      await tester.tap(find.text('Sign In'));
      await tester.pumpAndSettle();

      expect(find.text('Must be at least 6 characters'), findsOneWidget);
    });

    testWidgets('password visibility toggle works', (tester) async {
      await tester.pumpWidget(_wrapWidget(const LoginScreen()));

      // Initially password is obscured - check via EditableText
      var editableTexts = tester
          .widgetList<EditableText>(find.byType(EditableText))
          .toList();
      expect(editableTexts.last.obscureText, true);

      // Find and tap the visibility toggle
      await tester.tap(find.byIcon(Icons.visibility_off_outlined));
      await tester.pump();

      // Now it should show password
      editableTexts = tester
          .widgetList<EditableText>(find.byType(EditableText))
          .toList();
      expect(editableTexts.last.obscureText, false);
    });

    testWidgets('or divider is displayed', (tester) async {
      await tester.pumpWidget(_wrapWidget(const LoginScreen()));

      expect(find.text('or'), findsOneWidget);
      expect(find.byType(Divider), findsNWidgets(2));
    });
  });
}
