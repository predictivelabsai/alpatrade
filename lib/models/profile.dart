class UserProfile {
  final String name;
  final String email;
  final String phone;
  final String country;
  final String city;
  final String currency;
  final String language;
  final double? budgetMinEur;
  final double? budgetMaxEur;
  final List<String> preferredMakes;
  final List<String> preferredBodyTypes;
  final List<String> preferredFuelTypes;
  final String? preferredTransmission;
  final int? maxMileageKm;
  final int? minYear;
  final int? maxYear;
  final bool notifyNewListings;
  final bool notifyPriceDrops;
  final bool notifyWeeklyDigest;

  const UserProfile({
    this.name = '',
    this.email = '',
    this.phone = '',
    this.country = '',
    this.city = '',
    this.currency = 'EUR',
    this.language = 'en',
    this.budgetMinEur,
    this.budgetMaxEur,
    this.preferredMakes = const [],
    this.preferredBodyTypes = const [],
    this.preferredFuelTypes = const [],
    this.preferredTransmission,
    this.maxMileageKm,
    this.minYear,
    this.maxYear,
    this.notifyNewListings = true,
    this.notifyPriceDrops = true,
    this.notifyWeeklyDigest = false,
  });

  factory UserProfile.fromJson(Map<String, dynamic> json) => UserProfile(
    name: json['name'] as String? ?? '',
    email: json['email'] as String? ?? '',
    phone: json['phone'] as String? ?? '',
    country: json['country'] as String? ?? '',
    city: json['city'] as String? ?? '',
    currency: json['currency'] as String? ?? 'EUR',
    language: json['language'] as String? ?? 'en',
    budgetMinEur: (json['budget_min_eur'] as num?)?.toDouble(),
    budgetMaxEur: (json['budget_max_eur'] as num?)?.toDouble(),
    preferredMakes:
        (json['preferred_makes'] as List<dynamic>?)
            ?.map((e) => e as String)
            .toList() ??
        const [],
    preferredBodyTypes:
        (json['preferred_body_types'] as List<dynamic>?)
            ?.map((e) => e as String)
            .toList() ??
        const [],
    preferredFuelTypes:
        (json['preferred_fuel_types'] as List<dynamic>?)
            ?.map((e) => e as String)
            .toList() ??
        const [],
    preferredTransmission: json['preferred_transmission'] as String?,
    maxMileageKm: json['max_mileage_km'] as int?,
    minYear: json['min_year'] as int?,
    maxYear: json['max_year'] as int?,
    notifyNewListings: json['notify_new_listings'] as bool? ?? true,
    notifyPriceDrops: json['notify_price_drops'] as bool? ?? true,
    notifyWeeklyDigest: json['notify_weekly_digest'] as bool? ?? false,
  );
}

class UpdateProfileRequest {
  final String? name;
  final String? phone;
  final String? country;
  final String? city;
  final String? currency;
  final String? language;
  final double? budgetMinEur;
  final double? budgetMaxEur;
  final List<String>? preferredMakes;
  final List<String>? preferredBodyTypes;
  final List<String>? preferredFuelTypes;
  final String? preferredTransmission;
  final int? maxMileageKm;
  final int? minYear;
  final int? maxYear;
  final bool? notifyNewListings;
  final bool? notifyPriceDrops;
  final bool? notifyWeeklyDigest;

  const UpdateProfileRequest({
    this.name,
    this.phone,
    this.country,
    this.city,
    this.currency,
    this.language,
    this.budgetMinEur,
    this.budgetMaxEur,
    this.preferredMakes,
    this.preferredBodyTypes,
    this.preferredFuelTypes,
    this.preferredTransmission,
    this.maxMileageKm,
    this.minYear,
    this.maxYear,
    this.notifyNewListings,
    this.notifyPriceDrops,
    this.notifyWeeklyDigest,
  });

  Map<String, dynamic> toJson() => {
    if (name != null) 'name': name,
    if (phone != null) 'phone': phone,
    if (country != null) 'country': country,
    if (city != null) 'city': city,
    if (currency != null) 'currency': currency,
    if (language != null) 'language': language,
    if (budgetMinEur != null) 'budget_min_eur': budgetMinEur,
    if (budgetMaxEur != null) 'budget_max_eur': budgetMaxEur,
    if (preferredMakes != null) 'preferred_makes': preferredMakes,
    if (preferredBodyTypes != null) 'preferred_body_types': preferredBodyTypes,
    if (preferredFuelTypes != null) 'preferred_fuel_types': preferredFuelTypes,
    if (preferredTransmission != null)
      'preferred_transmission': preferredTransmission,
    if (maxMileageKm != null) 'max_mileage_km': maxMileageKm,
    if (minYear != null) 'min_year': minYear,
    if (maxYear != null) 'max_year': maxYear,
    if (notifyNewListings != null) 'notify_new_listings': notifyNewListings,
    if (notifyPriceDrops != null) 'notify_price_drops': notifyPriceDrops,
    if (notifyWeeklyDigest != null) 'notify_weekly_digest': notifyWeeklyDigest,
  };
}
