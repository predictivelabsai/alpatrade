import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'package:carhero/config/api_config.dart';
import 'package:carhero/models/chat.dart';

class ChatService {
  Stream<ChatEvent> streamChat({
    required String message,
    int? sessionId,
    String lang = 'en',
    required String token,
  }) async* {
    final uri = Uri.parse('${ApiConfig.baseUrl}/chat');

    final request = http.Request('POST', uri);
    request.headers['Content-Type'] = 'application/json';
    request.headers['Accept'] = 'text/event-stream';
    if (token.isNotEmpty) {
      request.headers['Authorization'] = 'Bearer $token';
    }
    request.body = jsonEncode(
      ChatRequest(message: message, sessionId: sessionId, lang: lang).toJson(),
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
          if (line.startsWith('event: ')) {
            eventName = line.substring(7).trim();
          } else if (line.startsWith('data: ')) {
            eventData = line.substring(6);
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
