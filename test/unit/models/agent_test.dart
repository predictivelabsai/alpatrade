import 'package:flutter_test/flutter_test.dart';
import 'package:carhero/models/agent.dart';

void main() {
  group('AgentOut', () {
    test('fromJson parses all fields', () {
      final json = {
        'slug': 'search',
        'name': 'Car Search Agent',
        'category': 'core',
        'icon': 'search',
        'one_liner': 'Find your perfect car',
        'prefix': '/search',
        'example_prompts': [
          'Find BMW 3 Series under 40k',
          'Show me Porsche 911s in Germany',
        ],
      };

      final agent = AgentOut.fromJson(json);

      expect(agent.slug, 'search');
      expect(agent.name, 'Car Search Agent');
      expect(agent.category, 'core');
      expect(agent.icon, 'search');
      expect(agent.oneLiner, 'Find your perfect car');
      expect(agent.prefix, '/search');
      expect(agent.examplePrompts, hasLength(2));
      expect(agent.examplePrompts[0], 'Find BMW 3 Series under 40k');
    });

    test('fromJson handles empty example prompts', () {
      final json = {
        'slug': 'advisor',
        'name': 'Advisor',
        'category': 'core',
        'icon': 'help',
        'one_liner': 'Get advice',
        'prefix': '/advisor',
        'example_prompts': [],
      };

      final agent = AgentOut.fromJson(json);
      expect(agent.examplePrompts, isEmpty);
    });
  });
}
