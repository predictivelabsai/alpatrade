import 'package:flutter_test/flutter_test.dart';
import 'package:carhero/models/chat.dart';

void main() {
  group('ChatRequest', () {
    test('toJson includes all fields', () {
      const req = ChatRequest(message: 'Find BMWs', sessionId: 5, lang: 'de');
      final json = req.toJson();

      expect(json['message'], 'Find BMWs');
      expect(json['session_id'], 5);
      expect(json['lang'], 'de');
    });

    test('toJson omits null sessionId', () {
      const req = ChatRequest(message: 'Hello');
      final json = req.toJson();

      expect(json.containsKey('session_id'), false);
      expect(json['lang'], 'en');
    });
  });

  group('parseSseEvent', () {
    test('parses session event', () {
      final event = parseSseEvent('session', {'sid': 42});
      expect(event, isA<SessionEvent>());
      expect((event as SessionEvent).sid, 42);
    });

    test('parses agent_route event', () {
      final event = parseSseEvent('agent_route', {
        'slug': 'search',
        'agent': 'Car Search',
        'icon': 'search',
      });
      expect(event, isA<AgentRouteEvent>());
      final e = event as AgentRouteEvent;
      expect(e.slug, 'search');
      expect(e.name, 'Car Search');
      expect(e.icon, 'search');
    });

    test('parses token event', () {
      final event = parseSseEvent('token', {'text': 'Hello '});
      expect(event, isA<TokenEvent>());
      expect((event as TokenEvent).text, 'Hello ');
    });

    test('parses tool_start event', () {
      final event = parseSseEvent('tool_start', {
        'name': 'search_listings',
        'args': {'make': 'BMW'},
      });
      expect(event, isA<ToolStartEvent>());
      final e = event as ToolStartEvent;
      expect(e.name, 'search_listings');
      expect(e.args['make'], 'BMW');
    });

    test('parses tool_start with null args', () {
      final event = parseSseEvent('tool_start', {'name': 'fetch'});
      expect(event, isA<ToolStartEvent>());
      expect((event as ToolStartEvent).args, isEmpty);
    });

    test('parses tool_end event', () {
      final event = parseSseEvent('tool_end', {
        'name': 'search_listings',
        'output': '5 results found',
      });
      expect(event, isA<ToolEndEvent>());
      final e = event as ToolEndEvent;
      expect(e.name, 'search_listings');
      expect(e.output, '5 results found');
    });

    test('parses tool_end with null output', () {
      final event = parseSseEvent('tool_end', {'name': 'fetch'});
      expect(event, isA<ToolEndEvent>());
      expect((event as ToolEndEvent).output, '');
    });

    test('parses artifact_show event', () {
      final data = {'kind': 'listings', 'title': 'Results', 'items': []};
      final event = parseSseEvent('artifact_show', data);
      expect(event, isA<ArtifactEvent>());
      expect((event as ArtifactEvent).payload, data);
    });

    test('parses done event', () {
      final event = parseSseEvent('done', {'slug': 'search', 'tools': 3});
      expect(event, isA<DoneEvent>());
      final e = event as DoneEvent;
      expect(e.slug, 'search');
      expect(e.toolCount, 3);
    });

    test('parses done event with null tools', () {
      final event = parseSseEvent('done', {'slug': 'search'});
      expect((event as DoneEvent).toolCount, 0);
    });

    test('parses error event', () {
      final event = parseSseEvent('error', {'message': 'Rate limit'});
      expect(event, isA<ErrorEvent>());
      expect((event as ErrorEvent).message, 'Rate limit');
    });

    test('parses error with null message', () {
      final event = parseSseEvent('error', {});
      expect((event as ErrorEvent).message, 'Unknown error');
    });

    test('returns ErrorEvent for unknown event type', () {
      final event = parseSseEvent('unknown_event', {});
      expect(event, isA<ErrorEvent>());
      expect((event as ErrorEvent).message, contains('Unknown event'));
    });
  });

  group('ChatMessage', () {
    test('copyWith updates content', () {
      const msg = ChatMessage(role: 'user', content: 'Hello');
      final updated = msg.copyWith(content: 'Updated');

      expect(updated.content, 'Updated');
      expect(updated.role, 'user');
    });

    test('copyWith preserves existing values', () {
      const msg = ChatMessage(
        role: 'assistant',
        content: 'Hi',
        agentSlug: 'search',
        toolCalls: [ToolCall(name: 'fetch', args: {})],
      );
      final updated = msg.copyWith(content: 'New');

      expect(updated.agentSlug, 'search');
      expect(updated.toolCalls, hasLength(1));
    });
  });

  group('ToolCall', () {
    test('withOutput creates new instance', () {
      const tc = ToolCall(name: 'search', args: {'q': 'bmw'});
      final withOut = tc.withOutput('found 5');

      expect(withOut.output, 'found 5');
      expect(withOut.name, 'search');
      expect(withOut.args['q'], 'bmw');
      expect(tc.output, isNull);
    });
  });

  group('Artifact', () {
    test('fromJson parses correctly', () {
      final json = {'kind': 'chart', 'title': 'Price Trends', 'data': []};
      final artifact = Artifact.fromJson(json);

      expect(artifact.kind, 'chart');
      expect(artifact.title, 'Price Trends');
      expect(artifact.data, json);
    });

    test('fromJson handles missing kind', () {
      final artifact = Artifact.fromJson({'title': 'X'});
      expect(artifact.kind, 'unknown');
    });

    test('fromJson handles missing title', () {
      final artifact = Artifact.fromJson({'kind': 'table'});
      expect(artifact.title, isNull);
    });
  });

  group('ChatState', () {
    test('initial has correct defaults', () {
      final state = ChatState.initial();

      expect(state.messages, isEmpty);
      expect(state.currentSessionId, isNull);
      expect(state.currentAgent, isNull);
      expect(state.isStreaming, false);
      expect(state.streamBuffer, '');
      expect(state.activeToolCalls, isEmpty);
      expect(state.artifacts, isEmpty);
      expect(state.error, isNull);
    });

    test('copyWith updates selected fields', () {
      final state = ChatState.initial();
      final updated = state.copyWith(isStreaming: true, currentSessionId: 7);

      expect(updated.isStreaming, true);
      expect(updated.currentSessionId, 7);
      expect(updated.messages, isEmpty);
    });
  });
}
