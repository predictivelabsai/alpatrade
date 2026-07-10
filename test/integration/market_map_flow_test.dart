import 'package:flutter_test/flutter_test.dart';
import 'package:carhero/models/market_map.dart';

void main() {
  group('Market map flow integration', () {
    test('filters load and can be used to query data', () {
      // 1. Load filters
      final filters = MarketFilters.fromJson({
        'countries': ['Germany', 'France', 'Netherlands', 'Sweden'],
        'makes': ['BMW', 'Audi', 'Mercedes-Benz', 'Porsche', 'Volvo'],
        'fuel_types': ['Petrol', 'Diesel', 'Electric', 'Hybrid'],
      });

      expect(filters.countries, hasLength(4));
      expect(filters.makes, hasLength(5));
      expect(filters.fuelTypes, hasLength(4));

      // 2. User selects filters
      String? selectedCountry = 'Germany';
      String? selectedMake = 'BMW';
      expect(filters.countries.contains(selectedCountry), true);
      expect(filters.makes.contains(selectedMake), true);
    });

    test('treemap data groups by make and model', () {
      final treemapData = [
        TreemapItem.fromJson({
          'make': 'BMW',
          'model': '3 Series',
          'listing_count': 150,
          'avg_price': 42500.0,
          'price_spread_pct': 25.3,
        }),
        TreemapItem.fromJson({
          'make': 'BMW',
          'model': '5 Series',
          'listing_count': 120,
          'avg_price': 55000.0,
          'price_spread_pct': 22.1,
        }),
        TreemapItem.fromJson({
          'make': 'Audi',
          'model': 'A4',
          'listing_count': 130,
          'avg_price': 38000.0,
          'price_spread_pct': 28.5,
        }),
      ];

      // Group by make
      final byMake = <String, List<TreemapItem>>{};
      for (final item in treemapData) {
        byMake.putIfAbsent(item.make, () => []).add(item);
      }

      expect(byMake.keys, containsAll(['BMW', 'Audi']));
      expect(byMake['BMW'], hasLength(2));
      expect(byMake['Audi'], hasLength(1));

      // Total listings
      final totalListings = treemapData.fold<int>(
        0,
        (sum, item) => sum + item.listingCount,
      );
      expect(totalListings, 400);
    });

    test('trend data shows depreciation curves', () {
      final trendData = [
        TrendItem.fromJson({
          'year': 2024,
          'make': 'BMW',
          'avg_price': 52000.0,
          'listings': 50,
        }),
        TrendItem.fromJson({
          'year': 2023,
          'make': 'BMW',
          'avg_price': 48000.0,
          'listings': 80,
        }),
        TrendItem.fromJson({
          'year': 2022,
          'make': 'BMW',
          'avg_price': 43000.0,
          'listings': 120,
        }),
        TrendItem.fromJson({
          'year': 2021,
          'make': 'BMW',
          'avg_price': 38000.0,
          'listings': 150,
        }),
        TrendItem.fromJson({
          'year': 2020,
          'make': 'BMW',
          'avg_price': 33000.0,
          'listings': 130,
        }),
      ];

      // Prices should decrease with age
      for (int i = 0; i < trendData.length - 1; i++) {
        expect(trendData[i].avgPrice, greaterThan(trendData[i + 1].avgPrice));
      }

      // Years should be ordered
      final years = trendData.map((t) => t.year).toList();
      expect(years, orderedEquals([2024, 2023, 2022, 2021, 2020]));
    });

    test('geo data shows price differences by country', () {
      final geoData = [
        GeoItem.fromJson({
          'country': 'Germany',
          'listings': 5000,
          'avg_price': 38000.0,
          'median_price': 35000.0,
        }),
        GeoItem.fromJson({
          'country': 'France',
          'listings': 3000,
          'avg_price': 35000.0,
          'median_price': 33000.0,
        }),
        GeoItem.fromJson({
          'country': 'Sweden',
          'listings': 1500,
          'avg_price': 42000.0,
          'median_price': 40000.0,
        }),
      ];

      // Germany should have most listings
      final sorted = [...geoData]
        ..sort((a, b) => b.listings.compareTo(a.listings));
      expect(sorted.first.country, 'Germany');

      // Sweden has highest avg price
      final byCost = [...geoData]
        ..sort((a, b) => b.avgPrice.compareTo(a.avgPrice));
      expect(byCost.first.country, 'Sweden');
    });

    test('value map items for scatter chart', () {
      final valueData = [
        ValueMapItem.fromJson({
          'make': 'BMW',
          'model': '330i',
          'listing_count': 50,
          'median_price': 35000.0,
          'avg_score': 72.0,
        }),
        ValueMapItem.fromJson({
          'make': 'Porsche',
          'model': '911',
          'listing_count': 20,
          'median_price': 95000.0,
          'avg_score': 85.0,
        }),
        ValueMapItem.fromJson({
          'make': 'Fiat',
          'model': '500',
          'listing_count': 80,
          'median_price': 12000.0,
          'avg_score': 45.0,
        }),
      ];

      // Find highest value (best score relative to price)
      final bestValue = valueData.reduce(
        (a, b) =>
            (a.avgScore / a.medianPrice) > (b.avgScore / b.medianPrice) ? a : b,
      );
      expect(bestValue.make, 'Fiat');

      // Premium segment
      final premium = valueData.where((v) => v.medianPrice > 50000).toList();
      expect(premium, hasLength(1));
      expect(premium[0].make, 'Porsche');
    });

    test('price index items for trend line', () {
      final indexData = [
        PriceIndexItem.fromJson({
          'year': 2024,
          'make': 'Porsche',
          'index_value': 105.0,
          'listings': 30,
        }),
        PriceIndexItem.fromJson({
          'year': 2023,
          'make': 'Porsche',
          'index_value': 100.0,
          'listings': 50,
        }),
        PriceIndexItem.fromJson({
          'year': 2022,
          'make': 'Porsche',
          'index_value': 92.0,
          'listings': 70,
        }),
        PriceIndexItem.fromJson({
          'year': 2021,
          'make': 'Porsche',
          'index_value': 85.0,
          'listings': 80,
        }),
      ];

      // 2023 is baseline (100.0)
      final baseline = indexData.firstWhere((i) => i.year == 2023);
      expect(baseline.indexValue, 100.0);

      // 2024 appreciates above baseline
      final latest = indexData.firstWhere((i) => i.year == 2024);
      expect(latest.indexValue, greaterThan(100));
    });
  });
}
