import 'package:flutter_test/flutter_test.dart';
import 'package:alpatrade/models/chat.dart';

void main() {
  group('ChatRequest', () {
    test('serializes msg and thread_id', () {
      final json = const ChatRequest(msg: 'hi', threadId: 'm1').toJson();
      expect(json['msg'], 'hi');
      expect(json['thread_id'], 'm1');
    });

    test('omits thread_id when null', () {
      final json = const ChatRequest(msg: 'hi').toJson();
      expect(json.containsKey('thread_id'), isFalse);
    });
  });

  group('parseSseEvent', () {
    test('session -> SessionEvent with string sid', () {
      final e = parseSseEvent('session', {'sid': 'm1'});
      expect(e, isA<SessionEvent>());
      expect((e as SessionEvent).sid, 'm1');
    });

    test('coerces non-string sid to string', () {
      final e = parseSseEvent('session', {'sid': 42});
      expect((e as SessionEvent).sid, '42');
    });

    test('token -> TokenEvent', () {
      final e = parseSseEvent('token', {'text': 'hello'});
      expect((e as TokenEvent).text, 'hello');
    });

    test('agent_route -> AgentRouteEvent', () {
      final e = parseSseEvent('agent_route', {
        'slug': 'ai',
        'agent': 'AlpaTrade AI',
      });
      expect(e, isA<AgentRouteEvent>());
      expect((e as AgentRouteEvent).name, 'AlpaTrade AI');
    });

    test('tool_start / tool_end', () {
      expect(
        (parseSseEvent('tool_start', {'name': 'get_alpaca_positions'})
                as ToolStartEvent)
            .name,
        'get_alpaca_positions',
      );
      expect(
        (parseSseEvent('tool_end', {'name': 'get_alpaca_positions'})
                as ToolEndEvent)
            .name,
        'get_alpaca_positions',
      );
    });

    test('done -> DoneEvent', () {
      expect(parseSseEvent('done', {}), isA<DoneEvent>());
    });

    test('error -> ErrorEvent with message', () {
      final e = parseSseEvent('error', {'message': 'boom'});
      expect((e as ErrorEvent).message, 'boom');
    });

    test('unknown event -> ErrorEvent', () {
      expect(parseSseEvent('nope', {}), isA<ErrorEvent>());
    });
  });

  group('ToolCall', () {
    test('complete() marks done', () {
      const t = ToolCall(name: 'x');
      expect(t.done, isFalse);
      expect(t.complete().done, isTrue);
    });
  });
}
