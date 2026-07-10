import 'package:flutter_test/flutter_test.dart';
import 'package:carhero/models/analytics.dart';

void main() {
  group('AnalyticsResult', () {
    test('fromJson parses full result', () {
      final json = {
        'sql': 'SELECT make, COUNT(*) FROM listings GROUP BY make',
        'title': 'Listings by Make',
        'data': [
          {'make': 'BMW', 'count': 500},
          {'make': 'Audi', 'count': 450},
        ],
        'chart_type': 'bar',
        'x_column': 'make',
        'y_column': 'count',
        'color_column': 'make',
        'rows': 2,
      };

      final result = AnalyticsResult.fromJson(json);

      expect(result.sql, contains('SELECT'));
      expect(result.title, 'Listings by Make');
      expect(result.data, hasLength(2));
      expect(result.data![0]['make'], 'BMW');
      expect(result.chartType, 'bar');
      expect(result.xColumn, 'make');
      expect(result.yColumn, 'count');
      expect(result.colorColumn, 'make');
      expect(result.rows, 2);
    });

    test('fromJson handles empty result', () {
      final result = AnalyticsResult.fromJson({});

      expect(result.sql, '');
      expect(result.title, '');
      expect(result.data, isNull);
      expect(result.chartType, isNull);
      expect(result.xColumn, isNull);
      expect(result.yColumn, isNull);
      expect(result.rows, 0);
    });
  });
}
