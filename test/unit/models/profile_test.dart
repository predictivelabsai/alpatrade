import 'package:flutter_test/flutter_test.dart';
import 'package:carhero/models/profile.dart';

void main() {
  group('UserProfile', () {
    test('fromJson parses full profile', () {
      final json = {
        'name': 'Julian',
        'email': 'julian@test.com',
        'phone': '+372555',
        'country': 'Estonia',
        'city': 'Tallinn',
        'currency': 'EUR',
        'language': 'et',
        'budget_min_eur': 10000.0,
        'budget_max_eur': 50000.0,
        'preferred_makes': ['BMW', 'Audi'],
        'preferred_body_types': ['Sedan', 'SUV'],
        'preferred_fuel_types': ['Petrol', 'Hybrid'],
        'preferred_transmission': 'Automatic',
        'max_mileage_km': 100000,
        'min_year': 2018,
        'max_year': 2024,
        'notify_new_listings': true,
        'notify_price_drops': true,
        'notify_weekly_digest': false,
      };

      final p = UserProfile.fromJson(json);

      expect(p.name, 'Julian');
      expect(p.email, 'julian@test.com');
      expect(p.phone, '+372555');
      expect(p.country, 'Estonia');
      expect(p.city, 'Tallinn');
      expect(p.currency, 'EUR');
      expect(p.language, 'et');
      expect(p.budgetMinEur, 10000.0);
      expect(p.budgetMaxEur, 50000.0);
      expect(p.preferredMakes, ['BMW', 'Audi']);
      expect(p.preferredBodyTypes, ['Sedan', 'SUV']);
      expect(p.preferredFuelTypes, ['Petrol', 'Hybrid']);
      expect(p.preferredTransmission, 'Automatic');
      expect(p.maxMileageKm, 100000);
      expect(p.minYear, 2018);
      expect(p.maxYear, 2024);
      expect(p.notifyNewListings, true);
      expect(p.notifyPriceDrops, true);
      expect(p.notifyWeeklyDigest, false);
    });

    test('fromJson handles empty/null values', () {
      final p = UserProfile.fromJson({});

      expect(p.name, '');
      expect(p.email, '');
      expect(p.currency, 'EUR');
      expect(p.language, 'en');
      expect(p.preferredMakes, isEmpty);
      expect(p.preferredBodyTypes, isEmpty);
      expect(p.preferredFuelTypes, isEmpty);
      expect(p.budgetMinEur, isNull);
      expect(p.budgetMaxEur, isNull);
      expect(p.preferredTransmission, isNull);
      expect(p.notifyNewListings, true);
      expect(p.notifyPriceDrops, true);
      expect(p.notifyWeeklyDigest, false);
    });
  });

  group('UpdateProfileRequest', () {
    test('toJson includes only non-null fields', () {
      const req = UpdateProfileRequest(
        name: 'Julian',
        language: 'et',
        preferredMakes: ['BMW'],
      );

      final json = req.toJson();

      expect(json['name'], 'Julian');
      expect(json['language'], 'et');
      expect(json['preferred_makes'], ['BMW']);
      expect(json.containsKey('phone'), false);
      expect(json.containsKey('country'), false);
      expect(json.containsKey('budget_min_eur'), false);
    });

    test('toJson returns empty map when all null', () {
      const req = UpdateProfileRequest();
      final json = req.toJson();
      expect(json, isEmpty);
    });

    test('toJson includes notification settings', () {
      const req = UpdateProfileRequest(
        notifyNewListings: false,
        notifyPriceDrops: true,
        notifyWeeklyDigest: true,
      );

      final json = req.toJson();

      expect(json['notify_new_listings'], false);
      expect(json['notify_price_drops'], true);
      expect(json['notify_weekly_digest'], true);
    });
  });
}
