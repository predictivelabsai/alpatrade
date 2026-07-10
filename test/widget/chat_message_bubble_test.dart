import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:carhero/config/theme.dart';
import 'package:carhero/models/chat.dart';
import 'package:carhero/screens/chat/widgets/chat_message_bubble.dart';

Widget _wrapWidget(Widget child) {
  return MaterialApp(
    theme: AppTheme.light,
    home: Scaffold(body: SingleChildScrollView(child: child)),
  );
}

void main() {
  group('ChatMessageBubble', () {
    testWidgets('renders user message', (tester) async {
      const msg = ChatMessage(role: 'user', content: 'Find me a BMW');
      await tester.pumpWidget(
        _wrapWidget(const ChatMessageBubble(message: msg)),
      );

      expect(find.text('Find me a BMW'), findsOneWidget);
    });

    testWidgets('renders assistant message with markdown', (tester) async {
      const msg = ChatMessage(
        role: 'assistant',
        content: 'I found **5 BMWs** for you.',
      );
      await tester.pumpWidget(
        _wrapWidget(const ChatMessageBubble(message: msg)),
      );

      expect(find.textContaining('5 BMWs'), findsOneWidget);
    });

    testWidgets('renders tool calls when present', (tester) async {
      const msg = ChatMessage(
        role: 'assistant',
        content: 'Results',
        toolCalls: [
          ToolCall(
            name: 'search_listings',
            args: {'make': 'BMW'},
            output: '5 found',
          ),
        ],
      );

      await tester.pumpWidget(
        _wrapWidget(const ChatMessageBubble(message: msg)),
      );

      expect(find.text('Search Listings'), findsOneWidget);
    });

    testWidgets('user messages align right', (tester) async {
      const msg = ChatMessage(role: 'user', content: 'Test');
      await tester.pumpWidget(
        _wrapWidget(const ChatMessageBubble(message: msg)),
      );

      final column = tester.widget<Column>(
        find
            .ancestor(of: find.text('Test'), matching: find.byType(Column))
            .first,
      );
      expect(column.crossAxisAlignment, CrossAxisAlignment.end);
    });

    testWidgets('assistant messages align left', (tester) async {
      const msg = ChatMessage(role: 'assistant', content: 'Hello');
      await tester.pumpWidget(
        _wrapWidget(const ChatMessageBubble(message: msg)),
      );

      final column = tester.widget<Column>(
        find
            .ancestor(
              of: find.textContaining('Hello'),
              matching: find.byType(Column),
            )
            .first,
      );
      expect(column.crossAxisAlignment, CrossAxisAlignment.start);
    });
  });
}
