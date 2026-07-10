class CarListing {
  final int id;
  final String make;
  final String model;
  final String variant;
  final int? year;
  final double? priceEur;
  final int? mileageKm;
  final String fuelType;
  final String transmission;
  final String bodyType;
  final int? powerHp;
  final String country;
  final String provider;
  final String sourceUrl;
  final List<String>? imageUrls;
  final int? investmentScore;
  final int? tier;

  const CarListing({
    required this.id,
    required this.make,
    required this.model,
    this.variant = '',
    this.year,
    this.priceEur,
    this.mileageKm,
    this.fuelType = '',
    this.transmission = '',
    this.bodyType = '',
    this.powerHp,
    this.country = '',
    this.provider = '',
    this.sourceUrl = '',
    this.imageUrls,
    this.investmentScore,
    this.tier,
  });

  factory CarListing.fromJson(Map<String, dynamic> json) => CarListing(
    id: json['id'] as int,
    make: json['make'] as String,
    model: json['model'] as String,
    variant: json['variant'] as String? ?? '',
    year: json['year'] as int?,
    priceEur: (json['price_eur'] as num?)?.toDouble(),
    mileageKm: json['mileage_km'] as int?,
    fuelType: json['fuel_type'] as String? ?? '',
    transmission: json['transmission'] as String? ?? '',
    bodyType: json['body_type'] as String? ?? '',
    powerHp: json['power_hp'] as int?,
    country: json['country'] as String? ?? '',
    provider: json['provider'] as String? ?? '',
    sourceUrl: json['source_url'] as String? ?? '',
    imageUrls: (json['image_urls'] as List<dynamic>?)
        ?.map((e) => e as String)
        .toList(),
    investmentScore: json['investment_score'] as int?,
    tier: json['tier'] as int?,
  );

  String get displayTitle =>
      '$make $model${variant.isNotEmpty ? ' $variant' : ''}';

  String get priceFormatted {
    if (priceEur == null) return 'N/A';
    return 'EUR ${priceEur!.toStringAsFixed(0).replaceAllMapped(RegExp(r'(\d)(?=(\d{3})+$)'), (m) => '${m[1]},')}';
  }

  String get mileageFormatted {
    if (mileageKm == null) return '';
    return '${mileageKm.toString().replaceAllMapped(RegExp(r'(\d)(?=(\d{3})+$)'), (m) => '${m[1]},')} km';
  }
}
