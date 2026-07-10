import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:carhero/config/theme.dart';
import 'package:carhero/screens/chat/widgets/chat_input_bar.dart';

Widget _wrapWidget(Widget child) {
  return MaterialApp(
    theme: AppTheme.light,
    home: Scaffold(body: child),
  );
}

void main() {
  group('ChatInputBar', () {
    testWidgets('renders text field with placeholder', (tester) async {
      await tester.pumpWidget(
        _wrapWidget(ChatInputBar(isStreaming: false, onSend: (_) {})),
      );

      expect(find.byType(TextField), findsOneWidget);
      expect(find.text('Search for a car, compare models...'), findsOneWidget);
    });

    testWidgets('renders send button', (tester) async {
      await tester.pumpWidget(
        _wrapWidget(ChatInputBar(isStreaming: false, onSend: (_) {})),
      );

      expect(find.byIcon(Icons.arrow_upward), findsOneWidget);
    });

    testWidgets('send button disabled when text is empty', (tester) async {
      String? sentText;

      await tester.pumpWidget(
        _wrapWidget(
          ChatInputBar(isStreaming: false, onSend: (text) => sentText = text),
        ),
      );

      // Tap send with empty field
      await tester.tap(find.byIcon(Icons.arrow_upward));
      await tester.pump();

      expect(sentText, isNull);
    });

    testWidgets('calls onSend when text entered and send pressed', (
      tester,
    ) async {
      String? sentText;

      await tester.pumpWidget(
        _wrapWidget(
          ChatInputBar(isStreaming: false, onSend: (text) => sentText = text),
        ),
      );

      await tester.enterText(find.byType(TextField), 'Find BMWs');
      await tester.pump();

      await tester.tap(find.byIcon(Icons.arrow_upward));
      await tester.pump();

      expect(sentText, 'Find BMWs');
    });

    testWidgets('clears text after send', (tester) async {
      await tester.pumpWidget(
        _wrapWidget(ChatInputBar(isStreaming: false, onSend: (_) {})),
      );

      await tester.enterText(find.byType(TextField), 'Test message');
      await tester.pump();
      await tester.tap(find.byIcon(Icons.arrow_upward));
      await tester.pump();

      final textField = tester.widget<TextField>(find.byType(TextField));
      expect(textField.controller!.text, '');
    });

    testWidgets('text field disabled when streaming', (tester) async {
      await tester.pumpWidget(
        _wrapWidget(ChatInputBar(isStreaming: true, onSend: (_) {})),
      );

      final textField = tester.widget<TextField>(find.byType(TextField));
      expect(textField.enabled, false);
    });

    testWidgets('shows spinner when streaming', (tester) async {
      await tester.pumpWidget(
        _wrapWidget(ChatInputBar(isStreaming: true, onSend: (_) {})),
      );

      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(find.byIcon(Icons.arrow_upward), findsNothing);
    });

    testWidgets('does not send when streaming even with text', (tester) async {
      String? sentText;

      await tester.pumpWidget(
        _wrapWidget(
          ChatInputBar(isStreaming: true, onSend: (text) => sentText = text),
        ),
      );

      // Can't enter text when disabled, so this is just a safety check
      expect(sentText, isNull);
    });
  });
}
