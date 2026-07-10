import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:carhero/config/theme.dart';
import 'package:carhero/models/profile.dart';
import 'package:carhero/providers/profile_provider.dart';
import 'package:carhero/screens/profile_screen.dart';

class _FakeProfileNotifier extends ProfileNotifier {
  final UserProfile? _profile;
  _FakeProfileNotifier(this._profile);

  @override
  Future<UserProfile?> build() async => _profile;
}

const _testProfile = UserProfile(
  name: 'Jane Doe',
  email: 'jane@example.com',
  phone: '+372 555 1234',
  country: 'Estonia',
  city: 'Tallinn',
  currency: 'EUR',
  language: 'en',
  budgetMinEur: 10000,
  budgetMaxEur: 50000,
  preferredMakes: ['BMW', 'Audi'],
  preferredBodyTypes: ['SUV'],
  preferredFuelTypes: ['Petrol'],
  preferredTransmission: 'Automatic',
  maxMileageKm: 100000,
  minYear: 2018,
  maxYear: 2024,
  notifyNewListings: true,
  notifyPriceDrops: true,
  notifyWeeklyDigest: false,
);

Widget _buildProfileScreen({UserProfile? profile = _testProfile}) {
  return ProviderScope(
    overrides: [
      profileProvider.overrideWith(() => _FakeProfileNotifier(profile)),
    ],
    child: MaterialApp(theme: AppTheme.light, home: const ProfileScreen()),
  );
}

