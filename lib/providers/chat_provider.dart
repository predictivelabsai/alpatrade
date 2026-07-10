import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:alpatrade/models/chat.dart';
import 'package:alpatrade/services/chat_service.dart';

final chatServiceProvider = Provider<ChatService>((ref) => ChatService());

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

  /// Append a transcript line produced by the voice session so voice and text
  /// share one conversation view.
  void appendVoiceMessage(String role, String content) {
    if (content.trim().isEmpty) return;
    state = state.copyWith(
      messages: [
        ...state.messages,
        ChatMessage(role: role, content: content),
      ],
    );
  }

  void newChat() => state = ChatState.initial();
}
