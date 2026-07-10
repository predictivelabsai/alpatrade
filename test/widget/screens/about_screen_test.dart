import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:carhero/config/theme.dart';
import 'package:carhero/screens/about_screen.dart';

Widget _wrapWidget(Widget child) {
  return MaterialApp(
    theme: AppTheme.light,
    routes: {'/contact': (_) => const Scaffold(body: Text('Contact Page'))},
    home: child,
  );
}

void main() {
  group('AboutScreen', () {
    testWidgets('renders app bar with title', (tester) async {
      await tester.pumpWidget(_wrapWidget(const AboutScreen()));

      expect(find.text('About'), findsOneWidget);
    });

    testWidgets('renders Kenri.ai branding', (tester) async {
      await tester.pumpWidget(_wrapWidget(const AboutScreen()));

      expect(find.text('Kenri.ai'), findsOneWidget);
      expect(find.text('Your Personal Advisor'), findsOneWidget);
      expect(find.text('K'), findsOneWidget);
    });

    testWidgets('renders Our Mission section', (tester) async {
      await tester.pumpWidget(_wrapWidget(const AboutScreen()));

      expect(find.text('Our Mission'), findsOneWidget);
      expect(find.textContaining('smarter decisions'), findsOneWidget);
    });

    testWidgets('renders Technology section', (tester) async {
      await tester.pumpWidget(_wrapWidget(const AboutScreen()));

      await tester.scrollUntilVisible(
        find.text('Technology'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.text('Technology'), findsOneWidget);
      expect(find.textContaining('multi-agent AI system'), findsOneWidget);
    });

    testWidgets('renders Get in Touch section', (tester) async {
      await tester.pumpWidget(_wrapWidget(const AboutScreen()));

      await tester.scrollUntilVisible(
        find.text('Get in Touch'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.text('Get in Touch'), findsOneWidget);
      expect(find.textContaining('feedback'), findsOneWidget);
    });

    testWidgets('renders Contact Us button', (tester) async {
      await tester.pumpWidget(_wrapWidget(const AboutScreen()));

      await tester.scrollUntilVisible(
        find.text('Contact Us'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.text('Contact Us'), findsOneWidget);
      expect(find.byType(OutlinedButton), findsOneWidget);
    });

    testWidgets('renders version footer', (tester) async {
      await tester.pumpWidget(_wrapWidget(const AboutScreen()));

      await tester.scrollUntilVisible(
        find.text('Kenri.ai v1.0.0'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.text('Kenri.ai v1.0.0'), findsOneWidget);
    });

    testWidgets('renders back button in app bar', (tester) async {
      await tester.pumpWidget(_wrapWidget(const AboutScreen()));

      expect(find.byIcon(Icons.arrow_back), findsOneWidget);
    });

    testWidgets('renders mission body text about personalised search', (
      tester,
    ) async {
      await tester.pumpWidget(_wrapWidget(const AboutScreen()));

      expect(find.textContaining('personalised search'), findsOneWidget);
    });

    testWidgets('renders technology body text about data pipeline', (
      tester,
    ) async {
      await tester.pumpWidget(_wrapWidget(const AboutScreen()));

      await tester.scrollUntilVisible(
        find.textContaining('data pipeline'),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.textContaining('data pipeline'), findsOneWidget);
    });

    testWidgets('renders mail icon in Contact Us button', (tester) async {
      await tester.pumpWidget(_wrapWidget(const AboutScreen()));

      await tester.scrollUntilVisible(
        find.byIcon(Icons.mail_outline),
        200,
        scrollable: find.byType(Scrollable).first,
      );

      expect(find.byIcon(Icons.mail_outline), findsOneWidget);
    });
  });
}
