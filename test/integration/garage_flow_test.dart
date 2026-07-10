import 'package:flutter_test/flutter_test.dart';
import 'package:carhero/models/garage.dart';

void main() {
  group('Garage flow integration', () {
    test('add car, get valuation, compute TCO', () {
      // 1. Create add request
      const req = AddGarageCarRequest(
        make: 'BMW',
        model: '330i',
        variant: 'M Sport',
        year: 2020,
        mileageKm: 45000,
        purchasePriceEur: 38000.0,
        fuelType: 'Petrol',
        fuelConsumptionL100km: 7.5,
        annualKm: 20000,
        insuranceAnnualEur: 1200,
        maintenanceAnnualEur: 800,
      );

      final json = req.toJson();
      expect(json['make'], 'BMW');
      expect(json['model'], '330i');
      expect(json['annual_km'], 20000);

      // 2. Car returned from API
      final car = GarageCar.fromJson({
        'id': 1,
        'make': 'BMW',
        'model': '330i',
        'variant': 'M Sport',
        'year': 2020,
        'mileage_km': 45000,
        'purchase_price_eur': 38000.0,
        'fuel_type': 'Petrol',
        'estimated_value': 32000,
        'comparable_count': 18,
      });

      expect(car.id, 1);
      expect(car.estimatedValue, 32000);
      expect(car.comparableCount, 18);

      // 3. Get valuation
      final valuation = Valuation.fromJson({
        'estimated_value': 32000,
        'comparable_count': 18,
        'avg_price': 33500,
        'median_price': 32000,
        'min_price': 26000,
        'max_price': 40000,
        'avg_mileage': 42000,
      });

      expect(valuation.estimatedValue, 32000);
      expect(valuation.avgPrice, 33500);

      // Value difference from purchase
      final valueDiff =
          valuation.estimatedValue! - car.purchasePriceEur!.toInt();
      expect(valueDiff, -6000);

      // 4. TCO breakdown
      final tco = TcoCost.fromJson({
        'fuel_annual_eur': 2700,
        'insurance_annual_eur': 1200,
        'maintenance_annual_eur': 800,
        'depreciation_annual_eur': 3000,
        'total_annual_eur': 7700,
        'total_monthly_eur': 642,
        'cost_per_km_eur': 0.39,
        'current_market_value_eur': 32000,
        'valuation': {'estimated_value': 32000, 'comparable_count': 18},
      });

      expect(tco.fuelAnnualEur, 2700);
      expect(tco.totalAnnualEur, 7700);
      expect(tco.totalMonthlyEur, 642);
      expect(tco.costPerKmEur, closeTo(0.39, 0.01));
      expect(tco.valuation, isNotNull);
      expect(tco.valuation!.estimatedValue, 32000);

      // Monthly cost breakdown should sum approximately to total
      final monthlyComponents =
          (tco.fuelAnnualEur +
              tco.insuranceAnnualEur +
              tco.maintenanceAnnualEur +
              tco.depreciationAnnualEur) ~/
          12;
      expect(monthlyComponents, closeTo(tco.totalMonthlyEur, 2));
    });

    test('multiple garage cars managed as list', () {
      final cars = [
        GarageCar.fromJson({
          'id': 1,
          'make': 'BMW',
          'model': '330i',
          'year': 2020,
          'estimated_value': 32000,
        }),
        GarageCar.fromJson({
          'id': 2,
          'make': 'Porsche',
          'model': '718 Cayman',
          'year': 2021,
          'estimated_value': 55000,
        }),
      ];

      expect(cars, hasLength(2));

      // Total garage value
      final totalValue = cars
          .where((c) => c.estimatedValue != null)
          .fold<int>(0, (sum, c) => sum + c.estimatedValue!);
      expect(totalValue, 87000);

      // Remove first car
      final updatedCars = cars.where((c) => c.id != 1).toList();
      expect(updatedCars, hasLength(1));
      expect(updatedCars[0].make, 'Porsche');
    });

    test('add request omits null optional fields', () {
      const minimal = AddGarageCarRequest(
        make: 'Audi',
        model: 'A4',
        year: 2019,
      );

      final json = minimal.toJson();

      expect(json.containsKey('mileage_km'), false);
      expect(json.containsKey('purchase_price_eur'), false);
      expect(json.containsKey('fuel_type'), false);
      expect(json.containsKey('fuel_consumption_l_100km'), false);
      // Defaults should still be present
      expect(json['annual_km'], 15000);
      expect(json['insurance_annual_eur'], 0);
    });
  });
}
