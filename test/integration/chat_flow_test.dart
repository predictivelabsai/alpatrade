import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'package:carhero/config/theme.dart';
import 'package:carhero/models/auth.dart';
import 'package:carhero/models/chat.dart';
import 'package:carhero/models/agent.dart';
import 'package:carhero/models/session.dart';
import 'package:carhero/providers/auth_provider.dart';
import 'package:carhero/providers/chat_provider.dart';
import 'package:carhero/providers/agent_provider.dart';
import 'package:carhero/providers/session_provider.dart';
import 'package:carhero/screens/chat_screen.dart';
import 'package:carhero/screens/app_scaffold.dart';

// ---------------------------------------------------------------------------
// Fake providers for isolating the chat flow from network
// ---------------------------------------------------------------------------

class _FakeAuthNotifier extends AuthNotifier {
  @override
  Future<AuthResponse?> build() async => const AuthResponse(
    token: 'test-token',
    email: 'test@test.com',
    name: 'Test',
    userId: 1,
  );
}

/// A ChatNotifier override that does not call ChatService.
/// Instead, sendMessage immediately simulates the full SSE lifecycle.
class FakeChatNotifier extends ChatNotifier {
  @override
  ChatState build() => ChatState.initial();

  @override
  Future<void> sendMessage(String message, {String lang = 'en'}) async {
    // 1. Add user message, start streaming
    state = state.copyWith(
      messages: [
        ...state.messages,
        ChatMessage(role: 'user', content: message),
      ],
      isStreaming: true,
      streamBuffer: '',
      activeToolCalls: [],
      artifacts: [],
      error: null,
    );

    // 2. Simulate session event
    state = state.copyWith(currentSessionId: 42);

    // 3. Simulate agent route
    state = state.copyWith(
      currentAgent: const AgentInfo(
        slug: 'search',
        name: 'Car Search',
        icon: 'search',
      ),
    );

    // 4. Simulate token streaming
    const reply = 'I found some great options for you.';
    state = state.copyWith(streamBuffer: reply);

    // 5. Simulate done
    final assistantMsg = ChatMessage(
      role: 'assistant',
      content: reply,
      agentSlug: 'search',
    );
    state = state.copyWith(
      messages: [...state.messages, assistantMsg],
      isStreaming: false,
      streamBuffer: '',
    );
  }
}

Widget _buildChatTestApp({ChatNotifier? chatNotifier}) {
  final router = GoRouter(
    initialLocation: '/chat',
    routes: [
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
      authProvider.overrideWith(() => _FakeAuthNotifier()),
      agentsProvider.overrideWith((ref) => <AgentOut>[]),
      sessionsProvider.overrideWith((ref) => <SessionSummary>[]),
      if (chatNotifier != null) chatProvider.overrideWith(() => chatNotifier),
    ],
    child: MaterialApp.router(theme: AppTheme.light, routerConfig: router),
  );
}

