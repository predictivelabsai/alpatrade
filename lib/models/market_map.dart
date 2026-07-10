class TreemapItem {
  final String make;
  final String model;
  final int listingCount;
  final double avgPrice;
  final double priceSpreadPct;

  const TreemapItem({
    required this.make,
    required this.model,
    this.listingCount = 0,
    this.avgPrice = 0,
    this.priceSpreadPct = 0,
  });

  factory TreemapItem.fromJson(Map<String, dynamic> json) => TreemapItem(
    make: json['make'] as String,
    model: json['model'] as String,
    listingCount: json['listing_count'] as int? ?? 0,
    avgPrice: (json['avg_price'] as num?)?.toDouble() ?? 0,
    priceSpreadPct: (json['price_spread_pct'] as num?)?.toDouble() ?? 0,
  );
}

class TrendItem {
  final int year;
  final String make;
  final double avgPrice;
  final int listings;

  const TrendItem({
    required this.year,
    required this.make,
    this.avgPrice = 0,
    this.listings = 0,
  });

  factory TrendItem.fromJson(Map<String, dynamic> json) => TrendItem(
    year: json['year'] as int,
    make: json['make'] as String,
    avgPrice: (json['avg_price'] as num?)?.toDouble() ?? 0,
    listings: json['listings'] as int? ?? 0,
  );
}

class GeoItem {
  final String country;
  final String provider;
  final int listings;
  final double avgPrice;
  final double medianPrice;

  const GeoItem({
    required this.country,
    this.provider = '',
    this.listings = 0,
    this.avgPrice = 0,
    this.medianPrice = 0,
  });

  factory GeoItem.fromJson(Map<String, dynamic> json) => GeoItem(
    country: json['country'] as String,
    provider: json['provider'] as String? ?? '',
    listings: json['listings'] as int? ?? 0,
    avgPrice: (json['avg_price'] as num?)?.toDouble() ?? 0,
    medianPrice: (json['median_price'] as num?)?.toDouble() ?? 0,
  );
}

class ValueMapItem {
  final String make;
  final String model;
  final int listingCount;
  final double medianPrice;
  final double avgScore;

  const ValueMapItem({
    required this.make,
    required this.model,
    this.listingCount = 0,
    this.medianPrice = 0,
    this.avgScore = 0,
  });

  factory ValueMapItem.fromJson(Map<String, dynamic> json) => ValueMapItem(
    make: json['make'] as String,
    model: json['model'] as String,
    listingCount: json['listing_count'] as int? ?? 0,
    medianPrice: (json['median_price'] as num?)?.toDouble() ?? 0,
    avgScore: (json['avg_score'] as num?)?.toDouble() ?? 0,
  );
}

class PriceIndexItem {
  final int year;
  final String make;
  final double indexValue;
  final int listings;

  const PriceIndexItem({
    required this.year,
    required this.make,
    this.indexValue = 0,
    this.listings = 0,
  });

  factory PriceIndexItem.fromJson(Map<String, dynamic> json) => PriceIndexItem(
    year: json['year'] as int,
    make: json['make'] as String,
    indexValue: (json['index_value'] as num?)?.toDouble() ?? 0,
    listings: json['listings'] as int? ?? 0,
  );
}

class MarketFilters {
  final List<String> countries;
  final List<String> makes;
  final List<String> fuelTypes;

  const MarketFilters({
    this.countries = const [],
    this.makes = const [],
    this.fuelTypes = const [],
  });

  factory MarketFilters.fromJson(Map<String, dynamic> json) => MarketFilters(
    countries:
        (json['countries'] as List<dynamic>?)
            ?.map((e) => e as String)
            .toList() ??
        const [],
    makes:
        (json['makes'] as List<dynamic>?)?.map((e) => e as String).toList() ??
        const [],
    fuelTypes:
        (json['fuel_types'] as List<dynamic>?)
            ?.map((e) => e as String)
            .toList() ??
        const [],
  );
}