void main() {
  group('ProfileScreen', () {
    testWidgets('renders app bar with title', (tester) async {
      await tester.pumpWidget(_buildProfileScreen());
      await tester.pumpAndSettle();

      expect(find.text('Profile & Preferences'), findsOneWidget);
    });

    testWidgets('renders Account section header', (tester) async {
      await tester.pumpWidget(_buildProfileScreen());
      await tester.pumpAndSettle();

      expect(find.text('Account'), findsOneWidget);
    });

    testWidgets('renders account fields pre-filled from profile', (
      tester,
    ) async {
      await tester.pumpWidget(_buildProfileScreen());
      await tester.pumpAndSettle();

      // Text fields should contain profile data
      expect(find.text('Jane Doe'), findsOneWidget);
      expect(find.text('jane@example.com'), findsOneWidget);
      expect(find.text('+372 555 1234'), findsOneWidget);
      expect(find.text('Estonia'), findsOneWidget);
      expect(find.text('Tallinn'), findsOneWidget);
    });

    testWidgets('renders Save Account button', (tester) async {
      await tester.pumpWidget(_buildProfileScreen());
      await tester.pumpAndSettle();

      expect(find.text('Save Account'), findsOneWidget);
    });

    testWidgets('renders Search Preferences section header', (tester) async {
      await tester.pumpWidget(_buildProfileScreen());
      await tester.pumpAndSettle();

      expect(find.text('Search Preferences'), findsOneWidget);
    });

    testWidgets('renders Budget Range label', (tester) async {
      await tester.pumpWidget(_buildProfileScreen());
      await tester.pumpAndSettle();

      expect(find.text('Budget Range'), findsOneWidget);
    });

    testWidgets('renders Preferred Makes chip group', (tester) async {
      await tester.pumpWidget(_buildProfileScreen());
      await tester.pumpAndSettle();

      expect(find.text('Preferred Makes'), findsOneWidget);
      // BMW and Audi should appear as FilterChips
      expect(find.widgetWithText(FilterChip, 'BMW'), findsOneWidget);
      expect(find.widgetWithText(FilterChip, 'Audi'), findsOneWidget);
    });

    testWidgets('renders Body Types chip group', (tester) async {
      await tester.pumpWidget(_buildProfileScreen());
      await tester.pumpAndSettle();

      expect(find.text('Body Types'), findsOneWidget);
      expect(find.widgetWithText(FilterChip, 'SUV'), findsOneWidget);
      expect(find.widgetWithText(FilterChip, 'Sedan'), findsOneWidget);
    });

    testWidgets('renders Fuel Types chip group', (tester) async {
      await tester.pumpWidget(_buildProfileScreen());
      await tester.pumpAndSettle();

      expect(find.text('Fuel Types'), findsOneWidget);
      expect(find.widgetWithText(FilterChip, 'Petrol'), findsOneWidget);
      expect(find.widgetWithText(FilterChip, 'Diesel'), findsOneWidget);
    });

    testWidgets('renders Transmission choice chips', (tester) async {
      await tester.pumpWidget(_buildProfileScreen());
      await tester.pumpAndSettle();

      expect(find.text('Transmission'), findsOneWidget);
      expect(find.widgetWithText(ChoiceChip, 'Any'), findsOneWidget);
      expect(find.widgetWithText(ChoiceChip, 'Automatic'), findsOneWidget);
      expect(find.widgetWithText(ChoiceChip, 'Manual'), findsOneWidget);
    });

    testWidgets('renders Save Preferences button', (tester) async {
      await tester.pumpWidget(_buildProfileScreen());
      await tester.pumpAndSettle();

      expect(find.text('Save Preferences'), findsOneWidget);
    });

    testWidgets('renders Notifications section header', (tester) async {
      await tester.pumpWidget(_buildProfileScreen());
      await tester.pumpAndSettle();

      // Scroll down to reveal Notifications section
      await tester.scrollUntilVisible(
        find.text('Notifications'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.text('Notifications'), findsOneWidget);
    });

    testWidgets('renders notification toggle switches', (tester) async {
      await tester.pumpWidget(_buildProfileScreen());
      await tester.pumpAndSettle();

      // Scroll down to notification toggles
      await tester.scrollUntilVisible(
        find.text('New listings matching preferences'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.text('New listings matching preferences'), findsOneWidget);
      expect(find.text('Price drops on favorites'), findsOneWidget);
      expect(find.text('Weekly market digest'), findsOneWidget);

      // SwitchListTile widgets
      expect(find.byType(SwitchListTile), findsNWidgets(3));
    });

    testWidgets('renders Save Notifications button', (tester) async {
      await tester.pumpWidget(_buildProfileScreen());
      await tester.pumpAndSettle();

      await tester.scrollUntilVisible(
        find.text('Save Notifications'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.text('Save Notifications'), findsOneWidget);
    });

    testWidgets('renders all three sections in scrollable form', (
      tester,
    ) async {
      await tester.pumpWidget(_buildProfileScreen());
      await tester.pumpAndSettle();

      // All three section headers exist in the widget tree
      expect(find.text('Account'), findsOneWidget);
      expect(find.text('Search Preferences'), findsOneWidget);
      // Scroll to reveal Notifications
      await tester.scrollUntilVisible(
        find.text('Notifications'),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.text('Notifications'), findsOneWidget);
    });

    testWidgets('shows login prompt when profile is null', (tester) async {
      await tester.pumpWidget(_buildProfileScreen(profile: null));
      await tester.pumpAndSettle();

      expect(find.text('Please log in to view profile.'), findsOneWidget);
    });

    testWidgets('renders three save buttons total', (tester) async {
      await tester.pumpWidget(_buildProfileScreen());
      await tester.pumpAndSettle();

      // Three ElevatedButton save buttons
      expect(find.byType(ElevatedButton), findsNWidgets(3));
    });

    testWidgets('renders Year Range label and fields', (tester) async {
      await tester.pumpWidget(_buildProfileScreen());
      await tester.pumpAndSettle();

      await tester.scrollUntilVisible(
        find.text('Year Range'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.text('Year Range'), findsOneWidget);
    });

    testWidgets('renders Max Mileage field', (tester) async {
      await tester.pumpWidget(_buildProfileScreen());
      await tester.pumpAndSettle();

      await tester.scrollUntilVisible(
        find.text('Max Mileage (km)'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.text('Max Mileage (km)'), findsOneWidget);
    });
  });
}
