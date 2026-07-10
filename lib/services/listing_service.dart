import 'package:carhero/models/listing.dart';
import 'package:carhero/services/api_client.dart';

class ListingService {
  final ApiClient _client;

  ListingService(this._client);

  Future<List<CarListing>> search({
    String? make,
    String? model,
    int? minPrice,
    int? maxPrice,
    int? minYear,
    int? maxYear,
    int? maxMileage,
    String? fuelType,
    String? transmission,
    String? bodyType,
    String? country,
    int limit = 20,
  }) async {
    final params = <String, dynamic>{'limit': limit};
    if (make != null) params['make'] = make;
    if (model != null) params['model'] = model;
    if (minPrice != null) params['min_price'] = minPrice;
    if (maxPrice != null) params['max_price'] = maxPrice;
    if (minYear != null) params['min_year'] = minYear;
    if (maxYear != null) params['max_year'] = maxYear;
    if (maxMileage != null) params['max_mileage'] = maxMileage;
    if (fuelType != null) params['fuel_type'] = fuelType;
    if (transmission != null) params['transmission'] = transmission;
    if (bodyType != null) params['body_type'] = bodyType;
    if (country != null) params['country'] = country;

    final data = await _client.getList(
      '/listings/search',
      queryParameters: params,
    );
    return data
        .map((e) => CarListing.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<CarListing> getDetail(int listingId) async {
    final json = await _client.get('/listings/$listingId');
    return CarListing.fromJson(json);
  }

  Future<List<CarListing>> trending({int limit = 20}) async {
    final data = await _client.getList(
      '/listings/trending',
      queryParameters: {'limit': limit},
    );
    return data
        .map((e) => CarListing.fromJson(e as Map<String, dynamic>))
        .toList();
  }
}
