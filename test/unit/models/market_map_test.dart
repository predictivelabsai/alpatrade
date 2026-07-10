import 'package:flutter_test/flutter_test.dart';
import 'package:carhero/models/market_map.dart';

void main() {
  group('TreemapItem', () {
    test('fromJson parses correctly', () {
      final json = {
        'make': 'BMW',
        'model': '3 Series',
        'listing_count': 150,
        'avg_price': 42500.0,
        'price_spread_pct': 25.3,
      };

      final item = TreemapItem.fromJson(json);

      expect(item.make, 'BMW');
      expect(item.model, '3 Series');
      expect(item.listingCount, 150);
      expect(item.avgPrice, 42500.0);
      expect(item.priceSpreadPct, 25.3);
    });

    test('fromJson handles missing numerics', () {
      final item = TreemapItem.fromJson({'make': 'A', 'model': 'B'});

      expect(item.listingCount, 0);
      expect(item.avgPrice, 0);
      expect(item.priceSpreadPct, 0);
    });
  });

  group('TrendItem', () {
    test('fromJson parses correctly', () {
      final json = {
        'year': 2020,
        'make': 'Porsche',
        'avg_price': 85000.0,
        'listings': 45,
      };

      final item = TrendItem.fromJson(json);

      expect(item.year, 2020);
      expect(item.make, 'Porsche');
      expect(item.avgPrice, 85000.0);
      expect(item.listings, 45);
    });
  });

  group('GeoItem', () {
    test('fromJson parses correctly', () {
      final json = {
        'country': 'Germany',
        'provider': 'AutoScout24',
        'listings': 5000,
        'avg_price': 38000.0,
        'median_price': 35000.0,
      };

      final item = GeoItem.fromJson(json);

      expect(item.country, 'Germany');
      expect(item.provider, 'AutoScout24');
      expect(item.listings, 5000);
      expect(item.avgPrice, 38000.0);
      expect(item.medianPrice, 35000.0);
    });

    test('fromJson handles defaults', () {
      final item = GeoItem.fromJson({'country': 'Estonia'});

      expect(item.provider, '');
      expect(item.listings, 0);
      expect(item.avgPrice, 0);
      expect(item.medianPrice, 0);
    });
  });

  group('ValueMapItem', () {
    test('fromJson parses correctly', () {
      final json = {
        'make': 'Mercedes-Benz',
        'model': 'E-Class',
        'listing_count': 80,
        'median_price': 42000.0,
        'avg_score': 72.5,
      };

      final item = ValueMapItem.fromJson(json);

      expect(item.make, 'Mercedes-Benz');
      expect(item.model, 'E-Class');
      expect(item.listingCount, 80);
      expect(item.medianPrice, 42000.0);
      expect(item.avgScore, 72.5);
    });
  });

  group('PriceIndexItem', () {
    test('fromJson parses correctly', () {
      final json = {
        'year': 2019,
        'make': 'Audi',
        'index_value': 87.5,
        'listings': 120,
      };

      final item = PriceIndexItem.fromJson(json);

      expect(item.year, 2019);
      expect(item.make, 'Audi');
      expect(item.indexValue, 87.5);
      expect(item.listings, 120);
    });
  });

  group('MarketFilters', () {
    test('fromJson parses lists', () {
      final json = {
        'countries': ['Germany', 'France', 'Netherlands'],
        'makes': ['BMW', 'Audi', 'Mercedes-Benz'],
        'fuel_types': ['Petrol', 'Diesel', 'Electric'],
      };

      final filters = MarketFilters.fromJson(json);

      expect(filters.countries, hasLength(3));
      expect(filters.makes, hasLength(3));
      expect(filters.fuelTypes, hasLength(3));
      expect(filters.countries.first, 'Germany');
    });

    test('fromJson handles null lists', () {
      final filters = MarketFilters.fromJson({});

      expect(filters.countries, isEmpty);
      expect(filters.makes, isEmpty);
      expect(filters.fuelTypes, isEmpty);
    });
  });
}
