import 'package:flutter_test/flutter_test.dart';
import 'package:carhero/utils/validators.dart';

void main() {
  group('Validators.email', () {
    test('returns null for valid email', () {
      expect(Validators.email('user@example.com'), isNull);
    });

    test('returns error for empty string', () {
      expect(Validators.email(''), isNotNull);
    });

    test('returns error for null', () {
      expect(Validators.email(null), isNotNull);
    });

    test('returns error for missing @', () {
      expect(Validators.email('userexample.com'), isNotNull);
    });

    test('returns error for missing dot', () {
      expect(Validators.email('user@example'), isNotNull);
    });

    test('accepts email with subdomain', () {
      expect(Validators.email('user@sub.example.com'), isNull);
    });
  });

  group('Validators.password', () {
    test('returns null for valid password', () {
      expect(Validators.password('secret123'), isNull);
    });

    test('returns error for empty string', () {
      expect(Validators.password(''), isNotNull);
    });

    test('returns error for null', () {
      expect(Validators.password(null), isNotNull);
    });

    test('returns error for short password', () {
      expect(Validators.password('abc'), isNotNull);
      expect(Validators.password('12345'), isNotNull);
    });

    test('accepts exactly 6 characters', () {
      expect(Validators.password('123456'), isNull);
    });
  });

  group('Validators.required', () {
    test('returns null for non-empty string', () {
      expect(Validators.required('hello'), isNull);
    });

    test('returns error for empty string', () {
      expect(Validators.required(''), isNotNull);
    });

    test('returns error for null', () {
      expect(Validators.required(null), isNotNull);
    });

    test('returns error for whitespace only', () {
      expect(Validators.required('   '), isNotNull);
    });
  });
}
