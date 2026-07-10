import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:carhero/config/theme.dart';
import 'package:carhero/models/listing.dart';
import 'package:carhero/screens/chat/widgets/listing_card.dart';

Widget _wrapWidget(Widget child) {
  return MaterialApp(
    theme: AppTheme.light,
    home: Scaffold(body: SingleChildScrollView(child: child)),
  );
}

const _testListing = CarListing(
  id: 1,
  make: 'BMW',
  model: '330i',
  variant: 'M Sport',
  year: 2021,
  priceEur: 45000.0,
  mileageKm: 32000,
  fuelType: 'Petrol',
  transmission: 'Automatic',
  bodyType: 'Sedan',
  powerHp: 258,
  country: 'Germany',
  provider: 'AutoScout24',
  sourceUrl: 'https://example.com/1',
  tier: 1,
  investmentScore: 78,
);

void main() {
  group('ListingCard full', () {
    testWidgets('displays make, model, variant', (tester) async {
      await tester.pumpWidget(_wrapWidget(ListingCard(listing: _testListing)));

      expect(find.text('BMW 330i M Sport'), findsOneWidget);
    });

    testWidgets('displays year', (tester) async {
      await tester.pumpWidget(_wrapWidget(ListingCard(listing: _testListing)));

      expect(find.text('2021'), findsOneWidget);
    });

    testWidgets('displays formatted price', (tester) async {
      await tester.pumpWidget(_wrapWidget(ListingCard(listing: _testListing)));

      expect(find.text('EUR 45,000'), findsOneWidget);
    });

    testWidgets('displays mileage', (tester) async {
      await tester.pumpWidget(_wrapWidget(ListingCard(listing: _testListing)));

      expect(find.text('32,000 km'), findsOneWidget);
    });

    testWidgets('displays fuel type', (tester) async {
      await tester.pumpWidget(_wrapWidget(ListingCard(listing: _testListing)));

      expect(find.text('Petrol'), findsOneWidget);
    });

    testWidgets('displays transmission', (tester) async {
      await tester.pumpWidget(_wrapWidget(ListingCard(listing: _testListing)));

      expect(find.text('Automatic'), findsOneWidget);
    });

    testWidgets('displays power', (tester) async {
      await tester.pumpWidget(_wrapWidget(ListingCard(listing: _testListing)));

      expect(find.text('258 hp'), findsOneWidget);
    });

    testWidgets('displays country and provider', (tester) async {
      await tester.pumpWidget(_wrapWidget(ListingCard(listing: _testListing)));

      expect(find.text('Germany / AutoScout24'), findsOneWidget);
    });

    testWidgets('displays tier badge', (tester) async {
      await tester.pumpWidget(_wrapWidget(ListingCard(listing: _testListing)));

      expect(find.text('Tier 1'), findsOneWidget);
      expect(find.text('78'), findsOneWidget);
    });

    testWidgets('displays N/A for null price', (tester) async {
      const listing = CarListing(id: 2, make: 'Audi', model: 'A4');
      await tester.pumpWidget(_wrapWidget(ListingCard(listing: listing)));

      expect(find.text('N/A'), findsOneWidget);
    });
  });

  group('ListingCard compact', () {
    testWidgets('renders compact variant', (tester) async {
      await tester.pumpWidget(
        _wrapWidget(ListingCard(listing: _testListing, compact: true)),
      );

      expect(find.text('BMW 330i M Sport'), findsOneWidget);
      expect(find.text('EUR 45,000'), findsOneWidget);
    });
  });

  group('ListingCard.fromJson', () {
    testWidgets('creates card from JSON', (tester) async {
      final json = {
        'id': 3,
        'make': 'Mercedes-Benz',
        'model': 'C300',
        'year': 2020,
        'price_eur': 38000.0,
      };

      await tester.pumpWidget(_wrapWidget(ListingCard.fromJson(json)));

      expect(find.text('Mercedes-Benz C300'), findsOneWidget);
      expect(find.text('EUR 38,000'), findsOneWidget);
    });
  });
}
