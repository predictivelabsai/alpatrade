import 'package:flutter_test/flutter_test.dart';
import 'package:carhero/models/favorite.dart';

void main() {
  group('Favorites flow integration', () {
    test('add and remove favorites from list', () {
      var favorites = <Favorite>[];

      // Add a favorite
      favorites = [
        ...favorites,
        const Favorite(
          id: 1,
          listingId: 100,
          make: 'BMW',
          model: 'M3',
          year: 2021,
          priceEur: 65000,
          priceAtSave: 65000,
        ),
      ];

      expect(favorites, hasLength(1));
      expect(favorites[0].make, 'BMW');

      // Add another
      favorites = [
        ...favorites,
        const Favorite(
          id: 2,
          listingId: 200,
          make: 'Porsche',
          model: '911',
          year: 2020,
          priceEur: 95000,
          priceAtSave: 98000,
          priceChange: -3000,
        ),
      ];

      expect(favorites, hasLength(2));

      // Verify price change tracking
      expect(favorites[1].priceChange, -3000);
      expect(favorites[1].priceChangeFormatted, '-3,000 EUR');

      // Remove first favorite
      favorites = favorites.where((f) => f.id != 1).toList();

      expect(favorites, hasLength(1));
      expect(favorites[0].make, 'Porsche');
    });

    test('favorite display helpers work correctly', () {
      const fav = Favorite(
        id: 1,
        listingId: 100,
        make: 'Mercedes-Benz',
        model: 'E-Class',
        variant: 'AMG',
        year: 2022,
        priceEur: 72000,
        priceAtSave: 75000,
        priceChange: -3000,
        mileageKm: 15000,
        fuelType: 'Petrol',
        country: 'Germany',
      );

      expect(fav.displayTitle, 'Mercedes-Benz E-Class AMG');
      expect(fav.priceFormatted, 'EUR 72,000');
      expect(fav.priceChangeFormatted, '-3,000 EUR');
    });

    test('favorites with price increases', () {
      const fav = Favorite(
        id: 1,
        listingId: 100,
        make: 'Porsche',
        model: '718 Cayman',
        priceEur: 55000,
        priceAtSave: 52000,
        priceChange: 3000,
      );

      expect(fav.priceChangeFormatted, '+3,000 EUR');
    });

    test('favorites from JSON array', () {
      final jsonList = [
        {
          'id': 1,
          'listing_id': 100,
          'make': 'BMW',
          'model': 'M3',
          'year': 2021,
          'price_eur': 65000,
        },
        {
          'id': 2,
          'listing_id': 200,
          'make': 'Audi',
          'model': 'RS5',
          'year': 2022,
          'price_eur': 78000,
        },
      ];

      final favorites = jsonList.map((e) => Favorite.fromJson(e)).toList();

      expect(favorites, hasLength(2));
      expect(favorites[0].displayTitle, 'BMW M3');
      expect(favorites[1].displayTitle, 'Audi RS5');
    });
  });
}
