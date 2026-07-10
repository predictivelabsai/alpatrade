import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'package:alpatrade/config/api_config.dart';
import 'package:alpatrade/models/chat.dart';

/// Streams POST /v2/chat as Server-Sent Events. Uses the raw `http` package
/// because Dio does not stream POST response bodies well.
class ChatService {
  Stream<ChatEvent> streamChat({
    required String message,
    String? threadId,
  }) async* {
    final uri = Uri.parse('${ApiConfig.baseUrl}/v2/chat');

    final request = http.Request('POST', uri)
      ..headers['Content-Type'] = 'application/json'
      ..headers['Accept'] = 'text/event-stream'
      ..body = jsonEncode(
        ChatRequest(msg: message, threadId: threadId).toJson(),
      );

    final response = await http.Client().send(request);

    if (response.statusCode != 200) {
      final body = await response.stream.bytesToString();
      yield ErrorEvent('HTTP ${response.statusCode}: $body');
      return;
    }

    String buffer = '';

    await for (final chunk in response.stream.transform(utf8.decoder)) {
      buffer += chunk;

      while (true) {
        final eventEnd = buffer.indexOf('\n\n');
        if (eventEnd == -1) break;

        final rawEvent = buffer.substring(0, eventEnd);
        buffer = buffer.substring(eventEnd + 2);

        String? eventName;
        String? eventData;

        for (final line in rawEvent.split('\n')) {
          if (line.startsWith('event:')) {
            eventName = line.substring(6).trim();
          } else if (line.startsWith('data:')) {
            eventData = line.substring(5).trim();
          }
        }

        if (eventName != null && eventData != null) {
          try {
            final json = jsonDecode(eventData) as Map<String, dynamic>;
            yield parseSseEvent(eventName, json);
          } catch (e) {
            yield ErrorEvent('Failed to parse SSE event: $e');
          }
        }
      }
    }
  }
}