void main() {
  group('Chat flow - state lifecycle', () {
    test('full message lifecycle builds correct state', () {
      var state = ChatState.initial();

      // 1. User sends message
      state = state.copyWith(
        messages: [
          ...state.messages,
          const ChatMessage(role: 'user', content: 'Find BMW 3 Series'),
        ],
        isStreaming: true,
        streamBuffer: '',
      );

      expect(state.messages, hasLength(1));
      expect(state.messages[0].role, 'user');
      expect(state.isStreaming, true);

      // 2. Session assigned
      state = state.copyWith(currentSessionId: 42);
      expect(state.currentSessionId, 42);

      // 3. Agent routed
      state = state.copyWith(
        currentAgent: const AgentInfo(
          slug: 'search',
          name: 'Car Search',
          icon: 'search',
        ),
      );
      expect(state.currentAgent!.slug, 'search');

      // 4. Tool starts
      final toolCalls = <ToolCall>[
        const ToolCall(name: 'search_listings', args: {'make': 'BMW'}),
      ];
      state = state.copyWith(activeToolCalls: toolCalls);
      expect(state.activeToolCalls, hasLength(1));

      // 5. Tool ends
      toolCalls[0] = toolCalls[0].withOutput('5 results');
      state = state.copyWith(activeToolCalls: List.of(toolCalls));
      expect(state.activeToolCalls[0].output, '5 results');

      // 6. Tokens stream in
      var buffer = '';
      for (final text in ['I found ', '5 BMWs ', 'for you.']) {
        buffer += text;
      }
      state = state.copyWith(streamBuffer: buffer);
      expect(state.streamBuffer, 'I found 5 BMWs for you.');

      // 7. Artifact arrives
      final artifacts = [
        Artifact.fromJson({
          'kind': 'listings',
          'title': 'BMW 3 Series',
          'listings': [],
        }),
      ];
      state = state.copyWith(artifacts: artifacts);
      expect(state.artifacts, hasLength(1));

      // 8. Done - finalize
      final assistantMsg = ChatMessage(
        role: 'assistant',
        content: buffer,
        agentSlug: 'search',
        toolCalls: List.of(toolCalls),
        artifacts: List.of(artifacts),
      );
      state = state.copyWith(
        messages: [...state.messages, assistantMsg],
        isStreaming: false,
        streamBuffer: '',
      );

      expect(state.messages, hasLength(2));
      expect(state.messages[1].role, 'assistant');
      expect(state.messages[1].content, 'I found 5 BMWs for you.');
      expect(state.messages[1].toolCalls, hasLength(1));
      expect(state.messages[1].artifacts, hasLength(1));
      expect(state.isStreaming, false);
      expect(state.streamBuffer, '');
    });

    test('new chat resets state', () {
      var state = ChatState.initial().copyWith(
        messages: [const ChatMessage(role: 'user', content: 'test')],
        currentSessionId: 5,
        currentAgent: const AgentInfo(slug: 'a', name: 'A', icon: 'a'),
      );

      state = ChatState.initial();

      expect(state.messages, isEmpty);
      expect(state.currentSessionId, isNull);
      expect(state.currentAgent, isNull);
    });

    test('load session restores messages', () {
      final messages = [
        const ChatMessage(role: 'user', content: 'Hello'),
        const ChatMessage(role: 'assistant', content: 'Hi there'),
      ];

      final state = ChatState(messages: messages, currentSessionId: 10);

      expect(state.messages, hasLength(2));
      expect(state.currentSessionId, 10);
      expect(state.isStreaming, false);
    });

    test('error state preserves messages', () {
      var state = ChatState.initial().copyWith(
        messages: [const ChatMessage(role: 'user', content: 'test')],
        isStreaming: true,
      );

      state = state.copyWith(error: 'Network error', isStreaming: false);

      expect(state.messages, hasLength(1));
      expect(state.error, 'Network error');
      expect(state.isStreaming, false);
    });

    test('multiple messages accumulate correctly', () {
      var state = ChatState.initial();

      for (int i = 0; i < 5; i++) {
        state = state.copyWith(
          messages: [
            ...state.messages,
            ChatMessage(role: 'user', content: 'Message $i'),
            ChatMessage(role: 'assistant', content: 'Reply $i'),
          ],
        );
      }

      expect(state.messages, hasLength(10));
      expect(state.messages[0].content, 'Message 0');
      expect(state.messages[9].content, 'Reply 4');
    });
  });

  group('Chat flow - widget integration', () {
    testWidgets('chat screen renders welcome message with no messages', (
      tester,
    ) async {
      await tester.pumpWidget(_buildChatTestApp());
      await tester.pumpAndSettle();

      expect(find.text('Kenri.ai'), findsOneWidget);
      expect(find.text('Try asking'), findsOneWidget);
      expect(find.text('Search for a car, compare models...'), findsOneWidget);
    });

    testWidgets('chat screen has app bar with title', (tester) async {
      await tester.pumpWidget(_buildChatTestApp());
      await tester.pumpAndSettle();

      expect(find.text('Kenri.ai · Personal Advisor'), findsOneWidget);
    });

    testWidgets('chat screen has menu icon for drawer', (tester) async {
      await tester.pumpWidget(_buildChatTestApp());
      await tester.pumpAndSettle();

      expect(find.byIcon(Icons.menu), findsOneWidget);
    });

    testWidgets('typing text enables send button', (tester) async {
      await tester.pumpWidget(_buildChatTestApp());
      await tester.pumpAndSettle();

      // Find the TextField in the ChatInputBar
      final textField = find.byType(TextField);
      expect(textField, findsOneWidget);

      // Type a message
      await tester.enterText(textField, 'Find me a BMW');
      await tester.pump();

      // The send button (arrow_upward icon) should now be active
      expect(find.byIcon(Icons.arrow_upward), findsOneWidget);
    });

    testWidgets('sending a message shows user message and assistant reply', (
      tester,
    ) async {
      final fakeChatNotifier = FakeChatNotifier();
      await tester.pumpWidget(
        _buildChatTestApp(chatNotifier: fakeChatNotifier),
      );
      await tester.pumpAndSettle();

      // Type and send a message
      final textField = find.byType(TextField);
      await tester.enterText(textField, 'Find me a BMW');
      await tester.pump();

      // Submit via the text field's onSubmitted
      await tester.testTextInput.receiveAction(TextInputAction.send);
      await tester.pumpAndSettle();

      // Both user and assistant messages should be visible
      expect(find.text('Find me a BMW'), findsOneWidget);
      expect(find.text('I found some great options for you.'), findsOneWidget);
    });

    testWidgets('chat state with pre-loaded messages shows message list', (
      tester,
    ) async {
      // Use a notifier that starts with messages already loaded
      final notifier = FakeChatNotifier();
      await tester.pumpWidget(_buildChatTestApp(chatNotifier: notifier));
      await tester.pumpAndSettle();

      // Send a message to populate state
      final textField = find.byType(TextField);
      await tester.enterText(textField, 'Hello');
      await tester.pump();
      await tester.testTextInput.receiveAction(TextInputAction.send);
      await tester.pumpAndSettle();

      // Welcome message should be gone, message list should be visible
      expect(find.text('Kenri.ai'), findsNothing);
      expect(find.text('Hello'), findsOneWidget);
    });

    testWidgets('chat screen shows agent name after routing', (tester) async {
      final fakeChatNotifier = FakeChatNotifier();
      await tester.pumpWidget(
        _buildChatTestApp(chatNotifier: fakeChatNotifier),
      );
      await tester.pumpAndSettle();

      // Initially shows default title
      expect(find.text('Kenri.ai · Personal Advisor'), findsOneWidget);

      // Send a message which triggers agent routing in fake
      final textField = find.byType(TextField);
      await tester.enterText(textField, 'Search BMW');
      await tester.pump();
      await tester.testTextInput.receiveAction(TextInputAction.send);
      await tester.pumpAndSettle();

      // After routing, app bar should show agent name
      expect(find.text('Car Search'), findsOneWidget);
    });
  });
}
