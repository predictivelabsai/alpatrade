import 'package:flutter_test/flutter_test.dart';
import 'package:alpatrade/utils/formatters.dart';

void main() {
  group('Fmt.usd', () {
    test('formats positive and negative', () {
      expect(Fmt.usd(1234.5), r'$1,234.50');
      expect(Fmt.usd(-1234.5), r'-$1,234.50');
      expect(Fmt.usd(1000, decimals: 0), r'$1,000');
    });
    test('null -> dash', () => expect(Fmt.usd(null), '—'));
  });

  group('Fmt.signedUsd', () {
    test('adds explicit sign', () {
      expect(Fmt.signedUsd(20), r'+$20.00');
      expect(Fmt.signedUsd(-20), r'-$20.00');
      expect(Fmt.signedUsd(0), r'$0.00');
    });
  });

  group('Fmt.pct', () {
    test('signed and unsigned', () {
      expect(Fmt.pct(2.5), '2.50%');
      expect(Fmt.pct(2.5, signed: true), '+2.50%');
      expect(Fmt.pct(-2.5, signed: true), '-2.50%');
      expect(Fmt.pct(null), '—');
    });
  });

  group('Fmt.titleize', () {
    test('slug to title case', () {
      expect(Fmt.titleize('buy_the_dip'), 'Buy The Dip');
      expect(Fmt.titleize('btd-3dp-05sl'), 'Btd 3dp 05sl');
      expect(Fmt.titleize(null), '—');
    });
  });

  group('Fmt.shares', () {
    test('drops trailing .0', () {
      expect(Fmt.shares(3.0), '3');
      expect(Fmt.shares(2.5), '2.5');
      expect(Fmt.shares(null), '—');
    });
  });
}
