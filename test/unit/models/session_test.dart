import 'package:flutter_test/flutter_test.dart';
import 'package:carhero/models/session.dart';

void main() {
  group('SessionSummary', () {
    test('fromJson parses all fields', () {
      final json = {
        'id': 10,
        'title': 'BMW search',
        'agent_slug': 'search',
        'updated_at': '2024-03-15T10:30:00Z',
      };

      final s = SessionSummary.fromJson(json);

      expect(s.id, 10);
      expect(s.title, 'BMW search');
      expect(s.agentSlug, 'search');
      expect(s.updatedAt, '2024-03-15T10:30:00Z');
    });

    test('fromJson handles null agentSlug', () {
      final json = {
        'id': 1,
        'title': 'Chat',
        'updated_at': '2024-01-01T00:00:00Z',
      };

      final s = SessionSummary.fromJson(json);
      expect(s.agentSlug, isNull);
    });
  });

  group('MessageOut', () {
    test('fromJson parses correctly', () {
      final json = {
        'role': 'assistant',
        'content': 'Here are some BMWs',
        'agent_slug': 'search',
      };

      final msg = MessageOut.fromJson(json);

      expect(msg.role, 'assistant');
      expect(msg.content, 'Here are some BMWs');
      expect(msg.agentSlug, 'search');
    });

    test('fromJson handles null agentSlug', () {
      final json = {'role': 'user', 'content': 'Find cars'};
      final msg = MessageOut.fromJson(json);
      expect(msg.agentSlug, isNull);
    });
  });

  group('SessionDetail', () {
    test('fromJson parses with messages', () {
      final json = {
        'id': 5,
        'title': 'Test Session',
        'agent_slug': 'valuator',
        'messages': [
          {'role': 'user', 'content': 'Value my car'},
          {'role': 'assistant', 'content': 'Your car is worth...'},
        ],
      };

      final detail = SessionDetail.fromJson(json);

      expect(detail.id, 5);
      expect(detail.title, 'Test Session');
      expect(detail.agentSlug, 'valuator');
      expect(detail.messages, hasLength(2));
      expect(detail.messages[0].role, 'user');
      expect(detail.messages[1].role, 'assistant');
    });

    test('fromJson handles empty messages', () {
      final json = {'id': 1, 'title': 'Empty', 'messages': []};

      final detail = SessionDetail.fromJson(json);
      expect(detail.messages, isEmpty);
    });
  });

  group('ShareResponse', () {
    test('fromJson parses correctly', () {
      final json = {
        'token': 'abc123',
        'url': 'https://carhero.chat/shared/abc123',
      };

      final share = ShareResponse.fromJson(json);

      expect(share.token, 'abc123');
      expect(share.url, 'https://carhero.chat/shared/abc123');
    });
  });
}
