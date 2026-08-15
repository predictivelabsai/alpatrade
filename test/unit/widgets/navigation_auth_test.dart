import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:alpatrade/app.dart';
import 'package:alpatrade/providers/connectivity_provider.dart';

class _AlwaysOnline extends ConnectivityNotifier {
  @override
  Stream<bool> build() => Stream.value(true);
}

Widget _testApp() {
  return ProviderScope(
    overrides: [connectivityProvider.overrideWith(_AlwaysOnline.new)],
    child: const AlpaTradeApp(),
  );
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('protected tabs prompt for sign-in without retrying requests', (
    tester,
  ) async {
    await tester.pumpWidget(_testApp());
    await tester.pumpAndSettle();

    await tester.tap(find.text('Portfolio'));
    await tester.pumpAndSettle();

    expect(find.text('Sign in required'), findsOneWidget);
    expect(find.text('Sign in or create account'), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsNothing);
  });

  testWidgets('switching bottom tabs dismisses a More subpage', (tester) async {
    await tester.pumpWidget(_testApp());
    await tester.pumpAndSettle();

    await tester.tap(find.text('More'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Settings'));
    await tester.pumpAndSettle();
    expect(find.text('Settings'), findsOneWidget);

    await tester.tap(find.text('Chat'));
    await tester.pumpAndSettle();

    expect(find.text('AI Trading Assistant'), findsOneWidget);
    expect(find.text('Settings'), findsNothing);
  });

  testWidgets('paper-order shortcuts require authentication', (tester) async {
    await tester.pumpWidget(_testApp());
    await tester.pumpAndSettle();

    await tester.tap(find.text('Buy market'));
    await tester.pumpAndSettle();

    expect(find.text('Welcome back'), findsOneWidget);
    expect(find.text('Email'), findsOneWidget);
    expect(find.text('Password'), findsOneWidget);
    expect(find.text('New paper order'), findsNothing);
  });
}
