class DailyScanStats {
  final int totalActive;
  final int freshCount;
  final int newCount;
  final int providersScraped;
  final int countriesCovered;
  final String? lastScrape;

  const DailyScanStats({
    this.totalActive = 0,
    this.freshCount = 0,
    this.newCount = 0,
    this.providersScraped = 0,
    this.countriesCovered = 0,
    this.lastScrape,
  });

  factory DailyScanStats.fromJson(Map<String, dynamic> json) => DailyScanStats(
    totalActive: (json['total_active'] as num?)?.toInt() ?? 0,
    freshCount: (json['fresh_count'] as num?)?.toInt() ?? 0,
    newCount: (json['new_count'] as num?)?.toInt() ?? 0,
    providersScraped: (json['providers_scraped'] as num?)?.toInt() ?? 0,
    countriesCovered: (json['countries_covered'] as num?)?.toInt() ?? 0,
    lastScrape: json['last_scrape'] as String?,
  );
}

class PriceComparison {
  final String make;
  final String model;
  final int year;
  final int listingCount;
  final int sourceCount;
  final double minPrice;
  final double maxPrice;
  final double avgPrice;
  final double savingsEur;
  final double savingsPct;
  final double cheapPrice;
  final String? cheapCountry;
  final String? cheapProvider;
  final String? cheapUrl;
  final int? cheapKm;
  final double expensivePrice;
  final String? expensiveCountry;
  final String? expensiveProvider;
  final String? expensiveUrl;

  const PriceComparison({
    required this.make,
    required this.model,
    required this.year,
    this.listingCount = 0,
    this.sourceCount = 0,
    this.minPrice = 0,
    this.maxPrice = 0,
    this.avgPrice = 0,
    this.savingsEur = 0,
    this.savingsPct = 0,
    this.cheapPrice = 0,
    this.cheapCountry,
    this.cheapProvider,
    this.cheapUrl,
    this.cheapKm,
    this.expensivePrice = 0,
    this.expensiveCountry,
    this.expensiveProvider,
    this.expensiveUrl,
  });

  factory PriceComparison.fromJson(Map<String, dynamic> json) =>
      PriceComparison(
        make: json['make'] as String? ?? '',
        model: json['model'] as String? ?? '',
        year: (json['year'] as num?)?.toInt() ?? 0,
        listingCount: (json['listing_count'] as num?)?.toInt() ?? 0,
        sourceCount: (json['source_count'] as num?)?.toInt() ?? 0,
        minPrice: (json['min_price'] as num?)?.toDouble() ?? 0,
        maxPrice: (json['max_price'] as num?)?.toDouble() ?? 0,
        avgPrice: (json['avg_price'] as num?)?.toDouble() ?? 0,
        savingsEur: (json['savings_eur'] as num?)?.toDouble() ?? 0,
        savingsPct: (json['savings_pct'] as num?)?.toDouble() ?? 0,
        cheapPrice: (json['cheap_price'] as num?)?.toDouble() ?? 0,
        cheapCountry: json['cheap_country'] as String?,
        cheapProvider: json['cheap_provider'] as String?,
        cheapUrl: json['cheap_url'] as String?,
        cheapKm: (json['cheap_km'] as num?)?.toInt(),
        expensivePrice: (json['expensive_price'] as num?)?.toDouble() ?? 0,
        expensiveCountry: json['expensive_country'] as String?,
        expensiveProvider: json['expensive_provider'] as String?,
        expensiveUrl: json['expensive_url'] as String?,
      );
}

class PriceDrop {
  final String make;
  final String model;
  final String? variant;
  final int year;
  final int? mileageKm;
  final double priceEur;
  final double oldPrice;
  final double dropEur;
  final double dropPct;
  final String? country;
  final String? provider;
  final String? fuelType;
  final String? sourceUrl;

  const PriceDrop({
    required this.make,
    required this.model,
    this.variant,
    required this.year,
    this.mileageKm,
    this.priceEur = 0,
    this.oldPrice = 0,
    this.dropEur = 0,
    this.dropPct = 0,
    this.country,
    this.provider,
    this.fuelType,
    this.sourceUrl,
  });

  factory PriceDrop.fromJson(Map<String, dynamic> json) => PriceDrop(
    make: json['make'] as String? ?? '',
    model: json['model'] as String? ?? '',
    variant: json['variant'] as String?,
    year: (json['year'] as num?)?.toInt() ?? 0,
    mileageKm: (json['mileage_km'] as num?)?.toInt(),
    priceEur: (json['price_eur'] as num?)?.toDouble() ?? 0,
    oldPrice: (json['old_price'] as num?)?.toDouble() ?? 0,
    dropEur: (json['drop_eur'] as num?)?.toDouble() ?? 0,
    dropPct: (json['drop_pct'] as num?)?.toDouble() ?? 0,
    country: json['country'] as String?,
    provider: json['provider'] as String?,
    fuelType: json['fuel_type'] as String?,
    sourceUrl: json['source_url'] as String?,
  );
}

class DailyScanData {
  final DailyScanStats stats;
  final List<PriceComparison> comparisons;
  final List<PriceDrop> priceDrops;

  const DailyScanData({
    required this.stats,
    required this.comparisons,
    required this.priceDrops,
  });

  factory DailyScanData.fromJson(Map<String, dynamic> json) => DailyScanData(
    stats: DailyScanStats.fromJson(
      (json['stats'] as Map?)?.cast<String, dynamic>() ?? {},
    ),
    comparisons: (json['comparisons'] as List<dynamic>? ?? [])
        .map(
          (e) => PriceComparison.fromJson((e as Map).cast<String, dynamic>()),
        )
        .toList(),
    priceDrops: (json['price_drops'] as List<dynamic>? ?? [])
        .map((e) => PriceDrop.fromJson((e as Map).cast<String, dynamic>()))
        .toList(),
  );
}
