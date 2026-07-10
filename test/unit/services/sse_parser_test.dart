import 'package:flutter_test/flutter_test.dart';
import 'package:carhero/models/chat.dart';

void main() {
  group('SSE event parsing', () {
    test('parses all 8 event types correctly', () {
      final events = <String, Map<String, dynamic>>{
        'session': {'sid': 1},
        'agent_route': {'slug': 'search', 'agent': 'Search', 'icon': 'S'},
        'token': {'text': 'Hello'},
        'tool_start': {'name': 'fetch', 'args': {}},
        'tool_end': {'name': 'fetch', 'output': 'done'},
        'artifact_show': {'kind': 'listings'},
        'done': {'slug': 'search', 'tools': 2},
        'error': {'message': 'fail'},
      };

      expect(parseSseEvent('session', events['session']!), isA<SessionEvent>());
      expect(
        parseSseEvent('agent_route', events['agent_route']!),
        isA<AgentRouteEvent>(),
      );
      expect(parseSseEvent('token', events['token']!), isA<TokenEvent>());
      expect(
        parseSseEvent('tool_start', events['tool_start']!),
        isA<ToolStartEvent>(),
      );
      expect(
        parseSseEvent('tool_end', events['tool_end']!),
        isA<ToolEndEvent>(),
      );
      expect(
        parseSseEvent('artifact_show', events['artifact_show']!),
        isA<ArtifactEvent>(),
      );
      expect(parseSseEvent('done', events['done']!), isA<DoneEvent>());
      expect(parseSseEvent('error', events['error']!), isA<ErrorEvent>());
    });

    test('token accumulation', () {
      final tokens = ['Hello', ' world', '! How', ' are you?'];
      var buffer = '';

      for (final t in tokens) {
        final event = parseSseEvent('token', {'text': t});
        buffer += (event as TokenEvent).text;
      }

      expect(buffer, 'Hello world! How are you?');
    });

    test('tool lifecycle: start then end', () {
      final start =
          parseSseEvent('tool_start', {
                'name': 'search_listings',
                'args': {'make': 'BMW', 'max_price': 50000},
              })
              as ToolStartEvent;

      final end =
          parseSseEvent('tool_end', {
                'name': 'search_listings',
                'output': '15 listings found',
              })
              as ToolEndEvent;

      expect(start.name, end.name);
      expect(start.args['make'], 'BMW');
      expect(end.output, '15 listings found');
    });

    test('multiple tool calls tracked correctly', () {
      final tools = <ToolCall>[];

      final s1 =
          parseSseEvent('tool_start', {'name': 'search'}) as ToolStartEvent;
      tools.add(ToolCall(name: s1.name, args: s1.args));

      final s2 =
          parseSseEvent('tool_start', {'name': 'valuate'}) as ToolStartEvent;
      tools.add(ToolCall(name: s2.name, args: s2.args));

      final e1 =
          parseSseEvent('tool_end', {'name': 'search', 'output': 'ok'})
              as ToolEndEvent;
      final idx1 = tools.lastIndexWhere(
        (t) => t.name == e1.name && t.output == null,
      );
      tools[idx1] = tools[idx1].withOutput(e1.output);

      final e2 =
          parseSseEvent('tool_end', {'name': 'valuate', 'output': 'done'})
              as ToolEndEvent;
      final idx2 = tools.lastIndexWhere(
        (t) => t.name == e2.name && t.output == null,
      );
      tools[idx2] = tools[idx2].withOutput(e2.output);

      expect(tools[0].output, 'ok');
      expect(tools[1].output, 'done');
    });

    test('complete session flow produces correct state', () {
      final events = [
        parseSseEvent('session', {'sid': 42}),
        parseSseEvent('agent_route', {
          'slug': 'search',
          'agent': 'Car Search',
          'icon': 'S',
        }),
        parseSseEvent('tool_start', {
          'name': 'search_listings',
          'args': {'make': 'BMW'},
        }),
        parseSseEvent('tool_end', {
          'name': 'search_listings',
          'output': '10 found',
        }),
        parseSseEvent('token', {'text': 'I found '}),
        parseSseEvent('token', {'text': '10 BMWs'}),
        parseSseEvent('artifact_show', {
          'kind': 'listings',
          'title': 'Results',
        }),
        parseSseEvent('done', {'slug': 'search', 'tools': 1}),
      ];

      int? sessionId;
      String? agentSlug;
      var buffer = '';
      final toolCalls = <String>[];
      final artifacts = <Map<String, dynamic>>[];

      for (final event in events) {
        switch (event) {
          case SessionEvent(:final sid):
            sessionId = sid;
          case AgentRouteEvent(:final slug):
            agentSlug = slug;
          case TokenEvent(:final text):
            buffer += text;
          case ToolStartEvent(:final name):
            toolCalls.add(name);
          case ArtifactEvent(:final payload):
            artifacts.add(payload);
          case DoneEvent(:final slug, :final toolCount):
            expect(slug, 'search');
            expect(toolCount, 1);
          default:
            break;
        }
      }

      expect(sessionId, 42);
      expect(agentSlug, 'search');
      expect(buffer, 'I found 10 BMWs');
      expect(toolCalls, ['search_listings']);
      expect(artifacts, hasLength(1));
      expect(artifacts[0]['kind'], 'listings');
    });
  });
}
