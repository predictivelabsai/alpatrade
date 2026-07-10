import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:carhero/config/theme.dart';
import 'package:carhero/screens/contact_screen.dart';

Widget _wrapWidget(Widget child) {
  return ProviderScope(
    child: MaterialApp(theme: AppTheme.light, home: child),
  );
}

void main() {
  group('ContactScreen', () {
    testWidgets('renders app bar with title', (tester) async {
      await tester.pumpWidget(_wrapWidget(const ContactScreen()));

      expect(find.text('Contact Us'), findsOneWidget);
    });

    testWidgets('renders Get in Touch heading', (tester) async {
      await tester.pumpWidget(_wrapWidget(const ContactScreen()));

      expect(find.text('Get in Touch'), findsOneWidget);
    });

    testWidgets('renders form description text', (tester) async {
      await tester.pumpWidget(_wrapWidget(const ContactScreen()));

      expect(
        find.textContaining('question, suggestion, or need help'),
        findsOneWidget,
      );
    });

    testWidgets('renders Name field', (tester) async {
      await tester.pumpWidget(_wrapWidget(const ContactScreen()));

      expect(find.text('Name'), findsOneWidget);
      expect(find.byIcon(Icons.person_outline), findsOneWidget);
    });

    testWidgets('renders Email field', (tester) async {
      await tester.pumpWidget(_wrapWidget(const ContactScreen()));

      expect(find.text('Email'), findsOneWidget);
      expect(find.byIcon(Icons.email_outlined), findsOneWidget);
    });

    testWidgets('renders Message field', (tester) async {
      await tester.pumpWidget(_wrapWidget(const ContactScreen()));

      expect(find.text('Message'), findsOneWidget);
      expect(find.byIcon(Icons.message_outlined), findsOneWidget);
    });

    testWidgets('renders Send Message button', (tester) async {
      await tester.pumpWidget(_wrapWidget(const ContactScreen()));

      expect(find.text('Send Message'), findsOneWidget);
      expect(find.byType(ElevatedButton), findsOneWidget);
    });

    testWidgets('renders three TextFormField inputs', (tester) async {
      await tester.pumpWidget(_wrapWidget(const ContactScreen()));

      expect(find.byType(TextFormField), findsNWidgets(3));
    });

    testWidgets('renders back button in app bar', (tester) async {
      await tester.pumpWidget(_wrapWidget(const ContactScreen()));

      expect(find.byIcon(Icons.arrow_back), findsOneWidget);
    });

    testWidgets('shows validation error when Name is empty', (tester) async {
      await tester.pumpWidget(_wrapWidget(const ContactScreen()));

      // Tap Send without filling fields
      await tester.tap(find.text('Send Message'));
      await tester.pumpAndSettle();

      expect(find.text('Name is required'), findsOneWidget);
    });

    testWidgets('shows validation error when Email is empty', (tester) async {
      await tester.pumpWidget(_wrapWidget(const ContactScreen()));

      await tester.tap(find.text('Send Message'));
      await tester.pumpAndSettle();

      expect(find.text('Email is required'), findsOneWidget);
    });

    testWidgets('shows validation error when Message is empty', (tester) async {
      await tester.pumpWidget(_wrapWidget(const ContactScreen()));

      await tester.tap(find.text('Send Message'));
      await tester.pumpAndSettle();

      expect(find.text('Message is required'), findsOneWidget);
    });

    testWidgets('shows validation error for invalid email', (tester) async {
      await tester.pumpWidget(_wrapWidget(const ContactScreen()));

      // Fill name
      await tester.enterText(find.byType(TextFormField).at(0), 'John');
      // Fill invalid email
      await tester.enterText(find.byType(TextFormField).at(1), 'notanemail');
      // Fill message
      await tester.enterText(find.byType(TextFormField).at(2), 'Hello!');

      await tester.tap(find.text('Send Message'));
      await tester.pumpAndSettle();

      expect(find.text('Invalid email'), findsOneWidget);
    });

    testWidgets('no validation errors when all fields valid', (tester) async {
      await tester.pumpWidget(_wrapWidget(const ContactScreen()));

      // Fill all fields with valid data
      await tester.enterText(find.byType(TextFormField).at(0), 'John Doe');
      await tester.enterText(
        find.byType(TextFormField).at(1),
        'john@example.com',
      );
      await tester.enterText(
        find.byType(TextFormField).at(2),
        'I have a question about Kenri.ai.',
      );

      await tester.tap(find.text('Send Message'));
      await tester.pumpAndSettle();

      // No validation error messages
      expect(find.text('Name is required'), findsNothing);
      expect(find.text('Email is required'), findsNothing);
      expect(find.text('Invalid email'), findsNothing);
      expect(find.text('Message is required'), findsNothing);
    });

    testWidgets('shows all three validation errors at once', (tester) async {
      await tester.pumpWidget(_wrapWidget(const ContactScreen()));

      await tester.tap(find.text('Send Message'));
      await tester.pumpAndSettle();

      expect(find.text('Name is required'), findsOneWidget);
      expect(find.text('Email is required'), findsOneWidget);
      expect(find.text('Message is required'), findsOneWidget);
    });
  });
}
