import 'package:flutter_test/flutter_test.dart';
import 'package:carhero/models/favorite.dart';

void main() {
  group('Favorite', () {
    test('fromJson parses all fields', () {
      final json = {
        'id': 1,
        'listing_id': 100,
        'make': 'Porsche',
        'model': '911',
        'variant': 'Carrera S',
        'year': 2020,
        'mileage_km': 18000,
        'price_eur': 95000,
        'price_at_save': 98000,
        'price_change': -3000,
        'fuel_type': 'Petrol',
        'transmission': 'Manual',
        'country': 'Germany',
        'provider': 'Mobile.de',
        'url': 'https://example.com/911',
        'note': 'Great deal',
      };

      final fav = Favorite.fromJson(json);

      expect(fav.id, 1);
      expect(fav.listingId, 100);
      expect(fav.make, 'Porsche');
      expect(fav.model, '911');
      expect(fav.variant, 'Carrera S');
      expect(fav.year, 2020);
      expect(fav.mileageKm, 18000);
      expect(fav.priceEur, 95000);
      expect(fav.priceAtSave, 98000);
      expect(fav.priceChange, -3000);
      expect(fav.fuelType, 'Petrol');
      expect(fav.transmission, 'Manual');
      expect(fav.country, 'Germany');
      expect(fav.provider, 'Mobile.de');
      expect(fav.url, 'https://example.com/911');
      expect(fav.note, 'Great deal');
    });

    test('fromJson handles null optionals', () {
      final json = {'id': 2, 'listing_id': 200, 'make': 'BMW', 'model': 'M3'};

      final fav = Favorite.fromJson(json);

      expect(fav.variant, '');
      expect(fav.year, isNull);
      expect(fav.mileageKm, isNull);
      expect(fav.priceEur, isNull);
      expect(fav.priceAtSave, isNull);
      expect(fav.priceChange, isNull);
      expect(fav.fuelType, '');
      expect(fav.note, '');
    });

    test('displayTitle includes variant', () {
      const fav = Favorite(
        id: 1,
        listingId: 1,
        make: 'Porsche',
        model: '911',
        variant: 'Carrera',
      );
      expect(fav.displayTitle, 'Porsche 911 Carrera');
    });

    test('displayTitle omits empty variant', () {
      const fav = Favorite(id: 1, listingId: 1, make: 'BMW', model: 'M3');
      expect(fav.displayTitle, 'BMW M3');
    });

    test('priceFormatted returns N/A for null', () {
      const fav = Favorite(id: 1, listingId: 1, make: 'A', model: 'B');
      expect(fav.priceFormatted, 'N/A');
    });

    test('priceFormatted formats correctly', () {
      const fav = Favorite(
        id: 1,
        listingId: 1,
        make: 'A',
        model: 'B',
        priceEur: 95000,
      );
      expect(fav.priceFormatted, 'EUR 95,000');
    });

    test('priceChangeFormatted handles positive change', () {
      const fav = Favorite(
        id: 1,
        listingId: 1,
        make: 'A',
        model: 'B',
        priceChange: 5000,
      );
      expect(fav.priceChangeFormatted, '+5,000 EUR');
    });

    test('priceChangeFormatted handles negative change', () {
      const fav = Favorite(
        id: 1,
        listingId: 1,
        make: 'A',
        model: 'B',
        priceChange: -3000,
      );
      expect(fav.priceChangeFormatted, '-3,000 EUR');
    });

    test('priceChangeFormatted returns empty for null', () {
      const fav = Favorite(id: 1, listingId: 1, make: 'A', model: 'B');
      expect(fav.priceChangeFormatted, '');
    });
  });
}
