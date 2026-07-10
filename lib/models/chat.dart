class ChatRequest {
  final String message;
  final int? sessionId;
  final String lang;

  const ChatRequest({required this.message, this.sessionId, this.lang = 'en'});

  Map<String, dynamic> toJson() => {
    'message': message,
    if (sessionId != null) 'session_id': sessionId,
    'lang': lang,
  };
}

sealed class ChatEvent {}

class SessionEvent extends ChatEvent {
  final int sid;
  SessionEvent(this.sid);
}

class AgentRouteEvent extends ChatEvent {
  final String slug;
  final String name;
  final String icon;
  AgentRouteEvent({required this.slug, required this.name, required this.icon});
}

class TokenEvent extends ChatEvent {
  final String text;
  TokenEvent(this.text);
}

class ToolStartEvent extends ChatEvent {
  final String name;
  final Map<String, dynamic> args;
  ToolStartEvent({required this.name, required this.args});
}

class ToolEndEvent extends ChatEvent {
  final String name;
  final String output;
  ToolEndEvent({required this.name, required this.output});
}

class ArtifactEvent extends ChatEvent {
  final Map<String, dynamic> payload;
  ArtifactEvent(this.payload);
}

class DoneEvent extends ChatEvent {
  final String slug;
  final int toolCount;
  DoneEvent({required this.slug, required this.toolCount});
}

class ErrorEvent extends ChatEvent {
  final String message;
  ErrorEvent(this.message);
}

ChatEvent parseSseEvent(String name, Map<String, dynamic> data) {
  switch (name) {
    case 'session':
      return SessionEvent(data['sid'] as int);
    case 'agent_route':
      return AgentRouteEvent(
        slug: data['slug'] as String,
        name: data['agent'] as String,
        icon: data['icon'] as String,
      );
    case 'token':
      return TokenEvent(data['text'] as String);
    case 'tool_start':
      return ToolStartEvent(
        name: data['name'] as String,
        args: (data['args'] as Map?)?.cast<String, dynamic>() ?? {},
      );
    case 'tool_end':
      return ToolEndEvent(
        name: data['name'] as String,
        output: data['output'] as String? ?? '',
      );
    case 'artifact_show':
      return ArtifactEvent(data);
    case 'done':
      return DoneEvent(
        slug: data['slug'] as String,
        toolCount: data['tools'] as int? ?? 0,
      );
    case 'error':
      return ErrorEvent(data['message'] as String? ?? 'Unknown error');
    default:
      return ErrorEvent('Unknown event: $name');
  }
}

class ChatMessage {
  final String role;
  final String content;
  final String? agentSlug;
  final List<ToolCall> toolCalls;
  final List<Artifact> artifacts;

  const ChatMessage({
    required this.role,
    required this.content,
    this.agentSlug,
    this.toolCalls = const [],
    this.artifacts = const [],
  });

  ChatMessage copyWith({
    String? content,
    List<ToolCall>? toolCalls,
    List<Artifact>? artifacts,
  }) => ChatMessage(
    role: role,
    content: content ?? this.content,
    agentSlug: agentSlug,
    toolCalls: toolCalls ?? this.toolCalls,
    artifacts: artifacts ?? this.artifacts,
  );
}

class ToolCall {
  final String name;
  final Map<String, dynamic> args;
  final String? output;

  const ToolCall({required this.name, required this.args, this.output});

  ToolCall withOutput(String output) =>
      ToolCall(name: name, args: args, output: output);
}

class Artifact {
  final String kind;
  final String? title;
  final Map<String, dynamic> data;

  const Artifact({required this.kind, this.title, required this.data});

  factory Artifact.fromJson(Map<String, dynamic> json) => Artifact(
    kind: json['kind'] as String? ?? 'unknown',
    title: json['title'] as String?,
    data: json,
  );
}

class AgentInfo {
  final String slug;
  final String name;
  final String icon;

  const AgentInfo({required this.slug, required this.name, required this.icon});
}

class ChatState {
  final List<ChatMessage> messages;
  final int? currentSessionId;
  final AgentInfo? currentAgent;
  final bool isStreaming;
  final String streamBuffer;
  final List<ToolCall> activeToolCalls;
  final List<Artifact> artifacts;
  final String? error;

  const ChatState({
    this.messages = const [],
    this.currentSessionId,
    this.currentAgent,
    this.isStreaming = false,
    this.streamBuffer = '',
    this.activeToolCalls = const [],
    this.artifacts = const [],
    this.error,
  });

  factory ChatState.initial() => const ChatState();

  ChatState copyWith({
    List<ChatMessage>? messages,
    int? currentSessionId,
    AgentInfo? currentAgent,
    bool? isStreaming,
    String? streamBuffer,
    List<ToolCall>? activeToolCalls,
    List<Artifact>? artifacts,
    String? error,
  }) => ChatState(
    messages: messages ?? this.messages,
    currentSessionId: currentSessionId ?? this.currentSessionId,
    currentAgent: currentAgent ?? this.currentAgent,
    isStreaming: isStreaming ?? this.isStreaming,
    streamBuffer: streamBuffer ?? this.streamBuffer,
    activeToolCalls: activeToolCalls ?? this.activeToolCalls,
    artifacts: artifacts ?? this.artifacts,
    error: error,
  );
}
