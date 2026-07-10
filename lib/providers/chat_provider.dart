import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:carhero/models/chat.dart';
import 'package:carhero/services/chat_service.dart';
import 'package:carhero/providers/auth_provider.dart';
import 'package:carhero/providers/session_provider.dart';

final chatServiceProvider = Provider<ChatService>((ref) => ChatService());

final chatProvider = NotifierProvider<ChatNotifier, ChatState>(
  ChatNotifier.new,
);

class ChatNotifier extends Notifier<ChatState> {
  @override
  ChatState build() => ChatState.initial();

  Future<void> sendMessage(String message, {String lang = 'en'}) async {
    final token = ref.read(currentTokenProvider) ?? '';

    // Add user message immediately
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

    final service = ref.read(chatServiceProvider);
    String buffer = '';
    final toolCalls = <ToolCall>[];
    final artifacts = <Artifact>[];

    try {
      await for (final event in service.streamChat(
        message: message,
        sessionId: state.currentSessionId,
        lang: lang,
        token: token,
      )) {
        switch (event) {
          case SessionEvent(:final sid):
            state = state.copyWith(currentSessionId: sid);
          case AgentRouteEvent(:final slug, :final name, :final icon):
            state = state.copyWith(
              currentAgent: AgentInfo(slug: slug, name: name, icon: icon),
            );
          case TokenEvent(:final text):
            buffer += text;
            state = state.copyWith(streamBuffer: buffer);
          case ToolStartEvent(:final name, :final args):
            toolCalls.add(ToolCall(name: name, args: args));
            state = state.copyWith(activeToolCalls: List.of(toolCalls));
          case ToolEndEvent(:final name, :final output):
            final idx = toolCalls.lastIndexWhere(
              (t) => t.name == name && t.output == null,
            );
            if (idx >= 0) {
              toolCalls[idx] = toolCalls[idx].withOutput(output);
              state = state.copyWith(activeToolCalls: List.of(toolCalls));
            }
          case ArtifactEvent(:final payload):
            artifacts.add(Artifact.fromJson(payload));
            state = state.copyWith(artifacts: List.of(artifacts));
          case DoneEvent():
            final assistantMsg = ChatMessage(
              role: 'assistant',
              content: buffer.isEmpty ? '(no response)' : buffer,
              agentSlug: state.currentAgent?.slug,
              toolCalls: List.of(toolCalls),
              artifacts: List.of(artifacts),
            );
            state = state.copyWith(
              messages: [...state.messages, assistantMsg],
              isStreaming: false,
              streamBuffer: '',
            );
            // Refresh sessions list
            ref.invalidate(sessionsProvider);
          case ErrorEvent(:final message):
            state = state.copyWith(error: message, isStreaming: false);
        }
      }
    } catch (e) {
      state = state.copyWith(error: e.toString(), isStreaming: false);
    }
  }

  void loadSession(int sessionId, List<ChatMessage> messages) {
    state = ChatState(messages: messages, currentSessionId: sessionId);
  }

  void newChat() {
    state = ChatState.initial();
  }
}
