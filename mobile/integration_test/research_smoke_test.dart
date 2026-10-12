import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:alpatrade/app.dart';

// Run against the local API with a short-lived synthetic test JWT supplied via
// --dart-define-from-file. Never use an actual account or commit the token file.
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('local API: leaderboard, strategy, hedge funds and performance', (
    tester,
  ) async {
    SharedPreferences.setMockInitialValues({
      'alpatrade.auth.token': const String.fromEnvironment('LOCAL_TEST_TOKEN'),
      'alpatrade.auth.user_id': '00000000-0000-0000-0000-000000000001',
      'alpatrade.auth.email': 'mobile-smoke@example.test',
    });
    await tester.pumpWidget(const ProviderScope(child: AlpaTradeApp()));
    await tester.pumpAndSettle();
    await tester.tap(find.text('More'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Leaderboard'));
    await tester.pumpAndSettle(const Duration(seconds: 2));
    expect(find.text('Could not load research.'), findsNothing);
    expect(find.textContaining('#1 '), findsWidgets);
    await tester.tap(find.textContaining('#1 ').first);
    await tester.pumpAndSettle(const Duration(seconds: 2));
    expect(find.text('Strategy detail'), findsOneWidget);
    expect(find.text('Clone to my strategies'), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();
    await tester.pageBack();
    await tester.pumpAndSettle();
    await tester.tap(find.text('Hedge funds'));
    await tester.pumpAndSettle(const Duration(seconds: 2));
    expect(find.text('Could not load research.'), findsNothing);
    expect(find.textContaining('13F portfolio'), findsWidgets);
    await tester.pageBack();
    await tester.pumpAndSettle();
    await tester.tap(find.text('Fund performance'));
    await tester.pumpAndSettle(const Duration(seconds: 2));
    expect(find.text('Could not load research.'), findsNothing);
    expect(find.textContaining('SPY'), findsWidgets);
    expect(tester.takeException(), isNull);
  });
}
