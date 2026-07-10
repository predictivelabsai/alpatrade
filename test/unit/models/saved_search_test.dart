import 'package:flutter_test/flutter_test.dart';
import 'package:carhero/models/saved_search.dart';

void main() {
  group('SavedSearch', () {
    test('fromJson parses all fields', () {
      final json = {
        'id': 1,
        'name': 'BMW 3 Series under 40k',
        'filters': {'make': 'BMW', 'model': '3 Series', 'max_price': 40000},
        'last_count': 25,
        'notify_email': true,
        'created_at': '2024-03-15T10:00:00Z',
      };

      final search = SavedSearch.fromJson(json);

      expect(search.id, 1);
      expect(search.name, 'BMW 3 Series under 40k');
      expect(search.filters['make'], 'BMW');
      expect(search.filters['max_price'], 40000);
      expect(search.lastCount, 25);
      expect(search.notifyEmail, true);
      expect(search.createdAt, '2024-03-15T10:00:00Z');
    });

    test('fromJson handles minimal data', () {
      final json = {'id': 2, 'name': 'Test'};

      final search = SavedSearch.fromJson(json);

      expect(search.filters, isEmpty);
      expect(search.lastCount, 0);
      expect(search.notifyEmail, false);
      expect(search.createdAt, '');
    });
  });
}
