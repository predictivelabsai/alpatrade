import 'package:flutter_test/flutter_test.dart';
import 'package:carhero/utils/formatters.dart';

void main() {
  group('Fmt.price', () {
    test('formats standard price', () {
      expect(Fmt.price(45000.0), 'EUR 45,000');
    });

    test('formats large price', () {
      expect(Fmt.price(1250000.0), 'EUR 1,250,000');
    });

    test('formats small price', () {
      expect(Fmt.price(500.0), 'EUR 500');
    });

    test('rounds decimal prices', () {
      expect(Fmt.price(45999.99), 'EUR 46,000');
    });

    test('returns N/A for null', () {
      expect(Fmt.price(null), 'N/A');
    });
  });

  group('Fmt.mileage', () {
    test('formats standard mileage', () {
      expect(Fmt.mileage(125000), '125,000 km');
    });

    test('formats small mileage', () {
      expect(Fmt.mileage(500), '500 km');
    });

    test('returns empty for null', () {
      expect(Fmt.mileage(null), '');
    });
  });

  group('Fmt.priceChange', () {
    test('formats positive change with plus sign', () {
      expect(Fmt.priceChange(5000), '+5,000 EUR');
    });

    test('formats negative change', () {
      expect(Fmt.priceChange(-3000), '-3,000 EUR');
    });

    test('returns empty for null', () {
      expect(Fmt.priceChange(null), '');
    });

    test('returns empty for zero', () {
      expect(Fmt.priceChange(0), '');
    });
  });

  group('Fmt.dateShort', () {
    test('formats ISO date', () {
      final result = Fmt.dateShort('2024-03-15T10:30:00Z');
      expect(result, contains('Mar'));
      expect(result, contains('15'));
      expect(result, contains('2024'));
    });

    test('returns empty for null', () {
      expect(Fmt.dateShort(null), '');
    });

    test('returns empty for empty string', () {
      expect(Fmt.dateShort(''), '');
    });

    test('returns original for invalid date', () {
      expect(Fmt.dateShort('not-a-date'), 'not-a-date');
    });
  });
}
