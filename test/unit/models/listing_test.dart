import 'package:flutter_test/flutter_test.dart';
import 'package:carhero/models/listing.dart';

void main() {
  group('CarListing', () {
    test('fromJson parses all fields', () {
      final json = {
        'id': 1,
        'make': 'BMW',
        'model': '330i',
        'variant': 'M Sport',
        'year': 2021,
        'price_eur': 45000.0,
        'mileage_km': 32000,
        'fuel_type': 'Petrol',
        'transmission': 'Automatic',
        'body_type': 'Sedan',
        'power_hp': 258,
        'country': 'Germany',
        'provider': 'AutoScout24',
        'source_url': 'https://example.com/listing/1',
        'image_urls': ['https://img.com/1.jpg', 'https://img.com/2.jpg'],
        'investment_score': 78,
        'tier': 1,
      };

      final listing = CarListing.fromJson(json);

      expect(listing.id, 1);
      expect(listing.make, 'BMW');
      expect(listing.model, '330i');
      expect(listing.variant, 'M Sport');
      expect(listing.year, 2021);
      expect(listing.priceEur, 45000.0);
      expect(listing.mileageKm, 32000);
      expect(listing.fuelType, 'Petrol');
      expect(listing.transmission, 'Automatic');
      expect(listing.bodyType, 'Sedan');
      expect(listing.powerHp, 258);
      expect(listing.country, 'Germany');
      expect(listing.provider, 'AutoScout24');
      expect(listing.sourceUrl, 'https://example.com/listing/1');
      expect(listing.imageUrls, hasLength(2));
      expect(listing.investmentScore, 78);
      expect(listing.tier, 1);
    });

    test('fromJson handles null optional fields', () {
      final json = {'id': 2, 'make': 'Audi', 'model': 'A4'};

      final listing = CarListing.fromJson(json);

      expect(listing.id, 2);
      expect(listing.make, 'Audi');
      expect(listing.model, 'A4');
      expect(listing.variant, '');
      expect(listing.year, isNull);
      expect(listing.priceEur, isNull);
      expect(listing.mileageKm, isNull);
      expect(listing.fuelType, '');
      expect(listing.transmission, '');
      expect(listing.bodyType, '');
      expect(listing.powerHp, isNull);
      expect(listing.imageUrls, isNull);
      expect(listing.investmentScore, isNull);
      expect(listing.tier, isNull);
    });

    test('displayTitle includes variant when present', () {
      const listing = CarListing(
        id: 1,
        make: 'BMW',
        model: '330i',
        variant: 'M Sport',
      );
      expect(listing.displayTitle, 'BMW 330i M Sport');
    });

    test('displayTitle omits variant when empty', () {
      const listing = CarListing(id: 1, make: 'BMW', model: '330i');
      expect(listing.displayTitle, 'BMW 330i');
    });

    test('priceFormatted returns N/A for null price', () {
      const listing = CarListing(id: 1, make: 'A', model: 'B');
      expect(listing.priceFormatted, 'N/A');
    });

    test('priceFormatted formats with comma separator', () {
      const listing = CarListing(
        id: 1,
        make: 'A',
        model: 'B',
        priceEur: 45000.0,
      );
      expect(listing.priceFormatted, 'EUR 45,000');
    });

    test('priceFormatted formats large numbers', () {
      const listing = CarListing(
        id: 1,
        make: 'A',
        model: 'B',
        priceEur: 1250000.0,
      );
      expect(listing.priceFormatted, 'EUR 1,250,000');
    });

    test('mileageFormatted returns empty for null', () {
      const listing = CarListing(id: 1, make: 'A', model: 'B');
      expect(listing.mileageFormatted, '');
    });

    test('mileageFormatted formats correctly', () {
      const listing = CarListing(
        id: 1,
        make: 'A',
        model: 'B',
        mileageKm: 125000,
      );
      expect(listing.mileageFormatted, '125,000 km');
    });
  });
}
