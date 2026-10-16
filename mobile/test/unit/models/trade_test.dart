import 'package:flutter_test/flutter_test.dart';
import 'package:alpatrade/models/trade.dart';

void main() {
  group('Trade.fromJson', () {
    test('parses a paper trade', () {
      final t = Trade.fromJson({
        'id': 15564,
        'run_id': 'a2ee',
        'trade_type': 'paper',
        'symbol': 'AMZN',
        'direction': 'sell',
        'shares': 3.0,
        'entry_price': 255.07,
        'exit_price': 253.57,
        'pnl': -4.52,
        'pnl_pct': -0.59,
        'reason': 'STOP_LOSS (-0.59%)',
      });
      expect(t.symbol, 'AMZN');
      expect(t.direction, 'sell');
      expect(t.pnl, -4.52);
      expect(t.tradeType, 'paper');
    });

    test('defaults trade_type and tolerates nulls', () {
      final t = Trade.fromJson({'run_id': 'r'});
      expect(t.tradeType, 'paper');
      expect(t.symbol, isNull);
      expect(t.shares, isNull);
    });
  });

  group('TradesResponse.fromJson', () {
    test('parses envelope', () {
      final r = TradesResponse.fromJson({
        'total': 1,
        'trades': [
          {'run_id': 'r', 'trade_type': 'paper', 'symbol': 'MSFT'},
        ],
      });
      expect(r.total, 1);
      expect(r.trades.single.symbol, 'MSFT');
    });

    test('empty when missing', () {
      final r = TradesResponse.fromJson({});
      expect(r.trades, isEmpty);
      expect(r.total, 0);
    });
  });
}
