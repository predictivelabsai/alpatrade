import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:carhero/models/market_map.dart';
import 'package:carhero/services/market_map_service.dart';
import 'package:carhero/providers/auth_provider.dart';

final marketMapServiceProvider = Provider<MarketMapService>((ref) {
  return MarketMapService(ref.read(apiClientProvider));
});

// Selected filter state
final marketCountryFilterProvider =
    NotifierProvider<MarketCountryFilter, String?>(MarketCountryFilter.new);

class MarketCountryFilter extends Notifier<String?> {
  @override
  String? build() => null;

  void set(String? value) {
    state = value;
  }
}

final marketMakeFilterProvider = NotifierProvider<MarketMakeFilter, String?>(
  MarketMakeFilter.new,
);

class MarketMakeFilter extends Notifier<String?> {
  @override
  String? build() => null;

  void set(String? value) {
    state = value;
  }
}

final marketFuelTypeFilterProvider =
    NotifierProvider<MarketFuelTypeFilter, String?>(MarketFuelTypeFilter.new);

class MarketFuelTypeFilter extends Notifier<String?> {
  @override
  String? build() => null;

  void set(String? value) {
    state = value;
  }
}

// Available filters
final marketFiltersProvider = FutureProvider<MarketFilters>((ref) async {
  final service = ref.read(marketMapServiceProvider);
  return service.getFilters();
});

// Treemap data - reacts to filter changes
final treemapProvider = FutureProvider<List<TreemapItem>>((ref) async {
  final service = ref.read(marketMapServiceProvider);
  final country = ref.watch(marketCountryFilterProvider);
  final make = ref.watch(marketMakeFilterProvider);
  final fuelType = ref.watch(marketFuelTypeFilterProvider);
  return service.getTreemap(country: country, make: make, fuelType: fuelType);
});

// Trends data
final trendsProvider = FutureProvider<List<TrendItem>>((ref) async {
  final service = ref.read(marketMapServiceProvider);
  final country = ref.watch(marketCountryFilterProvider);
  final make = ref.watch(marketMakeFilterProvider);
  final fuelType = ref.watch(marketFuelTypeFilterProvider);
  return service.getTrends(country: country, make: make, fuelType: fuelType);
});

// Geo distribution data
final geoProvider = FutureProvider<List<GeoItem>>((ref) async {
  final service = ref.read(marketMapServiceProvider);
  final make = ref.watch(marketMakeFilterProvider);
  return service.getGeo(make: make);
});

// Value map data
final valueMapProvider = FutureProvider<List<ValueMapItem>>((ref) async {
  final service = ref.read(marketMapServiceProvider);
  final country = ref.watch(marketCountryFilterProvider);
  final make = ref.watch(marketMakeFilterProvider);
  final fuelType = ref.watch(marketFuelTypeFilterProvider);
  return service.getValueMap(country: country, make: make, fuelType: fuelType);
});

// Price index data
final priceIndexProvider = FutureProvider<List<PriceIndexItem>>((ref) async {
  final service = ref.read(marketMapServiceProvider);
  final make = ref.watch(marketMakeFilterProvider);
  return service.getPriceIndex(make: make);
});
