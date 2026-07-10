import 'package:flutter_test/flutter_test.dart';
import 'package:carhero/models/garage.dart';

void main() {
  group('GarageCar', () {
    test('fromJson parses all fields', () {
      final json = {
        'id': 1,
        'make': 'Mercedes-Benz',
        'model': 'C300',
        'variant': 'AMG Line',
        'year': 2019,
        'mileage_km': 45000,
        'purchase_price_eur': 38000.0,
        'fuel_type': 'Petrol',
        'estimated_value': 32000,
        'comparable_count': 15,
      };

      final car = GarageCar.fromJson(json);

      expect(car.id, 1);
      expect(car.make, 'Mercedes-Benz');
      expect(car.model, 'C300');
      expect(car.variant, 'AMG Line');
      expect(car.year, 2019);
      expect(car.mileageKm, 45000);
      expect(car.purchasePriceEur, 38000.0);
      expect(car.fuelType, 'Petrol');
      expect(car.estimatedValue, 32000);
      expect(car.comparableCount, 15);
    });

    test('fromJson handles minimal fields', () {
      final json = {'id': 2, 'make': 'Audi', 'model': 'A4', 'year': 2020};

      final car = GarageCar.fromJson(json);

      expect(car.variant, '');
      expect(car.mileageKm, isNull);
      expect(car.purchasePriceEur, isNull);
      expect(car.fuelType, '');
      expect(car.estimatedValue, isNull);
      expect(car.comparableCount, 0);
    });
  });

  group('AddGarageCarRequest', () {
    test('toJson includes required and optional fields', () {
      const req = AddGarageCarRequest(
        make: 'BMW',
        model: '330i',
        year: 2021,
        mileageKm: 20000,
        purchasePriceEur: 42000.0,
        fuelType: 'Petrol',
        fuelConsumptionL100km: 7.5,
        annualKm: 20000,
        insuranceAnnualEur: 1200,
        maintenanceAnnualEur: 800,
      );

      final json = req.toJson();

      expect(json['make'], 'BMW');
      expect(json['model'], '330i');
      expect(json['year'], 2021);
      expect(json['mileage_km'], 20000);
      expect(json['purchase_price_eur'], 42000.0);
      expect(json['fuel_type'], 'Petrol');
      expect(json['fuel_consumption_l_100km'], 7.5);
      expect(json['annual_km'], 20000);
      expect(json['insurance_annual_eur'], 1200);
      expect(json['maintenance_annual_eur'], 800);
    });

    test('toJson omits null optional fields', () {
      const req = AddGarageCarRequest(make: 'Audi', model: 'A4', year: 2020);

      final json = req.toJson();

      expect(json.containsKey('mileage_km'), false);
      expect(json.containsKey('purchase_price_eur'), false);
      expect(json.containsKey('purchase_date'), false);
      expect(json.containsKey('fuel_type'), false);
      expect(json.containsKey('fuel_consumption_l_100km'), false);
      expect(json['annual_km'], 15000);
      expect(json['insurance_annual_eur'], 0);
      expect(json['maintenance_annual_eur'], 0);
    });
  });

  group('Valuation', () {
    test('fromJson parses all fields', () {
      final json = {
        'estimated_value': 35000,
        'comparable_count': 20,
        'avg_price': 36000,
        'median_price': 35500,
        'min_price': 28000,
        'max_price': 42000,
        'avg_mileage': 40000,
      };

      final v = Valuation.fromJson(json);

      expect(v.estimatedValue, 35000);
      expect(v.comparableCount, 20);
      expect(v.avgPrice, 36000);
      expect(v.medianPrice, 35500);
      expect(v.minPrice, 28000);
      expect(v.maxPrice, 42000);
      expect(v.avgMileage, 40000);
    });

    test('fromJson handles nulls', () {
      final v = Valuation.fromJson({});

      expect(v.estimatedValue, isNull);
      expect(v.comparableCount, 0);
      expect(v.avgPrice, isNull);
    });
  });

  group('TcoCost', () {
    test('fromJson parses all fields', () {
      final json = {
        'fuel_annual_eur': 2400,
        'insurance_annual_eur': 1200,
        'maintenance_annual_eur': 800,
        'depreciation_annual_eur': 3500,
        'total_annual_eur': 7900,
        'total_monthly_eur': 658,
        'cost_per_km_eur': 0.53,
        'current_market_value_eur': 32000,
        'valuation': {'estimated_value': 32000, 'comparable_count': 15},
      };

      final tco = TcoCost.fromJson(json);

      expect(tco.fuelAnnualEur, 2400);
      expect(tco.insuranceAnnualEur, 1200);
      expect(tco.maintenanceAnnualEur, 800);
      expect(tco.depreciationAnnualEur, 3500);
      expect(tco.totalAnnualEur, 7900);
      expect(tco.totalMonthlyEur, 658);
      expect(tco.costPerKmEur, 0.53);
      expect(tco.currentMarketValueEur, 32000);
      expect(tco.valuation, isNotNull);
      expect(tco.valuation!.estimatedValue, 32000);
    });

    test('fromJson handles empty json', () {
      final tco = TcoCost.fromJson({});

      expect(tco.fuelAnnualEur, 0);
      expect(tco.totalAnnualEur, 0);
      expect(tco.costPerKmEur, 0);
      expect(tco.currentMarketValueEur, isNull);
      expect(tco.valuation, isNull);
    });
  });
}
