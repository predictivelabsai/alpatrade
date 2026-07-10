import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:carhero/config/theme.dart';
import 'package:carhero/screens/home_screen.dart';

Widget _wrapWidget(Widget child) {
  return MaterialApp(theme: AppTheme.light, home: child);
}

void main() {
  group('HomeScreen', () {
    testWidgets('renders Kenri.ai title in hero section', (tester) async {
      await tester.pumpWidget(_wrapWidget(const HomeScreen()));

      expect(find.text('Kenri.ai'), findsOneWidget);
    });

    testWidgets('renders hero subtitle', (tester) async {
      await tester.pumpWidget(_wrapWidget(const HomeScreen()));

      expect(find.text('Your Personal Advisor.'), findsOneWidget);
    });

    testWidgets('renders hero description', (tester) async {
      await tester.pumpWidget(_wrapWidget(const HomeScreen()));

      expect(
        find.text('Search, compare, and value premium cars across Europe.'),
        findsOneWidget,
      );
    });

    testWidgets('renders Sign In buttons', (tester) async {
      await tester.pumpWidget(_wrapWidget(const HomeScreen()));

      // One in hero section, one in bottom CTA
      expect(find.widgetWithText(ElevatedButton, 'Sign In'), findsNWidgets(2));
    });

    testWidgets('renders Explore Market button in hero section', (
      tester,
    ) async {
      await tester.pumpWidget(_wrapWidget(const HomeScreen()));

      expect(
        find.widgetWithText(OutlinedButton, 'Explore Market'),
        findsOneWidget,
      );
    });

    testWidgets('renders stats row with key numbers', (tester) async {
      await tester.pumpWidget(_wrapWidget(const HomeScreen()));

      expect(find.text('50,000+'), findsOneWidget);
      expect(find.text('Listings'), findsOneWidget);
      expect(find.text('12'), findsOneWidget);
      expect(find.text('Brands'), findsOneWidget);
      expect(find.text('5+'), findsOneWidget);
      expect(find.text('Countries'), findsOneWidget);
      expect(find.text('8'), findsOneWidget);
      expect(find.text('Sources'), findsOneWidget);
    });

    testWidgets('renders What Kenri.ai Does section', (tester) async {
      await tester.pumpWidget(_wrapWidget(const HomeScreen()));

      await tester.scrollUntilVisible(
        find.text('What Kenri.ai Does'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.text('What Kenri.ai Does'), findsOneWidget);
    });

    testWidgets('renders Advisory feature card', (tester) async {
      await tester.pumpWidget(_wrapWidget(const HomeScreen()));

      await tester.scrollUntilVisible(
        find.text('Advisory'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.text('Advisory'), findsOneWidget);
      expect(find.textContaining('Chat with our AI advisor'), findsOneWidget);
    });

    testWidgets('renders Market Intelligence feature card', (tester) async {
      await tester.pumpWidget(_wrapWidget(const HomeScreen()));

      await tester.scrollUntilVisible(
        find.text('Market Intelligence'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.text('Market Intelligence'), findsOneWidget);
      expect(find.textContaining('Real-time pricing data'), findsOneWidget);
    });

    testWidgets('renders Valuation feature card', (tester) async {
      await tester.pumpWidget(_wrapWidget(const HomeScreen()));

      await tester.scrollUntilVisible(
        find.text('Valuation'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.text('Valuation'), findsOneWidget);
      expect(find.textContaining('data-driven valuations'), findsOneWidget);
    });

    testWidgets('renders How it Works section', (tester) async {
      await tester.pumpWidget(_wrapWidget(const HomeScreen()));

      await tester.scrollUntilVisible(
        find.text('How it Works'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.text('How it Works'), findsOneWidget);
    });

    testWidgets('renders three how-it-works steps', (tester) async {
      await tester.pumpWidget(_wrapWidget(const HomeScreen()));

      await tester.scrollUntilVisible(
        find.text('Tell Us What You Want'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.text('Tell Us What You Want'), findsOneWidget);

      await tester.scrollUntilVisible(
        find.text('We Search the Market'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.text('We Search the Market'), findsOneWidget);

      await tester.scrollUntilVisible(
        find.text('Get Expert Advice'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.text('Get Expert Advice'), findsOneWidget);
    });

    testWidgets('renders Premium Brands section', (tester) async {
      await tester.pumpWidget(_wrapWidget(const HomeScreen()));

      await tester.scrollUntilVisible(
        find.text('Premium Brands'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.text('Premium Brands'), findsOneWidget);
    });

    testWidgets('renders bottom CTA section', (tester) async {
      await tester.pumpWidget(_wrapWidget(const HomeScreen()));

      await tester.scrollUntilVisible(
        find.text('Ready to find your next car?'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.text('Ready to find your next car?'), findsOneWidget);
      expect(find.textContaining('Join thousands of drivers'), findsOneWidget);
    });

    testWidgets('renders bottom CTA Sign In button', (tester) async {
      await tester.pumpWidget(_wrapWidget(const HomeScreen()));

      await tester.scrollUntilVisible(
        find.text('Ready to find your next car?'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      // Two Sign In buttons: one in hero, one in bottom CTA
      expect(find.text('Sign In'), findsNWidgets(2));
    });

    testWidgets('renders About and Contact links in footer', (tester) async {
      await tester.pumpWidget(_wrapWidget(const HomeScreen()));

      await tester.scrollUntilVisible(
        find.text('About'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.text('About'), findsOneWidget);
      expect(find.text('Contact'), findsOneWidget);
    });

    testWidgets('renders step numbers 1, 2, 3', (tester) async {
      await tester.pumpWidget(_wrapWidget(const HomeScreen()));

      await tester.scrollUntilVisible(
        find.text('1'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.text('1'), findsOneWidget);

      await tester.scrollUntilVisible(
        find.text('2'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.text('2'), findsOneWidget);

      await tester.scrollUntilVisible(
        find.text('3'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.text('3'), findsOneWidget);
    });

    testWidgets('renders four stat cards', (tester) async {
      await tester.pumpWidget(_wrapWidget(const HomeScreen()));

      expect(find.byType(Card), findsAtLeast(4));
    });
  });
}
