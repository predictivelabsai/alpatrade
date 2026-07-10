import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:carhero/config/theme.dart';
import 'package:carhero/models/chat.dart';
import 'package:carhero/screens/chat/widgets/tool_execution_card.dart';

Widget _wrapWidget(Widget child) {
  return MaterialApp(
    theme: AppTheme.light,
    home: Scaffold(body: child),
  );
}

void main() {
  group('ToolExecutionCard', () {
    testWidgets('displays tool name', (tester) async {
      const toolCall = ToolCall(
        name: 'search_listings',
        args: {'make': 'BMW'},
        output: '5 results',
      );

      await tester.pumpWidget(
        _wrapWidget(
          const ToolExecutionCard(toolCall: toolCall, isActive: false),
        ),
      );

      expect(find.text('Search Listings'), findsOneWidget);
    });

    testWidgets('shows spinner when active', (tester) async {
      const toolCall = ToolCall(name: 'search_listings', args: {});

      await tester.pumpWidget(
        _wrapWidget(
          const ToolExecutionCard(toolCall: toolCall, isActive: true),
        ),
      );

      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(find.text('Calling...'), findsOneWidget);
    });

    testWidgets('shows check icon and Done when completed', (tester) async {
      const toolCall = ToolCall(
        name: 'search_listings',
        args: {},
        output: 'done',
      );

      await tester.pumpWidget(
        _wrapWidget(
          const ToolExecutionCard(toolCall: toolCall, isActive: false),
        ),
      );

      expect(find.byIcon(Icons.check_circle), findsOneWidget);
      expect(find.text('Done'), findsOneWidget);
    });

    testWidgets('expands to show output on tap', (tester) async {
      const toolCall = ToolCall(
        name: 'search_listings',
        args: {'make': 'BMW'},
        output: '5 listings found for BMW',
      );

      await tester.pumpWidget(
        _wrapWidget(
          const ToolExecutionCard(toolCall: toolCall, isActive: false),
        ),
      );

      // Initially collapsed - output should not be visible
      expect(find.text('5 listings found for BMW'), findsNothing);

      // Tap to expand
      await tester.tap(find.text('Search Listings'));
      await tester.pumpAndSettle();

      // Output should now be visible
      expect(find.text('5 listings found for BMW'), findsOneWidget);
    });
  });
}
