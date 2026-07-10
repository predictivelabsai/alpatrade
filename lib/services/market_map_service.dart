import 'package:carhero/models/market_map.dart';
import 'package:carhero/services/api_client.dart';

class MarketMapService {
  final ApiClient _client;

  MarketMapService(this._client);

  Future<MarketFilters> getFilters() async {
    final json = await _client.get('/market-map/filters');
    return MarketFilters.fromJson(json);
  }

  Future<List<TreemapItem>> getTreemap({
    String? country,
    String? make,
    String? fuelType,
  }) async {
    final params = <String, dynamic>{'format': 'data'};
    if (country != null) params['country'] = country;
    if (make != null) params['make'] = make;
    if (fuelType != null) params['fuel_type'] = fuelType;

    final json = await _client.get(
      '/market-map/treemap',
      queryParameters: params,
    );
    final data = json['data'] as List<dynamic>? ?? [];
    return data
        .map((e) => TreemapItem.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<List<TrendItem>> getTrends({
    String? country,
    String? make,
    String? fuelType,
  }) async {
    final params = <String, dynamic>{'format': 'data'};
    if (country != null) params['country'] = country;
    if (make != null) params['make'] = make;
    if (fuelType != null) params['fuel_type'] = fuelType;

    final json = await _client.get(
      '/market-map/trends',
      queryParameters: params,
    );
    final data = json['data'] as List<dynamic>? ?? [];
    return data
        .map((e) => TrendItem.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<List<GeoItem>> getGeo({String? make, String? model}) async {
    final params = <String, dynamic>{'format': 'data'};
    if (make != null) params['make'] = make;
    if (model != null) params['model'] = model;

    final json = await _client.get('/market-map/geo', queryParameters: params);
    final data = json['data'] as List<dynamic>? ?? [];
    return data
        .map((e) => GeoItem.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<List<ValueMapItem>> getValueMap({
    String? country,
    String? make,
    String? fuelType,
  }) async {
    final params = <String, dynamic>{'format': 'data'};
    if (country != null) params['country'] = country;
    if (make != null) params['make'] = make;
    if (fuelType != null) params['fuel_type'] = fuelType;

    final json = await _client.get(
      '/market-map/value-map',
      queryParameters: params,
    );
    final data = json['data'] as List<dynamic>? ?? [];
    return data
        .map((e) => ValueMapItem.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<List<PriceIndexItem>> getPriceIndex({
    String? make,
    String? baseYear,
  }) async {
    final params = <String, dynamic>{'format': 'data'};
    if (make != null) params['make'] = make;
    if (baseYear != null) params['base_year'] = baseYear;

    final json = await _client.get(
      '/market-map/price-index',
      queryParameters: params,
    );
    final data = json['data'] as List<dynamic>? ?? [];
    return data
        .map((e) => PriceIndexItem.fromJson(e as Map<String, dynamic>))
        .toList();
  }
}
