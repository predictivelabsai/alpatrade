import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:carhero/config/theme.dart';
import 'package:carhero/models/agent.dart';
import 'package:carhero/providers/agent_provider.dart';
import 'package:carhero/screens/chat/widgets/welcome_message.dart';

Widget _wrapWidget(Widget child) {
  return ProviderScope(
    overrides: [agentsProvider.overrideWith((ref) async => <AgentOut>[])],
    child: MaterialApp(
      theme: AppTheme.light,
      home: Scaffold(body: child),
    ),
  );
}

void main() {
  group('WelcomeMessage', () {
    testWidgets('renders title', (tester) async {
      await tester.pumpWidget(_wrapWidget(WelcomeMessage(onPromptTap: (_) {})));
      await tester.pumpAndSettle();

      expect(find.text('Kenri.ai'), findsOneWidget);
    });

    testWidgets('renders subtitle description', (tester) async {
      await tester.pumpWidget(_wrapWidget(WelcomeMessage(onPromptTap: (_) {})));
      await tester.pumpAndSettle();

      expect(find.textContaining('European listings'), findsOneWidget);
    });

    testWidgets('renders Try asking header', (tester) async {
      await tester.pumpWidget(_wrapWidget(WelcomeMessage(onPromptTap: (_) {})));
      await tester.pumpAndSettle();

      expect(find.text('Try asking'), findsOneWidget);
    });

    testWidgets('renders fallback prompts when agents not loaded', (
      tester,
    ) async {
      await tester.pumpWidget(_wrapWidget(WelcomeMessage(onPromptTap: (_) {})));
      await tester.pumpAndSettle();

      expect(find.textContaining('Porsche'), findsOneWidget);
    });

    testWidgets('renders K logo box', (tester) async {
      await tester.pumpWidget(_wrapWidget(WelcomeMessage(onPromptTap: (_) {})));
      await tester.pumpAndSettle();

      expect(find.text('K'), findsOneWidget);
    });

    testWidgets('tapping a prompt chip calls onPromptTap with text', (
      tester,
    ) async {
      String? tappedPrompt;

      await tester.pumpWidget(
        _wrapWidget(
          WelcomeMessage(onPromptTap: (prompt) => tappedPrompt = prompt),
        ),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.textContaining('Porsche'));
      await tester.pump();

      expect(tappedPrompt, contains('Porsche'));
    });
  });
}
