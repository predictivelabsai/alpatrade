class Favorite {
  final int id;
  final int listingId;
  final String make;
  final String model;
  final String variant;
  final int? year;
  final int? mileageKm;
  final int? priceEur;
  final int? priceAtSave;
  final int? priceChange;
  final String fuelType;
  final String transmission;
  final String country;
  final String provider;
  final String url;
  final String note;

  const Favorite({
    required this.id,
    required this.listingId,
    required this.make,
    required this.model,
    this.variant = '',
    this.year,
    this.mileageKm,
    this.priceEur,
    this.priceAtSave,
    this.priceChange,
    this.fuelType = '',
    this.transmission = '',
    this.country = '',
    this.provider = '',
    this.url = '',
    this.note = '',
  });

  factory Favorite.fromJson(Map<String, dynamic> json) => Favorite(
    id: json['id'] as int,
    listingId: json['listing_id'] as int,
    make: json['make'] as String,
    model: json['model'] as String,
    variant: json['variant'] as String? ?? '',
    year: json['year'] as int?,
    mileageKm: json['mileage_km'] as int?,
    priceEur: json['price_eur'] as int?,
    priceAtSave: json['price_at_save'] as int?,
    priceChange: json['price_change'] as int?,
    fuelType: json['fuel_type'] as String? ?? '',
    transmission: json['transmission'] as String? ?? '',
    country: json['country'] as String? ?? '',
    provider: json['provider'] as String? ?? '',
    url: json['url'] as String? ?? '',
    note: json['note'] as String? ?? '',
  );

  String get displayTitle =>
      '$make $model${variant.isNotEmpty ? ' $variant' : ''}';

  String get priceFormatted {
    if (priceEur == null) return 'N/A';
    return 'EUR ${priceEur.toString().replaceAllMapped(RegExp(r'(\d)(?=(\d{3})+$)'), (m) => '${m[1]},')}';
  }

  String get priceChangeFormatted {
    if (priceChange == null) return '';
    final sign = priceChange! > 0 ? '+' : '';
    return '$sign${priceChange.toString().replaceAllMapped(RegExp(r'(\d)(?=(\d{3})+$)'), (m) => '${m[1]},')} EUR';
  }
}
