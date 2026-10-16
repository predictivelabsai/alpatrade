import 'package:alpatrade/config/theme.dart';
import 'package:alpatrade/models/chat.dart';
import 'package:alpatrade/screens/chat/widgets/chat_input_bar.dart';
import 'package:alpatrade/screens/chat/widgets/chat_message_bubble.dart';
import 'package:alpatrade/screens/chat/widgets/quick_order_bar.dart';
import 'package:alpatrade/screens/chat/widgets/responsive_markdown.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

const positionsMarkdown = '''
**Your current paper positions:**

| Symbol | Qty | Entry | Current | Unrealized P&L | P&L% |
|--------|-----|-------|---------|----------------|------|
| AAPL | 3 | \$301.32 | \$305.80 | +\$13.44 | +1.49% |
| TSLA | 2 | \$312.10 | \$306.75 | -\$10.70 | -1.71% |

*2 open positions*
''';

void main() {
  test(
    'parses a complete positions table without losing surrounding prose',
    () {
      final blocks = parseMarkdownContent(positionsMarkdown);

      expect(blocks, hasLength(3));
      expect(
        (blocks.first as MarkdownTextBlock).text,
        contains('current paper'),
      );
      final table = blocks[1] as MarkdownTableBlock;
      expect(table.headers, [
        'Symbol',
        'Qty',
        'Entry',
        'Current',
        'Unrealized P&L',
        'P&L%',
      ]);
      expect(table.rows, hasLength(2));
      expect(table.rows.first.first, 'AAPL');
      expect((blocks.last as MarkdownTextBlock).text, contains('2 open'));
    },
  );

  test('keeps an incomplete streaming table as Markdown text', () {
    final blocks = parseMarkdownContent('''
| Symbol | Qty |
| --- | --- |
''');

    expect(blocks, hasLength(1));
    expect(blocks.single, isA<MarkdownTextBlock>());
  });

  testWidgets('positions answer renders as readable cards at phone width', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: const Scaffold(
          body: Padding(
            padding: EdgeInsets.all(16),
            child: ChatMessageBubble(
              message: ChatMessage(
                role: 'assistant',
                content: positionsMarkdown,
                agentSlug: 'ai',
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('AAPL'), findsOneWidget);
    expect(find.text('TSLA'), findsOneWidget);
    expect(find.text('Unrealized P&L'), findsNWidgets(2));
    expect(find.text('+\$13.44'), findsOneWidget);
    expect(find.text('-\$10.70'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('all quick-order presets remain visible at phone width', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: Scaffold(body: QuickOrderBar(onSelect: (_) {})),
      ),
    );

    for (final label in [
      'Buy limit',
      'Sell limit',
      'Buy market',
      'Sell market',
    ]) {
      expect(find.text(label), findsOneWidget);
    }
    expect(tester.takeException(), isNull);
  });

  testWidgets('submitting safely transitions the focused input to streaming', (
    tester,
  ) async {
    final controller = TextEditingController();
    final focusNode = FocusNode();
    addTearDown(controller.dispose);
    addTearDown(focusNode.dispose);
    var streaming = false;
    String? sent;

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: StatefulBuilder(
          builder: (context, setState) => Scaffold(
            body: ChatInputBar(
              isStreaming: streaming,
              voiceActive: false,
              controller: controller,
              focusNode: focusNode,
              onMic: () {},
              onSend: (value) {
                sent = value;
                setState(() => streaming = true);
              },
            ),
          ),
        ),
      ),
    );

    await tester.enterText(find.byType(TextField), 'what are my positins');
    await tester.testTextInput.receiveAction(TextInputAction.send);
    await tester.pump();

    expect(sent, 'what are my positins');
    expect(streaming, isTrue);
    expect(focusNode.hasFocus, isFalse);
    expect(tester.widget<TextField>(find.byType(TextField)).readOnly, isTrue);
    expect(tester.takeException(), isNull);
  });
}
