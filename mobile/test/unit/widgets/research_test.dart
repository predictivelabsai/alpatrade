import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:alpatrade/screens/research_screen.dart';
import 'package:alpatrade/services/research_service.dart';
import 'package:alpatrade/services/api_client.dart';

class ResearchFixture extends ResearchService {
  ResearchFixture() : super(ApiClient());
  @override
  Future<Map<String, dynamic>> leaderboard({
    String query = '',
    String kind = '',
  }) async => {
    'strategies': [
      {
        'id': 1,
        'rank': 1,
        'name': 'Momentum',
        'author': 'Research',
        'kind': 'backtest',
        'metrics': {
          'return_pct': 12.5,
          'annualised_pct': null,
          'as_of': '2026-10-09',
          'trading_days': 20,
        },
      },
    ],
  };
  @override
  Future<Map<String, dynamic>> performance(String method) async => {
    'funds': [
      {
        'name': 'Example fund',
        'returns': {
          'TTM': {'fund': 0.125, 'spy': -0.02},
        },
        'positions': 10,
        'value': 1000000000,
      },
    ],
  };
}

void main() {
  testWidgets('leaderboard labels hypothetical results and missing metrics', (
    tester,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          researchServiceProvider.overrideWithValue(ResearchFixture()),
        ],
        child: const MaterialApp(
          home: ResearchScreen(section: 'leaderboard', title: 'Leaderboard'),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('#1 Momentum'), findsOneWidget);
    expect(find.textContaining('Hypothetical backtest'), findsOneWidget);
    expect(find.textContaining('12.50% · Annualised —'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets(
    '13F fractions render as percentages rather than percentage points',
    (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            researchServiceProvider.overrideWithValue(ResearchFixture()),
          ],
          child: const MaterialApp(
            home: ResearchScreen(
              section: 'performance',
              title: 'Fund performance',
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.textContaining('12.50% · SPY -2.00%'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
}
