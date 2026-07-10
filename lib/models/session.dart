class SessionSummary {
  final int id;
  final String title;
  final String? agentSlug;
  final String updatedAt;

  const SessionSummary({
    required this.id,
    required this.title,
    this.agentSlug,
    required this.updatedAt,
  });

  factory SessionSummary.fromJson(Map<String, dynamic> json) => SessionSummary(
    id: json['id'] as int,
    title: json['title'] as String,
    agentSlug: json['agent_slug'] as String?,
    updatedAt: json['updated_at'] as String,
  );
}

class MessageOut {
  final String role;
  final String content;
  final String? agentSlug;

  const MessageOut({required this.role, required this.content, this.agentSlug});

  factory MessageOut.fromJson(Map<String, dynamic> json) => MessageOut(
    role: json['role'] as String,
    content: json['content'] as String,
    agentSlug: json['agent_slug'] as String?,
  );
}

class SessionDetail {
  final int id;
  final String title;
  final String? agentSlug;
  final List<MessageOut> messages;

  const SessionDetail({
    required this.id,
    required this.title,
    this.agentSlug,
    required this.messages,
  });

  factory SessionDetail.fromJson(Map<String, dynamic> json) => SessionDetail(
    id: json['id'] as int,
    title: json['title'] as String,
    agentSlug: json['agent_slug'] as String?,
    messages: (json['messages'] as List<dynamic>)
        .map((e) => MessageOut.fromJson(e as Map<String, dynamic>))
        .toList(),
  );
}

class ShareResponse {
  final String token;
  final String url;

  const ShareResponse({required this.token, required this.url});

  factory ShareResponse.fromJson(Map<String, dynamic> json) =>
      ShareResponse(token: json['token'] as String, url: json['url'] as String);
}
