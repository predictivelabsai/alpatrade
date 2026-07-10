/// Request body for POST /v2/chat.
class ChatRequest {
  final String msg;
  final String? threadId;

  const ChatRequest({required this.msg, this.threadId});

  Map<String, dynamic> toJson() => {
    'msg': msg,
    if (threadId != null) 'thread_id': threadId,
  };
}

// ---------------------------------------------------------------------------
// SSE events emitted by /v2/chat:
//   session | agent_route | token | tool_start | tool_end | error | done
// ---------------------------------------------------------------------------
sealed class ChatEvent {}

class SessionEvent extends ChatEvent {
  final String sid; // thread id echoed back
  SessionEvent(this.sid);
}

class AgentRouteEvent extends ChatEvent {
  final String slug; // 'command' | 'ai'
  final String name;
  AgentRouteEvent({required this.slug, required this.name});
}

class TokenEvent extends ChatEvent {
  final String text;
  TokenEvent(this.text);
}

class ToolStartEvent extends ChatEvent {
  final String name;
  ToolStartEvent(this.name);
}

class ToolEndEvent extends ChatEvent {
  final String name;
  ToolEndEvent(this.name);
}

class DoneEvent extends ChatEvent {
  DoneEvent();
}

class ErrorEvent extends ChatEvent {
  final String message;
  ErrorEvent(this.message);
}

ChatEvent parseSseEvent(String name, Map<String, dynamic> data) {
  switch (name) {
    case 'session':
      return SessionEvent('${data['sid'] ?? ''}');
    case 'agent_route':
      return AgentRouteEvent(
        slug: data['slug'] as String? ?? 'ai',
        name: data['agent'] as String? ?? 'AlpaTrade AI',
      );
    case 'token':
      return TokenEvent(data['text'] as String? ?? '');
    case 'tool_start':
      return ToolStartEvent(data['name'] as String? ?? '');
    case 'tool_end':
      return ToolEndEvent(data['name'] as String? ?? '');
    case 'done':
      return DoneEvent();
    case 'error':
      return ErrorEvent(data['message'] as String? ?? 'Unknown error');
    default:
      return ErrorEvent('Unknown event: $name');
  }
}

// ---------------------------------------------------------------------------
// UI state
// ---------------------------------------------------------------------------
class ChatMessage {
  final String role; // 'user' | 'assistant'
  final String content;
  final String? agentSlug;
  final List<ToolCall> toolCalls;

  const ChatMessage({
    required this.role,
    required this.content,
    this.agentSlug,
    this.toolCalls = const [],
  });

  ChatMessage copyWith({String? content, List<ToolCall>? toolCalls}) =>
      ChatMessage(
        role: role,
        content: content ?? this.content,
        agentSlug: agentSlug,
        toolCalls: toolCalls ?? this.toolCalls,
      );
}

class ToolCall {
  final String name;
  final bool done;

  const ToolCall({required this.name, this.done = false});

  ToolCall complete() => ToolCall(name: name, done: true);
}

class AgentInfo {
  final String slug;
  final String name;

  const AgentInfo({required this.slug, required this.name});
}

class ChatState {
  final List<ChatMessage> messages;
  final String? threadId;
  final AgentInfo? currentAgent;
  final bool isStreaming;
  final String streamBuffer;
  final List<ToolCall> activeToolCalls;
  final String? error;

  /// Live voice transcript, streamed while a voice session speaks/listens.
  /// Finalized lines move into [messages]; these hold the in-progress text.
  final String? liveUserText;
  final String? liveAssistantText;

  const ChatState({
    this.messages = const [],
    this.threadId,
    this.currentAgent,
    this.isStreaming = false,
    this.streamBuffer = '',
    this.activeToolCalls = const [],
    this.error,
    this.liveUserText,
    this.liveAssistantText,
  });

  factory ChatState.initial() => const ChatState();

  ChatState copyWith({
    List<ChatMessage>? messages,
    String? threadId,
    AgentInfo? currentAgent,
    bool? isStreaming,
    String? streamBuffer,
    List<ToolCall>? activeToolCalls,
    String? error,
    String? liveUserText,
    bool clearLiveUser = false,
    String? liveAssistantText,
    bool clearLiveAssistant = false,
  }) => ChatState(
    messages: messages ?? this.messages,
    threadId: threadId ?? this.threadId,
    currentAgent: currentAgent ?? this.currentAgent,
    isStreaming: isStreaming ?? this.isStreaming,
    streamBuffer: streamBuffer ?? this.streamBuffer,
    activeToolCalls: activeToolCalls ?? this.activeToolCalls,
    error: error,
    liveUserText: clearLiveUser ? null : (liveUserText ?? this.liveUserText),
    liveAssistantText: clearLiveAssistant
        ? null
        : (liveAssistantText ?? this.liveAssistantText),
  );
}
