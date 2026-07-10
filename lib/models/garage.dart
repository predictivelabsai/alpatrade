class GarageCar {
  final int id;
  final String make;
  final String model;
  final String variant;
  final int year;
  final int? mileageKm;
  final double? purchasePriceEur;
  final String fuelType;
  final int? estimatedValue;
  final int comparableCount;

  const GarageCar({
    required this.id,
    required this.make,
    required this.model,
    this.variant = '',
    required this.year,
    this.mileageKm,
    this.purchasePriceEur,
    this.fuelType = '',
    this.estimatedValue,
    this.comparableCount = 0,
  });

  factory GarageCar.fromJson(Map<String, dynamic> json) => GarageCar(
    id: json['id'] as int,
    make: json['make'] as String,
    model: json['model'] as String,
    variant: json['variant'] as String? ?? '',
    year: json['year'] as int,
    mileageKm: json['mileage_km'] as int?,
    purchasePriceEur: (json['purchase_price_eur'] as num?)?.toDouble(),
    fuelType: json['fuel_type'] as String? ?? '',
    estimatedValue: json['estimated_value'] as int?,
    comparableCount: json['comparable_count'] as int? ?? 0,
  );
}

class AddGarageCarRequest {
  final String make;
  final String model;
  final String variant;
  final int year;
  final int? mileageKm;
  final double? purchasePriceEur;
  final String? purchaseDate;
  final String? fuelType;
  final double? fuelConsumptionL100km;
  final int annualKm;
  final double insuranceAnnualEur;
  final double maintenanceAnnualEur;

  const AddGarageCarRequest({
    required this.make,
    required this.model,
    this.variant = '',
    required this.year,
    this.mileageKm,
    this.purchasePriceEur,
    this.purchaseDate,
    this.fuelType,
    this.fuelConsumptionL100km,
    this.annualKm = 15000,
    this.insuranceAnnualEur = 0,
    this.maintenanceAnnualEur = 0,
  });

  Map<String, dynamic> toJson() => {
    'make': make,
    'model': model,
    'variant': variant,
    'year': year,
    if (mileageKm != null) 'mileage_km': mileageKm,
    if (purchasePriceEur != null) 'purchase_price_eur': purchasePriceEur,
    if (purchaseDate != null) 'purchase_date': purchaseDate,
    if (fuelType != null) 'fuel_type': fuelType,
    if (fuelConsumptionL100km != null)
      'fuel_consumption_l_100km': fuelConsumptionL100km,
    'annual_km': annualKm,
    'insurance_annual_eur': insuranceAnnualEur,
    'maintenance_annual_eur': maintenanceAnnualEur,
  };
}

class Valuation {
  final int? estimatedValue;
  final int comparableCount;
  final int? avgPrice;
  final int? medianPrice;
  final int? minPrice;
  final int? maxPrice;
  final int? avgMileage;

  const Valuation({
    this.estimatedValue,
    this.comparableCount = 0,
    this.avgPrice,
    this.medianPrice,
    this.minPrice,
    this.maxPrice,
    this.avgMileage,
  });

  factory Valuation.fromJson(Map<String, dynamic> json) => Valuation(
    estimatedValue: json['estimated_value'] as int?,
    comparableCount: json['comparable_count'] as int? ?? 0,
    avgPrice: json['avg_price'] as int?,
    medianPrice: json['median_price'] as int?,
    minPrice: json['min_price'] as int?,
    maxPrice: json['max_price'] as int?,
    avgMileage: json['avg_mileage'] as int?,
  );
}

class TcoCost {
  final int fuelAnnualEur;
  final int insuranceAnnualEur;
  final int maintenanceAnnualEur;
  final int depreciationAnnualEur;
  final int totalAnnualEur;
  final int totalMonthlyEur;
  final double costPerKmEur;
  final int? currentMarketValueEur;
  final Valuation? valuation;

  const TcoCost({
    this.fuelAnnualEur = 0,
    this.insuranceAnnualEur = 0,
    this.maintenanceAnnualEur = 0,
    this.depreciationAnnualEur = 0,
    this.totalAnnualEur = 0,
    this.totalMonthlyEur = 0,
    this.costPerKmEur = 0,
    this.currentMarketValueEur,
    this.valuation,
  });

  factory TcoCost.fromJson(Map<String, dynamic> json) => TcoCost(
    fuelAnnualEur: json['fuel_annual_eur'] as int? ?? 0,
    insuranceAnnualEur: json['insurance_annual_eur'] as int? ?? 0,
    maintenanceAnnualEur: json['maintenance_annual_eur'] as int? ?? 0,
    depreciationAnnualEur: json['depreciation_annual_eur'] as int? ?? 0,
    totalAnnualEur: json['total_annual_eur'] as int? ?? 0,
    totalMonthlyEur: json['total_monthly_eur'] as int? ?? 0,
    costPerKmEur: (json['cost_per_km_eur'] as num?)?.toDouble() ?? 0,
    currentMarketValueEur: json['current_market_value_eur'] as int?,
    valuation: json['valuation'] != null
        ? Valuation.fromJson(json['valuation'] as Map<String, dynamic>)
        : null,
  );
}
