import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:alpatrade/models/chat.dart';
import 'package:alpatrade/providers/auth_provider.dart';
import 'package:alpatrade/services/chat_service.dart';

final chatServiceProvider = Provider<ChatService>((ref) {
  final session = ref.watch(authProvider).whenOrNull(data: (value) => value);
  return ChatService(token: session?.token);
});

final chatProvider = NotifierProvider<ChatNotifier, ChatState>(
  ChatNotifier.new,
);

class ChatNotifier extends Notifier<ChatState> {
  @override
  ChatState build() => ChatState.initial();

  /// Keeps the same thread_id across a conversation so the 2-step paper-order
  /// confirm flow works ("buy 1 TSLA" -> preview -> "confirm").
  String _ensureThreadId() {
    final existing = state.threadId;
    if (existing != null && existing.isNotEmpty) return existing;
    final id = 'm${DateTime.now().microsecondsSinceEpoch}';
    state = state.copyWith(threadId: id);
    return id;
  }

  Future<void> sendMessage(String message) async {
    final trimmed = message.trim();
    if (trimmed.isEmpty || state.isStreaming) return;

    final threadId = _ensureThreadId();

    state = state.copyWith(
      messages: [
        ...state.messages,
        ChatMessage(role: 'user', content: trimmed),
      ],
      isStreaming: true,
      streamBuffer: '',
      activeToolCalls: [],
      error: null,
    );

    final service = ref.read(chatServiceProvider);
    String buffer = '';
    final toolCalls = <ToolCall>[];

    try {
      await for (final event in service.streamChat(
        message: trimmed,
        threadId: threadId,
      )) {
        switch (event) {
          case SessionEvent(:final sid):
            if (sid.isNotEmpty) state = state.copyWith(threadId: sid);
          case AgentRouteEvent(:final slug, :final name):
            state = state.copyWith(
              currentAgent: AgentInfo(slug: slug, name: name),
            );
          case TokenEvent(:final text):
            buffer += text;
            state = state.copyWith(streamBuffer: buffer);
          case ToolStartEvent(:final name):
            toolCalls.add(ToolCall(name: name));
            state = state.copyWith(activeToolCalls: List.of(toolCalls));
          case ToolEndEvent(:final name):
            final idx = toolCalls.lastIndexWhere(
              (t) => t.name == name && !t.done,
            );
            if (idx >= 0) {
              toolCalls[idx] = toolCalls[idx].complete();
              state = state.copyWith(activeToolCalls: List.of(toolCalls));
            }
          case DoneEvent():
            final assistantMsg = ChatMessage(
              role: 'assistant',
              content: buffer.isEmpty ? '_(no response)_' : buffer,
              agentSlug: state.currentAgent?.slug,
              toolCalls: List.of(toolCalls),
            );
            state = state.copyWith(
              messages: [...state.messages, assistantMsg],
              isStreaming: false,
              streamBuffer: '',
              activeToolCalls: [],
            );
          case ErrorEvent(:final message):
            state = state.copyWith(error: message, isStreaming: false);
        }
      }
    } catch (e) {
      state = state.copyWith(error: e.toString(), isStreaming: false);
    }
  }

  // ---- Voice transcript (streamed live, then finalized into messages) ----

  /// Live (in-progress) user speech transcript.
  void voiceUserPartial(String text) {
    state = state.copyWith(liveUserText: text);
  }

  /// Finalize the user's spoken turn into a permanent message.
  void voiceUserFinal(String text) {
    if (text.trim().isEmpty) {
      state = state.copyWith(clearLiveUser: true);
      return;
    }
    state = state.copyWith(
      messages: [
        ...state.messages,
        ChatMessage(role: 'user', content: text),
      ],
      clearLiveUser: true,
    );
  }

  /// Accumulate the assistant's spoken reply so it types back in real time.
  void voiceAssistantDelta(String delta) {
    state = state.copyWith(
      liveAssistantText: (state.liveAssistantText ?? '') + delta,
    );
  }

  /// Finalize the assistant's spoken turn into a permanent message.
  void voiceAssistantFinal(String? text) {
    final content = (text != null && text.trim().isNotEmpty)
        ? text
        : (state.liveAssistantText ?? '');
    if (content.trim().isEmpty) {
      state = state.copyWith(clearLiveAssistant: true);
      return;
    }
    state = state.copyWith(
      messages: [
        ...state.messages,
        ChatMessage(role: 'assistant', content: content, agentSlug: 'voice'),
      ],
      clearLiveAssistant: true,
    );
  }

  void newChat() => state = ChatState.initial();
}
